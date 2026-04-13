from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gremlinboard_api.db import Base


class BoardRecord(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    widgets: Mapped[list["WidgetInstanceRecord"]] = relationship(
        back_populates="board", cascade="all, delete-orphan"
    )


class WidgetInstanceRecord(Base):
    __tablename__ = "widget_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid4().hex)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), nullable=False, index=True)
    widget_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[str] = mapped_column(String(8), nullable=False)
    position_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    board: Mapped["BoardRecord"] = relationship(back_populates="widgets")


class StagedWidgetSpecRecord(Base):
    __tablename__ = "staged_widget_specs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid4().hex)
    widget_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    scaffold_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
