from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


DotPath = Annotated[
    str,
    Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*(\[[0-9]+\])?(\.[a-zA-Z_][a-zA-Z0-9_]*(\[[0-9]+\])?)*$"),
]
StatusColor = Literal["critical", "warn", "ok", "neutral"]


class BlueprintModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShowIf(BlueprintModel):
    path: DotPath
    op: Literal["exists", "eq", "gt", "lt"]
    value: Any | None = None


class NodeBase(BlueprintModel):
    show_if: ShowIf | None = None


class LayoutNodeBase(NodeBase):
    gap: Literal["none", "sm", "md"] | None = None
    children: list[BlueprintNode] = Field(min_length=1)


class StackNode(LayoutNodeBase):
    type: Literal["stack"]


class RowNode(LayoutNodeBase):
    type: Literal["row"]


class GridNode(LayoutNodeBase):
    type: Literal["grid"]
    columns: int = Field(ge=2, le=4)


class ScrollNode(LayoutNodeBase):
    type: Literal["scroll"]


class StatusMappedNode(NodeBase):
    status_path: DotPath | None = None
    status_map: dict[str, StatusColor] | None = None


class StatNode(StatusMappedNode):
    type: Literal["stat"]
    label: str = Field(min_length=1)
    value_path: DotPath
    unit: str | None = None
    emphasis: Literal["primary", "secondary"] | None = None
    trend_path: DotPath | None = None


class TextNode(NodeBase):
    type: Literal["text"]
    value_path: DotPath | None = None
    literal: str | None = None
    variant: Literal["title", "body", "caption", "mono"]

    @model_validator(mode="after")
    def validate_text_source(self) -> TextNode:
        if (self.value_path is None) == (self.literal is None):
            raise ValueError("text node must define exactly one of value_path or literal")
        return self


class BadgeItem(BlueprintModel):
    label_path: DotPath | None = None
    literal: str | None = None
    status_path: DotPath | None = None
    status_map: dict[str, StatusColor] | None = None

    @model_validator(mode="after")
    def validate_label_source(self) -> BadgeItem:
        if (self.label_path is None) == (self.literal is None):
            raise ValueError("badge item must define exactly one of label_path or literal")
        return self


class BadgeRowNode(NodeBase):
    type: Literal["badge_row"]
    items: list[BadgeItem] = Field(min_length=1)


class ListItem(BlueprintModel):
    primary_path: DotPath
    secondary_path: DotPath | None = None
    meta_path: DotPath | None = None
    href_path: DotPath | None = None
    status_path: DotPath | None = None
    status_map: dict[str, StatusColor] | None = None


class ListNode(NodeBase):
    type: Literal["list"]
    items_path: DotPath
    limit: int | None = Field(default=None, ge=1)
    item: ListItem


class TableColumn(BlueprintModel):
    header: str = Field(min_length=1)
    value_path: DotPath
    align: Literal["left", "center", "right"] | None = None


class TableNode(NodeBase):
    type: Literal["table"]
    items_path: DotPath
    limit: int | None = Field(default=None, ge=1)
    columns: list[TableColumn] = Field(min_length=1)


class KeyValueEntry(BlueprintModel):
    label: str = Field(min_length=1)
    value_path: DotPath


class KeyValueNode(NodeBase):
    type: Literal["key_value"]
    entries: list[KeyValueEntry] | None = Field(default=None, min_length=1)
    entries_path: DotPath | None = None

    @model_validator(mode="after")
    def validate_entries_source(self) -> KeyValueNode:
        if (self.entries is None) == (self.entries_path is None):
            raise ValueError("key_value node must define exactly one of entries or entries_path")
        return self


class ProgressNode(NodeBase):
    type: Literal["progress"]
    value_path: DotPath
    max_path: DotPath | None = None
    max_literal: float | None = None
    label: str | None = None

    @model_validator(mode="after")
    def validate_max_source(self) -> ProgressNode:
        if self.max_path is not None and self.max_literal is not None:
            raise ValueError("progress node must not define both max_path and max_literal")
        return self


class SparklineNode(NodeBase):
    type: Literal["sparkline"]
    values_path: DotPath
    label: str | None = None


class TimerNode(NodeBase):
    type: Literal["timer"]
    target_path: DotPath
    direction: Literal["down", "up"]
    label_path: DotPath | None = None


class EmptyStateNode(NodeBase):
    type: Literal["empty_state"]
    message: str = Field(min_length=1)
    show_if_empty_path: DotPath


class ActionButtonNode(NodeBase):
    type: Literal["action_button"]
    label: str = Field(min_length=1)
    action: Literal["refresh", "config_patch"]
    config_patch: dict[str, Any] | None = None
    style: Literal["primary", "secondary"] | None = None

    @model_validator(mode="after")
    def validate_config_patch(self) -> ActionButtonNode:
        if self.action == "config_patch" and not self.config_patch:
            raise ValueError("config_patch action requires a non-empty config_patch")
        if self.action == "refresh" and self.config_patch is not None:
            raise ValueError("config_patch must be None for refresh action")
        return self


BlueprintNode = Annotated[
    StackNode
    | RowNode
    | GridNode
    | ScrollNode
    | StatNode
    | TextNode
    | BadgeRowNode
    | ListNode
    | TableNode
    | KeyValueNode
    | ProgressNode
    | SparklineNode
    | TimerNode
    | EmptyStateNode
    | ActionButtonNode,
    Field(discriminator="type"),
]


class BlueprintLayouts(BlueprintModel):
    compact: BlueprintNode | None = None
    medium: BlueprintNode
    wide: BlueprintNode | None = None
    tall: BlueprintNode | None = None
    large: BlueprintNode | None = None


class Blueprint(BlueprintModel):
    blueprint_version: Literal["1"]
    widget_id: str = Field(min_length=1)
    layouts: BlueprintLayouts
    defaults: dict[str, BlueprintNode] | None = None


def validate_blueprint(data: dict[str, Any]) -> Blueprint:
    try:
        return Blueprint.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
        raise ValueError(f"invalid widget blueprint: {details}") from exc


def collect_binding_paths(blueprint: Blueprint) -> set[str]:
    paths: set[str] = set()

    def add(value: str | None) -> None:
        if value is not None:
            paths.add(value)

    def collect_from_show_if(show_if: ShowIf | None) -> None:
        if show_if is not None:
            add(show_if.path)

    def collect_from_nodes(nodes: Iterable[BlueprintNode | None]) -> None:
        for node in nodes:
            if node is not None:
                collect_from_node(node)

    def collect_from_node(node: BlueprintNode) -> None:
        collect_from_show_if(node.show_if)
        if isinstance(node, LayoutNodeBase):
            collect_from_nodes(node.children)
        elif isinstance(node, StatNode):
            add(node.value_path)
            add(node.trend_path)
            add(node.status_path)
        elif isinstance(node, TextNode):
            add(node.value_path)
        elif isinstance(node, BadgeRowNode):
            for item in node.items:
                add(item.label_path)
                add(item.status_path)
        elif isinstance(node, ListNode):
            add(node.items_path)
            add(node.item.primary_path)
            add(node.item.secondary_path)
            add(node.item.meta_path)
            add(node.item.href_path)
            add(node.item.status_path)
        elif isinstance(node, TableNode):
            add(node.items_path)
            for column in node.columns:
                add(column.value_path)
        elif isinstance(node, KeyValueNode):
            add(node.entries_path)
            for entry in node.entries or []:
                add(entry.value_path)
        elif isinstance(node, ProgressNode):
            add(node.value_path)
            add(node.max_path)
        elif isinstance(node, SparklineNode):
            add(node.values_path)
        elif isinstance(node, TimerNode):
            add(node.target_path)
            add(node.label_path)
        elif isinstance(node, EmptyStateNode):
            add(node.show_if_empty_path)

    collect_from_nodes(
        [
            blueprint.layouts.compact,
            blueprint.layouts.medium,
            blueprint.layouts.wide,
            blueprint.layouts.tall,
            blueprint.layouts.large,
        ]
    )
    if blueprint.defaults:
        collect_from_nodes(blueprint.defaults.values())
    return paths


for model in (
    StackNode,
    RowNode,
    GridNode,
    ScrollNode,
    StatNode,
    TextNode,
    BadgeRowNode,
    ListNode,
    TableNode,
    KeyValueNode,
    ProgressNode,
    SparklineNode,
    TimerNode,
    EmptyStateNode,
    ActionButtonNode,
    BlueprintLayouts,
    Blueprint,
):
    model.model_rebuild()

