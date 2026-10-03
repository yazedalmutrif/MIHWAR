"""Start the Mihwar server:  python -m mihwar"""
from __future__ import annotations

import sys

import uvicorn

from .config import load_settings


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    s = load_settings()
    mode = "Claude (LLM mode)" if s.llm_enabled else "offline (deterministic)"
    print(f"Mihwar is starting on http://{s.host}:{s.port}  ·  mode: {mode}")
    uvicorn.run("mihwar.app:create_app", factory=True, host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
