"""Optional Claude (LLM) mode.

Off by default. Switch it on with MIHWAR_LLM=on and an API key in the environment
(ANTHROPIC_API_KEY, never in code). Every call returns structured JSON validated by the
caller; on any error, refusal or timeout it raises LLMUnavailable and the agent falls
back to its deterministic offline logic, recording mode "offline-fallback" in the trace.

Model: claude-opus-5-5 at low effort (fast, short outputs). Server-side refusal
fallbacks are enabled (fallbacks="default").
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("mihwar.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(Exception):
    """Raised whenever Claude can't give a usable answer. Callers fall back to offline logic."""


class LLM:
    def __init__(self, settings):
        self.enabled = bool(settings.llm_enabled)
        self.model = settings.model
        self.timeout = settings.llm_timeout
        self._client = None
        self.calls = 0
        self.failures = 0

    def _get_client(self):
        if not self.enabled:
            raise LLMUnavailable("LLM mode is off")
        if self._client is None:
            try:
                import anthropic  # imported lazily: offline mode never needs it
            except ImportError as exc:  # pragma: no cover - dependency is in requirements
                raise LLMUnavailable("anthropic SDK is not installed") from exc
            try:
                self._client = anthropic.Anthropic(timeout=self.timeout, max_retries=1)
            except Exception as exc:  # missing credentials etc.
                raise LLMUnavailable(f"client init failed: {type(exc).__name__}") from exc
        return self._client

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 4096) -> dict[str, Any]:
        """One structured-output request. Returns the parsed JSON object."""
        client = self._get_client()
        self.calls += 1
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable("anthropic SDK is not installed") from exc

        request = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            try:
                response = client.beta.messages.create(
                    **request, betas=[FALLBACK_BETA], fallbacks="default"
                )
            except anthropic.BadRequestError as exc:
                # If an account or proxy rejects the fallback beta, retry once without it.
                if "fallback" not in str(exc).lower():
                    raise
                log.warning("fallbacks rejected, retrying without them")
                response = client.messages.create(**request)
        except anthropic.APIError as exc:  # connection, timeout, rate limit, 4xx/5xx
            self.failures += 1
            raise LLMUnavailable(f"{type(exc).__name__}") from exc
        except Exception as exc:  # anything unexpected must not break the platform
            self.failures += 1
            raise LLMUnavailable(f"{type(exc).__name__}") from exc

        stop = getattr(response, "stop_reason", None)
        if stop in ("refusal", "max_tokens"):
            self.failures += 1
            raise LLMUnavailable(f"stop_reason={stop}")
        text = next(
            (getattr(b, "text", None) for b in getattr(response, "content", []) if getattr(b, "type", None) == "text"),
            None,
        )
        if not text:
            self.failures += 1
            raise LLMUnavailable("no text block in response")
        try:
            data = json.loads(text)
        except ValueError as exc:
            self.failures += 1
            raise LLMUnavailable("response was not valid JSON") from exc
        if not isinstance(data, dict):
            self.failures += 1
            raise LLMUnavailable("response JSON is not an object")
        return data
