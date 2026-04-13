from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    provider_id: str
    label: str

    @property
    def supports_codegen(self) -> bool:
        return True

    @property
    def supports_review(self) -> bool:
        return True

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def build_generation_plan(self, *, widget_spec: dict[str, Any], stage_id: str) -> dict[str, Any]:
        raise NotImplementedError


class CodexProvider(AIProvider):
    provider_id = "codex"
    label = "Codex"

    async def health(self) -> dict[str, Any]:
        return {"status": "stubbed", "provider_id": self.provider_id}

    async def build_generation_plan(self, *, widget_spec: dict[str, Any], stage_id: str) -> dict[str, Any]:
        return {
            "stage_id": stage_id,
            "provider_id": self.provider_id,
            "steps": [
                {"id": "spec", "label": "Confirm validated spec", "status": "ready"},
                {"id": "scaffold", "label": "Generate scaffold patch set", "status": "placeholder"},
                {"id": "codegen", "label": "Prepare service and renderer generation request", "status": "placeholder"},
                {"id": "review", "label": "Require human review before install", "status": "required"},
            ],
            "widget_id": widget_spec.get("id"),
        }


class ClaudeProvider(AIProvider):
    provider_id = "claude"
    label = "Claude"

    async def health(self) -> dict[str, Any]:
        return {"status": "stubbed", "provider_id": self.provider_id}

    async def build_generation_plan(self, *, widget_spec: dict[str, Any], stage_id: str) -> dict[str, Any]:
        return {
            "stage_id": stage_id,
            "provider_id": self.provider_id,
            "steps": [
                {"id": "spec", "label": "Confirm validated spec", "status": "ready"},
                {"id": "cleanup", "label": "Prepare refinement and cleanup pass", "status": "placeholder"},
                {"id": "review", "label": "Require human review before install", "status": "required"},
            ],
            "widget_id": widget_spec.get("id"),
        }
