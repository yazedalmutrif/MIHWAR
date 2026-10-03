"""Command-line health check: runs every agent's self-test and prints a PASS/FAIL table.

    python -m mihwar.healthcheck          # summary table
    python -m mihwar.healthcheck -v       # every check with its detail

Exit code 0 when every agent passes, 1 otherwise.
"""
from __future__ import annotations

import sys

from .config import load_settings
from .selftest import run_self_tests


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    verbose = "-v" in argv or "--verbose" in argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = run_self_tests(load_settings())
    print("Mihwar agent health check (offline mode, isolated demo data)")
    print("=" * 78)
    print(f"{'#':<3}{'Agent':<28}{'Checks':>10}{'Time (ms)':>12}   Result")
    print("-" * 78)
    for i, r in enumerate(report["results"]):
        ok = sum(1 for c in r["checks"] if c["passed"])
        checks_s = f"{ok}/{len(r['checks'])}"
        result = "PASS" if r["passed"] else "FAIL"
        print(f"{i:<3}{r['name_en']:<28}{checks_s:>10}{r['duration_ms']:>12.1f}   {result}")
        if verbose or not r["passed"]:
            for c in r["checks"]:
                mark = "  ok " if c["passed"] else "  XX "
                print(f"     {mark}{c['name_en']}" + (f"  ->  {c['detail']}" if c["detail"] else ""))
    print("-" * 78)
    total = sum(len(r["checks"]) for r in report["results"])
    passed = sum(1 for r in report["results"] for c in r["checks"] if c["passed"])
    agents_ok = sum(1 for r in report["results"] if r["passed"])
    print(f"Agents: {agents_ok}/{len(report['results'])} PASS   Checks: {passed}/{total} PASS   "
          f"Total time: {report['duration_ms'] / 1000:.1f} s")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
