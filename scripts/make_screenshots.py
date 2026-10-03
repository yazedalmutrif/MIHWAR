"""Regenerate the deck screenshots in docs/screenshots/.

Starts a temporary Mihwar server on fresh demo data, stages a client request, runs the full
scenario, then captures each screen with headless Microsoft Edge (ships with Windows 11).
Nothing is installed and the project's own data folder is not touched.

    .venv\\Scripts\\python scripts\\make_screenshots.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PORT = int(os.environ.get("MIHWAR_SHOT_PORT", "8097"))
BASE = f"http://127.0.0.1:{PORT}"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
SHOTS = [
    ("01-dashboard.png", "/?user=1#/dashboard"),
    ("02-agents.png", "/?user=1#/agents?stage=7"),
    ("03-client-portal.png", "/?user=10#/portal"),
    ("04-project-gantt.png", "/?user=1#/projects/2"),
    ("05-files.png", "/?user=1#/files"),
    ("06-security.png", "/?user=1#/security"),
    ("07-team.png", "/?user=1#/team"),
    ("08-compliance.png", "/?user=1#/compliance"),
]


def call(method: str, path: str, uid: int, body: dict | None = None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-Demo-User": str(uid), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    edge = next((p for p in EDGE_CANDIDATES if Path(p).exists()), None)
    if not edge:
        print("Microsoft Edge was not found; screenshots skipped.")
        return 1
    data_dir = Path(tempfile.mkdtemp(prefix="mihwar-shots-"))
    profile = Path(tempfile.mkdtemp(prefix="mihwar-edge-"))
    env = dict(os.environ, MIHWAR_DATA_DIR=str(data_dir), MIHWAR_PORT=str(PORT), MIHWAR_LLM="off", PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "mihwar"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        call("POST", "/api/portal/requests", 10, {"text": "السلام عليكم، نحتاج تصميم كامل لعمارة سكنية في جدة حي الشاطئ، "
                                                        "مساحة الأرض ١٢٠٠ م٢، ٥ أدوار مع مواقف في القبو، وإصدار رخصة البناء خلال ٦ أشهر"})
        sid = call("POST", "/api/scenario/run", 1)["scenario_id"]
        for _ in range(240):
            sc = call("GET", f"/api/scenario/{sid}", 1)
            if sc["status"] != "running":
                break
            time.sleep(0.5)
        print(f"scenario: {sc['status']} in {sc['duration_ms'] / 1000:.1f} s")
        OUT.mkdir(parents=True, exist_ok=True)
        for name, path in SHOTS:
            shutil.rmtree(profile, ignore_errors=True)
            subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--no-default-browser-check", f"--user-data-dir={profile}", "--window-size=1440,900",
                            "--force-device-scale-factor=2", "--virtual-time-budget=12000", f"--screenshot={OUT / name}",
                            BASE + path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            size = (OUT / name).stat().st_size if (OUT / name).exists() else 0
            print(f"{name}: {size:,} bytes")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
