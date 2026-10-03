"""UI smoke test: renders every page, for every role, in headless Microsoft Edge and checks the DOM.

Fails if a page shows the error card or misses its expected Arabic heading/content.

    .venv\\Scripts\\python scripts\\smoke_ui.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("MIHWAR_SMOKE_PORT", "8098"))
BASE = f"http://127.0.0.1:{PORT}"
EDGE = next((p for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if Path(p).exists()), None)

# (user id, route, text that must appear once the page has rendered)
CASES = [
    (1, "#/dashboard", "نشاط الوكلاء المباشر"),
    (1, "#/portal", "طلبات العملاء"),
    (1, "#/projects", "كل مشاريع المكتب"),
    (1, "#/projects/2", "الجدول الزمني"),
    (1, "#/team", "أحمال العمل الأسبوعية"),
    (1, "#/files", "سجل الوثائق"),
    (1, "#/compliance", "حزمة القواعد"),
    (1, "#/security", "مصفوفة الصلاحيات"),
    (1, "#/agents", "فريق الوكلاء"),
    (2, "#/dashboard", "نشاط الوكلاء المباشر"),
    (2, "#/projects", "المشاريع المسندة إليك"),
    (2, "#/agents", "اختبر الوكيل"),
    (4, "#/files", "سجل الوثائق"),
    (9, "#/portal", "مشاريعي"),
    (11, "#/portal", "وكيل استقبال العملاء"),
    (9, "#/security", "مشاريعي"),  # a client is redirected away from staff pages
]
ERROR_MARKERS = ["تعذّر تحميل الصفحة", "تعذّر الاتصال بالخادم"]


def main() -> int:
    if not EDGE:
        print("Microsoft Edge not found; UI smoke test skipped.")
        return 0
    data_dir = Path(tempfile.mkdtemp(prefix="mihwar-smoke-"))
    profile = Path(tempfile.mkdtemp(prefix="mihwar-smoke-edge-"))
    env = dict(os.environ, MIHWAR_DATA_DIR=str(data_dir), MIHWAR_PORT=str(PORT), MIHWAR_LLM="off", PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "mihwar"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = 0
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        for uid, route, expect in CASES:
            shutil.rmtree(profile, ignore_errors=True)
            out = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                  f"--user-data-dir={profile}", "--virtual-time-budget=10000", "--dump-dom",
                                  f"{BASE}/?user={uid}{route}"], capture_output=True, timeout=120)
            dom = out.stdout.decode("utf-8", errors="replace")
            bad = [m for m in ERROR_MARKERS if m in dom]
            ok = expect in dom and not bad
            failures += 0 if ok else 1
            print(f"{'PASS' if ok else 'FAIL'}  user={uid:<3} {route:<16} expects «{expect}»" + (f"  errors={bad}" if bad else ""))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
    print(f"\nUI smoke test: {len(CASES) - failures}/{len(CASES)} pages PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
