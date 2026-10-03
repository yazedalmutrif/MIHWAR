"""Shared building blocks for every agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    """What one agent operation returns to the orchestrator (becomes one trace step)."""

    output: dict
    input_summary: str
    output_summary: str
    status: str = "ok"  # ok | denied | error | skipped
    mode: str = "offline"  # offline | llm | offline-fallback
    input: dict | None = None


@dataclass
class Check:
    name_en: str
    name_ar: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"name_en": self.name_en, "name_ar": self.name_ar, "passed": bool(self.passed), "detail": self.detail}


class DomainError(Exception):
    """A business-rule rejection (maps to an HTTP 4xx), e.g. an illegal state transition."""

    def __init__(self, code: str, message_ar: str, message_en: str, status: int = 409, extra: dict | None = None):
        super().__init__(message_en)
        self.code = code
        self.message_ar = message_ar
        self.message_en = message_en
        self.status = status
        self.extra = extra or {}


class BaseAgent:
    key: str = ""
    order: int = 0
    name_ar: str = ""
    name_en: str = ""
    role_ar: str = ""
    role_en: str = ""
    triggers: tuple[str, ...] = ()
    outputs_ar: str = ""
    llm_capable: bool = False
    challenge_phrase_ar: str = ""
    kpi_ar: str = ""

    def __init__(self, ctx):
        self.ctx = ctx

    # helpers ------------------------------------------------------------
    @property
    def db(self):
        return self.ctx.db

    def effective_mode(self) -> str:
        return "llm" if (self.llm_capable and self.ctx.llm.enabled) else "offline"

    def run(self, op: str, **payload: Any) -> StepResult:
        fn = getattr(self, f"op_{op}", None)
        if fn is None:
            raise ValueError(f"agent '{self.key}' has no operation '{op}'")
        return fn(**payload)

    def self_test(self) -> list[Check]:  # pragma: no cover - every agent overrides it
        raise NotImplementedError

    @staticmethod
    def check(name_en: str, name_ar: str, condition: bool, detail: str = "") -> Check:
        return Check(name_en, name_ar, bool(condition), detail)

    def info(self) -> dict:
        return {
            "key": self.key,
            "order": self.order,
            "name_ar": self.name_ar,
            "name_en": self.name_en,
            "role_ar": self.role_ar,
            "role_en": self.role_en,
            "triggers": list(self.triggers),
            "outputs_ar": self.outputs_ar,
            "llm_capable": self.llm_capable,
            "challenge_phrase_ar": self.challenge_phrase_ar,
            "kpi_ar": self.kpi_ar,
        }


def fmt_num(value: float | int | None, decimals: int = 0) -> str:
    if value is None:
        return "—"
    if decimals:
        return f"{value:,.{decimals}f}"
    return f"{round(value):,}"
