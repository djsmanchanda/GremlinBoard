from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.models.tables import BoardRecord, RuntimeLogRecord, StagedWidgetSpecRecord, WidgetInstanceRecord
from gremlinboard_api.schemas.contracts import (
    BoardRead,
    LifecycleState,
    RuntimeLogRead,
    TileSize,
    WidgetInstanceRead,
)


class BoardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_board(self, board_id: str, name: str, owner_user_id: str | None = None) -> BoardRecord:
        board = await self.session.get(BoardRecord, board_id)
        if board is None:
            board = BoardRecord(id=board_id, name=name, owner_user_id=owner_user_id)
            self.session.add(board)
            await self.session.commit()
            await self.session.refresh(board)
        elif owner_user_id is not None and board.owner_user_id is None:
            board.owner_user_id = owner_user_id
            await self.session.commit()
            await self.session.refresh(board)
        return board

    async def list_widgets(self, board_id: str) -> list[WidgetInstanceRecord]:
        result = await self.session.execute(
            select(WidgetInstanceRecord)
            .where(WidgetInstanceRecord.board_id == board_id, WidgetInstanceRecord.is_removed.is_(False))
            .order_by(WidgetInstanceRecord.position_index.asc(), WidgetInstanceRecord.created_at.asc())
        )
        return list(result.scalars())

    async def get_widget(self, widget_instance_id: str) -> WidgetInstanceRecord | None:
        return await self.session.get(WidgetInstanceRecord, widget_instance_id)

    async def create_widget(
        self,
        *,
        board_id: str,
        owner_user_id: str | None,
        widget_id: str,
        title: str,
        size: TileSize,
        position_index: int,
        config: dict[str, Any],
        lifecycle_state: LifecycleState,
        expires_at,
    ) -> WidgetInstanceRecord:
        record = WidgetInstanceRecord(
            board_id=board_id,
            owner_user_id=owner_user_id,
            widget_id=widget_id,
            title=title,
            size=size.value,
            position_index=position_index,
            config_json=json.dumps(config),
            state_json=json.dumps({}),
            lifecycle_state=lifecycle_state.value,
            expires_at=expires_at,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update_widget(
        self,
        record: WidgetInstanceRecord,
        *,
        title: str | None = None,
        size: TileSize | None = None,
        position_index: int | None = None,
        config: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        lifecycle_state: LifecycleState | None = None,
        status_message: str | None = None,
        freshness_at=None,
        expires_at=False,
        last_error: str | None = None,
        clear_error: bool = False,
        last_heartbeat=None,
        service_started_at=None,
        service_uptime_seconds: int | None = None,
        restart_count: int | None = None,
        consecutive_failures: int | None = None,
        is_removed: bool | None = None,
    ) -> WidgetInstanceRecord:
        if title is not None:
            record.title = title
        if size is not None:
            record.size = size.value
        if position_index is not None:
            record.position_index = position_index
        if config is not None:
            record.config_json = json.dumps(config)
        if state is not None:
            record.state_json = json.dumps(state)
        if lifecycle_state is not None:
            record.lifecycle_state = lifecycle_state.value
        if status_message is not None:
            record.status_message = status_message
        if freshness_at is not None:
            record.freshness_at = freshness_at
        if expires_at is not False:
            record.expires_at = expires_at
        if clear_error:
            record.last_error = None
        elif last_error is not None:
            record.last_error = last_error
        if last_heartbeat is not None:
            record.last_heartbeat = last_heartbeat
        if service_started_at is not None:
            record.service_started_at = service_started_at
        if service_uptime_seconds is not None:
            record.service_uptime_seconds = service_uptime_seconds
        if restart_count is not None:
            record.restart_count = restart_count
        if consecutive_failures is not None:
            record.consecutive_failures = consecutive_failures
        if is_removed is not None:
            record.is_removed = is_removed
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def reorder_widgets(self, board_id: str, ordered_ids: list[str]) -> None:
        widgets = await self.list_widgets(board_id)
        widgets_by_id = {widget.id: widget for widget in widgets}
        for index, widget_id in enumerate(ordered_ids):
            widget = widgets_by_id.get(widget_id)
            if widget is not None:
                widget.position_index = index
        await self.session.commit()

    async def create_staged_spec(
        self,
        *,
        widget_id: str,
        stage: str,
        spec: dict[str, Any],
        scaffold_preview: dict[str, Any],
        notes: list[str],
    ) -> StagedWidgetSpecRecord:
        record = StagedWidgetSpecRecord(
            widget_id=widget_id,
            stage=stage,
            spec_json=json.dumps(spec),
            scaffold_json=json.dumps(scaffold_preview),
            validation_notes=json.dumps(notes),
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def count_widget_instances_by_widget_id(self, widget_id: str) -> int:
        result = await self.session.execute(
            select(WidgetInstanceRecord).where(
                WidgetInstanceRecord.widget_id == widget_id,
                WidgetInstanceRecord.is_removed.is_(False),
            )
        )
        return len(list(result.scalars()))

    async def list_widget_instances_by_widget_id(self, widget_id: str) -> list[WidgetInstanceRecord]:
        result = await self.session.execute(
            select(WidgetInstanceRecord).where(
                WidgetInstanceRecord.widget_id == widget_id,
                WidgetInstanceRecord.is_removed.is_(False),
            )
        )
        return list(result.scalars())

    async def create_runtime_log(
        self,
        *,
        widget_instance_id: str | None,
        widget_id: str | None,
        level: str,
        event: str,
        message: str,
        context: dict[str, Any],
    ) -> RuntimeLogRecord:
        record = RuntimeLogRecord(
            widget_instance_id=widget_instance_id,
            widget_id=widget_id,
            level=level,
            event=event,
            message=message,
            context_json=json.dumps(context),
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_runtime_logs(self, limit: int = 100) -> list[RuntimeLogRecord]:
        result = await self.session.execute(
            select(RuntimeLogRecord).order_by(RuntimeLogRecord.created_at.desc()).limit(limit)
        )
        return list(result.scalars())


def serialize_widget(record: WidgetInstanceRecord, *, blueprint: dict[str, Any] | None = None) -> WidgetInstanceRead:
    return WidgetInstanceRead(
        id=record.id,
        board_id=record.board_id,
        owner_user_id=record.owner_user_id,
        widget_id=record.widget_id,
        title=record.title,
        size=TileSize(record.size),
        position_index=record.position_index,
        config=json.loads(record.config_json or "{}"),
        state=json.loads(record.state_json or "{}"),
        lifecycle_state=LifecycleState(record.lifecycle_state),
        status_message=record.status_message,
        freshness_at=record.freshness_at,
        expires_at=record.expires_at,
        last_error=record.last_error,
        last_heartbeat=record.last_heartbeat,
        service_started_at=record.service_started_at,
        service_uptime_seconds=record.service_uptime_seconds,
        restart_count=record.restart_count,
        consecutive_failures=record.consecutive_failures,
        blueprint=blueprint,
    )


def serialize_board(
    board: BoardRecord,
    widgets: list[WidgetInstanceRecord],
    *,
    blueprints_by_widget_id: dict[str, dict[str, Any]] | None = None,
) -> BoardRead:
    blueprints = blueprints_by_widget_id or {}
    return BoardRead(
        id=board.id,
        name=board.name,
        owner_user_id=board.owner_user_id,
        widgets=[serialize_widget(widget, blueprint=blueprints.get(widget.widget_id)) for widget in widgets],
    )


def serialize_runtime_log(record: RuntimeLogRecord) -> RuntimeLogRead:
    return RuntimeLogRead(
        id=record.id,
        widget_instance_id=record.widget_instance_id,
        widget_id=record.widget_id,
        level=record.level,
        event=record.event,
        message=record.message,
        context=json.loads(record.context_json or "{}"),
        created_at=record.created_at,
    )
