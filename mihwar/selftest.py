"""Agent self-tests.

Each agent's self_test() runs against a fresh, isolated copy of the demo data (a temporary
database), in offline mode, so results are deterministic and the live data is never touched.
Results are recorded in the live database so the Agents page can show them.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import traceback
from dataclasses import replace
from pathlib import Path

from . import clock


def _ephemeral_context(settings):
    from .context import Context
    from .db import Database
    from .seed import seed

    tmp = Path(tempfile.mkdtemp(prefix="mihwar-selftest-"))
    s = replace(settings, data_dir=tmp, llm_enabled=False, scenario_delay=0.0, seed_activity=False)
    ctx = Context(s, Database(":memory:"))
    seed(ctx, activity=False)
    return ctx, tmp


def run_agent_self_test(settings, key: str) -> dict:
    ctx, tmp = _ephemeral_context(settings)
    agent = ctx.agents[key]
    t0 = time.perf_counter()
    try:
        checks = [c.as_dict() for c in agent.self_test()]
    except Exception as exc:  # a crashing self-test is a failed self-test, not a crashed server
        checks = [{"name_en": "Self-test ran to completion", "name_ar": "اكتمال الاختبار الذاتي", "passed": False,
                   "detail": f"{type(exc).__name__}: {exc}"}]
        traceback.print_exc()
    finally:
        ctx.db.close()
        shutil.rmtree(tmp, ignore_errors=True)
    passed = all(c["passed"] for c in checks) and bool(checks)
    return {"key": key, "name_ar": agent.name_ar, "name_en": agent.name_en, "passed": passed,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1), "ran_at": clock.now_iso(), "checks": checks}


def run_self_tests(settings, keys: list[str] | None = None, record_db=None) -> dict:
    from .context import Context

    order = ["orchestrator", "intake", "proposal", "planner", "team", "documents", "compliance", "security", "reporting"]
    keys = keys or order
    t0 = time.perf_counter()
    results = [run_agent_self_test(settings, k) for k in keys]
    if record_db is not None:
        for r in results:
            record_db.execute(
                "INSERT INTO selftests (agent, passed, at, checks_passed, checks_total) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(agent) DO UPDATE SET passed=excluded.passed, at=excluded.at, "
                "checks_passed=excluded.checks_passed, checks_total=excluded.checks_total",
                (r["key"], int(r["passed"]), r["ran_at"], sum(1 for c in r["checks"] if c["passed"]), len(r["checks"])))
    return {"passed": all(r["passed"] for r in results), "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "results": results}
