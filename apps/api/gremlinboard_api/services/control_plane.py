from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from gremlinboard_api.config import settings
from gremlinboard_api.repositories.board import BoardRepository, serialize_board, serialize_widget
from gremlinboard_api.schemas.contracts import (
    LifecycleState,
    RuntimeEventCategory,
    RuntimeEventLevel,
    RuntimeEventPersistence,
    RuntimeEventSource,
    RuntimeEventVisibility,
    PresenceSource,
    WidgetConfigUpdate,
    WidgetCreate,
    WidgetResize,
)
from gremlinboard_api.schemas.control import (
    ControlActionDefinitionRead,
    ControlActionResponse,
    ControlAgentsListParams,
    ControlApprovalRead,
    ControlEmptyParams,
    ControlJobsListParams,
    ControlMcpToolRead,
    ControlWidgetAddParams,
    ControlWidgetInstanceParams,
    ControlWidgetResizeParams,
    ControlWidgetSettingsParams,
    new_control_correlation_id,
    utc_now,
)
from gremlinboard_api.validation.config_schema import ConfigValidationError, normalize_config


class ControlPlaneError(Exception):
    """Caller-correctable control plane failure."""


class ControlApprovalNotFound(ControlPlaneError):
    pass


ActionHandler = Callable[[BaseModel, "ControlExecutionContext"], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ControlAction:
    action_id: str
    description: str
    params_model: type[BaseModel]
    handler: ActionHandler
    destructive: bool = False
    approval_required: bool = False


@dataclass(frozen=True, slots=True)
class ControlExecutionContext:
    source: str
    user_id: str | None
    correlation_id: str
    causation_id: str | None
    approved: bool = False


class ControlPlaneService:
    def __init__(
        self,
        *,
        session_factory: Any,
        registry: Any,
        plugin_manager: Any,
        runtime_manager: Any,
        event_bus: Any,
        presence_manager: Any,
        generation_pipeline: Any,
        agent_registry: Any,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.plugin_manager = plugin_manager
        self.runtime_manager = runtime_manager
        self.event_bus = event_bus
        self.presence_manager = presence_manager
        self.generation_pipeline = generation_pipeline
        self.agent_registry = agent_registry
        self._approvals: dict[str, ControlApprovalRead] = {}
        self._actions: dict[str, ControlAction] = self._build_actions()

    def action_definitions(self) -> list[ControlActionDefinitionRead]:
        return [
            ControlActionDefinitionRead(
                action_id=action.action_id,
                description=action.description,
                input_schema=action.params_model.model_json_schema(),
                destructive=action.destructive,
                approval_required=action.approval_required,
            )
            for action in self._actions.values()
        ]

    def mcp_tools(self) -> list[ControlMcpToolRead]:
        return [
            ControlMcpToolRead(
                name=self._tool_name(action.action_id),
                description=action.description,
                input_schema=action.params_model.model_json_schema(),
                action_id=action.action_id,
                destructive=action.destructive,
                approval_required=action.approval_required,
            )
            for action in self._actions.values()
        ]

    def list_approvals(self) -> list[ControlApprovalRead]:
        return sorted(self._approvals.values(), key=lambda approval: approval.requested_at, reverse=True)

    async def execute_action(
        self,
        action_id: str,
        *,
        params: dict[str, Any] | None = None,
        source: str,
        user_id: str | None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        approved: bool = False,
    ) -> ControlActionResponse:
        action = self._actions.get(action_id)
        if action is None:
            raise ControlPlaneError(f"unknown control action '{action_id}'")
        resolved_correlation_id = correlation_id or new_control_correlation_id()
        try:
            typed_params = action.params_model.model_validate(params or {})
        except ValidationError as exc:
            raise ControlPlaneError(str(exc)) from exc

        context = ControlExecutionContext(
            source=source,
            user_id=user_id,
            correlation_id=resolved_correlation_id,
            causation_id=causation_id,
            approved=approved,
        )
        if action.approval_required and not approved:
            approval = await self._request_approval(action=action, params=typed_params, context=context)
            return ControlActionResponse(
                action_id=action.action_id,
                status="approval_required",
                message=f"approval required before running {action.action_id}",
                correlation_id=resolved_correlation_id,
                causation_id=causation_id,
                event_id=approval.id,
                approval=approval,
            )

        await self._publish_action_event("operator.control.started", action, typed_params, context)
        payload = await action.handler(typed_params, context)
        event = await self._publish_action_event("operator.control.completed", action, typed_params, context)
        return ControlActionResponse(
            action_id=action.action_id,
            status="completed",
            message=f"{action.action_id} completed",
            payload=payload,
            correlation_id=resolved_correlation_id,
            causation_id=causation_id,
            event_id=event.id,
        )

    async def call_mcp_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str | None,
        correlation_id: str | None,
        causation_id: str | None,
    ) -> ControlActionResponse:
        action_id = self._action_id_from_tool_name(tool_name)
        return await self.execute_action(
            action_id,
            params=arguments,
            source="mcp",
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    async def approve(self, approval_id: str, *, source: str, note: str | None) -> ControlActionResponse:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ControlApprovalNotFound(f"unknown approval '{approval_id}'")
        if approval.status != "pending":
            raise ControlPlaneError(f"approval '{approval_id}' is already {approval.status}")
        resolved = approval.model_copy(
            update={
                "status": "approved",
                "resolved_at": utc_now(),
                "resolution_note": note,
            }
        )
        self._approvals[approval_id] = resolved
        await self._publish_approval_event("operator.control.approved", resolved, source=source)
        return await self.execute_action(
            approval.action_id,
            params=approval.params,
            source=source,
            user_id=None,
            correlation_id=approval.correlation_id,
            causation_id=approval.id,
            approved=True,
        )

    async def reject(self, approval_id: str, *, source: str, note: str | None) -> ControlActionResponse:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ControlApprovalNotFound(f"unknown approval '{approval_id}'")
        if approval.status != "pending":
            raise ControlPlaneError(f"approval '{approval_id}' is already {approval.status}")
        resolved = approval.model_copy(
            update={
                "status": "rejected",
                "resolved_at": utc_now(),
                "resolution_note": note,
            }
        )
        self._approvals[approval_id] = resolved
        event = await self._publish_approval_event("operator.control.rejected", resolved, source=source)
        return ControlActionResponse(
            action_id=approval.action_id,
            status="rejected",
            message=f"{approval.action_id} rejected",
            correlation_id=approval.correlation_id,
            causation_id=approval.id,
            event_id=event.id,
            approval=resolved,
        )

    def _build_actions(self) -> dict[str, ControlAction]:
        actions = [
            ControlAction("widgets.list", "List board widget instances.", ControlEmptyParams, self._widgets_list),
            ControlAction("widgets.add", "Add a registered widget to the board.", ControlWidgetAddParams, self._widgets_add),
            ControlAction(
                "widgets.remove",
                "Remove a widget instance from the board.",
                ControlWidgetInstanceParams,
                self._widgets_remove,
                destructive=True,
                approval_required=True,
            ),
            ControlAction("widgets.restart", "Restart a widget runner.", ControlWidgetInstanceParams, self._widgets_restart),
            ControlAction("widgets.pause", "Pause a widget runner.", ControlWidgetInstanceParams, self._widgets_pause),
            ControlAction("widgets.resume", "Resume a widget runner.", ControlWidgetInstanceParams, self._widgets_resume),
            ControlAction("widgets.resize", "Resize a widget using an allowed tile size.", ControlWidgetResizeParams, self._widgets_resize),
            ControlAction(
                "widgets.configure",
                "Change a widget title and provider/source settings through its typed config.",
                ControlWidgetSettingsParams,
                self._widgets_configure,
            ),
            ControlAction("board.snapshot", "Inspect the current board snapshot.", ControlEmptyParams, self._board_snapshot),
            ControlAction("runtime.status", "Inspect runtime state and queues.", ControlEmptyParams, self._runtime_status),
            ControlAction("runtime.suspend", "Suspend scheduled runtime work.", ControlEmptyParams, self._runtime_suspend),
            ControlAction("runtime.resume", "Resume scheduled runtime work.", ControlEmptyParams, self._runtime_resume),
            ControlAction("jobs.list", "Inspect generation jobs.", ControlJobsListParams, self._jobs_list),
            ControlAction("agents.list", "Inspect agent sessions and tasks.", ControlAgentsListParams, self._agents_list),
        ]
        return {action.action_id: action for action in actions}

    async def _widgets_list(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        return (await self._read_board()).widgets

    async def _widgets_add(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = WidgetCreate.model_validate(params.model_dump())
        if not await self.plugin_manager.is_enabled(payload.widget_id):
            raise ControlPlaneError("widget plugin is disabled or not installed")
        try:
            loaded = self.registry.get(payload.widget_id)
        except KeyError as exc:
            raise ControlPlaneError(str(exc)) from exc
        if payload.size not in loaded.manifest.allowed_sizes:
            raise ControlPlaneError("requested size is not supported by this widget")
        try:
            normalized_config = normalize_config(loaded.config_schema, payload.config)
        except ConfigValidationError as exc:
            raise ControlPlaneError(str(exc.errors)) from exc

        async with self.session_factory() as session:
            repository = BoardRepository(session)
            owner_user_id = context.user_id or settings.default_user_id
            await repository.ensure_board(settings.default_board_id, "GremlinBoard", owner_user_id=owner_user_id)
            widgets = await repository.list_widgets(settings.default_board_id)
            expires_at = None
            if loaded.manifest.lifecycle_policy.expires and loaded.manifest.lifecycle_policy.default_ttl_seconds:
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=loaded.manifest.lifecycle_policy.default_ttl_seconds
                )
            record = await repository.create_widget(
                board_id=settings.default_board_id,
                owner_user_id=owner_user_id,
                widget_id=payload.widget_id,
                title=payload.title or loaded.manifest.name,
                size=payload.size,
                position_index=len(widgets),
                config=normalized_config,
                lifecycle_state=LifecycleState.CREATED,
                expires_at=expires_at,
            )
            widget_id = record.id
        await self.runtime_manager.start_widget(widget_id)
        return await self._widget_payload(widget_id)

    async def _widgets_remove(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = ControlWidgetInstanceParams.model_validate(params.model_dump())
        widget_instance_id = payload.widget_instance_id
        await self.runtime_manager.stop_widget(widget_instance_id, removed=True, reason=f"{context.source} requested remove")
        return await self._read_board()

    async def _widgets_restart(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = ControlWidgetInstanceParams.model_validate(params.model_dump())
        widget_instance_id = payload.widget_instance_id
        await self.runtime_manager.restart_widget(widget_instance_id, reason=f"{context.source} requested restart")
        return await self._widget_payload(widget_instance_id)

    async def _widgets_pause(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = ControlWidgetInstanceParams.model_validate(params.model_dump())
        widget_instance_id = payload.widget_instance_id
        await self.runtime_manager.stop_widget(
            widget_instance_id,
            final_state=LifecycleState.PAUSED,
            reason=f"{context.source} requested pause",
        )
        return await self._widget_payload(widget_instance_id)

    async def _widgets_resume(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = ControlWidgetInstanceParams.model_validate(params.model_dump())
        widget_instance_id = payload.widget_instance_id
        await self.runtime_manager.start_widget(widget_instance_id, force=True)
        return await self._widget_payload(widget_instance_id)

    async def _widgets_resize(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = WidgetResize.model_validate(params.model_dump())
        widget_instance_id = ControlWidgetResizeParams.model_validate(params.model_dump()).widget_instance_id
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(widget_instance_id)
            if record is None or record.is_removed:
                raise ControlPlaneError("widget instance not found")
            manifest = self.registry.get(record.widget_id).manifest
            if payload.size not in manifest.allowed_sizes:
                raise ControlPlaneError("requested size is not supported by this widget")
            updated = await repository.update_widget(record, size=payload.size)
        await self.runtime_manager.publish_board_snapshot()
        return serialize_widget(updated)

    async def _widgets_configure(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = WidgetConfigUpdate.model_validate(params.model_dump(exclude={"widget_instance_id"}))
        widget_instance_id = ControlWidgetSettingsParams.model_validate(params.model_dump()).widget_instance_id
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(widget_instance_id)
            if record is None or record.is_removed:
                raise ControlPlaneError("widget instance not found")
            current_config = serialize_widget(record).config
            next_config = payload.config if payload.config is not None else current_config
            try:
                loaded = self.registry.get(record.widget_id)
                normalized_config = normalize_config(loaded.config_schema, next_config)
            except ConfigValidationError as exc:
                raise ControlPlaneError(str(exc.errors)) from exc
            updated = await repository.update_widget(
                record,
                title=payload.title or record.title,
                config=normalized_config,
            )
        await self.runtime_manager.update_widget_config(widget_instance_id, normalized_config)
        return serialize_widget(updated)

    async def _board_snapshot(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        return await self._read_board()

    async def _runtime_status(self, params: BaseModel, context: ControlExecutionContext) -> dict[str, Any]:
        event_stats = self.event_bus.stats()
        presence = await self.presence_manager.snapshot(degraded=False, reason=None)
        return {
            "state": presence.state.value,
            "presence": presence.model_dump(mode="json"),
            "active_runners": self.runtime_manager.active_count,
            "websocket_subscribers": self.event_bus.websocket_subscriber_count,
            "monitor_cadence_seconds": self.runtime_manager.monitor_interval_seconds,
            "queue_depth": event_stats.queued_event_count,
            "dropped_event_count": event_stats.dropped_event_count,
            "latest_sequence": event_stats.latest_sequence,
            "registry_size": self.registry.size,
            "runners": self.runtime_manager.runner_statuses(),
            "agents": self.agent_registry.summary().model_dump(mode="json"),
            "generation_queue": self.generation_pipeline.queue_status(),
        }

    async def _runtime_suspend(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        await self.presence_manager.record_activity(self._presence_source(context.source))
        return await self.presence_manager.suspend(reason=f"{context.source} requested suspend")

    async def _runtime_resume(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        return await self.presence_manager.resume(source=self._presence_source(context.source))

    async def _jobs_list(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = ControlJobsListParams.model_validate(params.model_dump())
        return await self.generation_pipeline.list_jobs(widget_id=payload.widget_id)

    async def _agents_list(self, params: BaseModel, context: ControlExecutionContext) -> Any:
        payload = ControlAgentsListParams.model_validate(params.model_dump())
        return await self.agent_registry.list_agents(status=payload.status, type=payload.type, source=payload.source)

    async def _read_board(self) -> Any:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            board = await repository.ensure_board(settings.default_board_id, "GremlinBoard")
            widgets = await repository.list_widgets(settings.default_board_id)
            return serialize_board(board, widgets)

    async def _widget_payload(self, widget_instance_id: str) -> Any:
        async with self.session_factory() as session:
            repository = BoardRepository(session)
            record = await repository.get_widget(widget_instance_id)
            if record is None:
                raise ControlPlaneError("widget instance not found")
            return serialize_widget(record)

    async def _request_approval(
        self,
        *,
        action: ControlAction,
        params: BaseModel,
        context: ControlExecutionContext,
    ) -> ControlApprovalRead:
        approval = ControlApprovalRead(
            id=f"approval-{uuid4().hex}",
            action_id=action.action_id,
            params=params.model_dump(mode="json"),
            source=context.source,
            reason=f"{action.action_id} is destructive and requires approval",
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
            requested_at=utc_now(),
        )
        self._approvals[approval.id] = approval
        await self._publish_approval_event("operator.control.approval_required", approval, source=context.source)
        return approval

    async def _publish_action_event(
        self,
        event_type: str,
        action: ControlAction,
        params: BaseModel,
        context: ControlExecutionContext,
    ) -> Any:
        return await self.event_bus.publish_event(
            event_type,
            category=RuntimeEventCategory.OPERATOR,
            level=RuntimeEventLevel.WARNING if action.destructive else RuntimeEventLevel.INFO,
            message=f"GremlinControl {action.action_id}",
            source=RuntimeEventSource(
                component="gremlincontrol",
                board_id=settings.default_board_id,
                user_id=context.user_id,
            ),
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
            visibility=RuntimeEventVisibility.BOTH,
            persistence=RuntimeEventPersistence.TIMELINE
            if action.destructive or event_type.endswith(".completed")
            else RuntimeEventPersistence.EPHEMERAL,
            replayable=True,
            payload={
                "action_id": action.action_id,
                "source": context.source,
                "destructive": action.destructive,
                "approval_required": action.approval_required,
                "params": params.model_dump(mode="json"),
            },
        )

    async def _publish_approval_event(self, event_type: str, approval: ControlApprovalRead, *, source: str) -> Any:
        return await self.event_bus.publish_event(
            event_type,
            category=RuntimeEventCategory.OPERATOR,
            level=RuntimeEventLevel.WARNING,
            message=f"GremlinControl approval {approval.status}",
            source=RuntimeEventSource(component="gremlincontrol", board_id=settings.default_board_id),
            correlation_id=approval.correlation_id,
            causation_id=approval.causation_id,
            visibility=RuntimeEventVisibility.BOTH,
            persistence=RuntimeEventPersistence.TIMELINE,
            replayable=True,
            payload={**approval.model_dump(mode="json"), "source": source},
        )

    @staticmethod
    def _tool_name(action_id: str) -> str:
        return f"gremlinboard_{action_id.replace('.', '_')}"

    def _action_id_from_tool_name(self, tool_name: str) -> str:
        for action_id in self._actions:
            if self._tool_name(action_id) == tool_name:
                return action_id
        raise ControlPlaneError(f"unknown MCP tool '{tool_name}'")

    @staticmethod
    def _presence_source(source: str) -> PresenceSource:
        try:
            return PresenceSource(source)
        except ValueError:
            return PresenceSource.OPERATOR
