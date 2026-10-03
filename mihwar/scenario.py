"""The end-to-end demo scenario: one client request travels through all 9 stages.

Runs in a background thread. Each orchestrator step is appended to its stage as soon as it
happens (with a short delay between steps), so the Agents page can animate the trace live.
"""
from __future__ import annotations

import secrets
import threading
import time
import traceback

from . import clock, repo
from .agents.intake import brief_headline
from .agents.base import fmt_num
from .db import loads
from .orchestrator import Denied

SCENARIO_TEXT = ("السلام عليكم، أبغى تصميم فيلا سكنية في الرياض حي الملقا، مساحة الأرض ٦٠٠ متر مربع، "
                 "دورين وملحق علوي. أحتاج تصميم معماري وإنشائي وكهروميكانيكي مع إصدار رخصة البناء، "
                 "وأتمنى ننتهي خلال ٤ أشهر.")

STAGES = [
    ("intake", "استقبال طلب العميل", "Client intake", "client"),
    ("proposal", "مسودة عرض السعر", "Proposal draft", "system"),
    ("approval", "اعتماد المدير وقبول العميل", "Manager approval & client acceptance", "manager"),
    ("planner", "الجدول الزمني للمشروع", "Project plan", "system"),
    ("team", "تشكيل الفريق وإسناد المهام", "Team assignment", "system"),
    ("documents", "رفع الملفات وترميزها", "Document upload & control", "engineer"),
    ("compliance", "مراجعة الجودة والتوقيع والنشر", "QA, licensed sign-off & publish gate", "engineer"),
    ("security", "منع وصول غير مصرّح", "Blocked unauthorised access", "client"),
    ("reporting", "تحديث العميل", "Client update", "system"),
]


class ScenarioRunner:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lock = threading.Lock()
        self.items: dict[str, dict] = {}
        self.latest_id: str | None = None

    def _new(self) -> dict:
        sid = "s_" + secrets.token_hex(4)
        sc = {
            "scenario_id": sid, "status": "running", "started_at": clock.now_iso(), "finished_at": None, "duration_ms": 0,
            "current_stage": 0,
            "stages": [{"n": i + 1, "key": k, "title_ar": a, "title_en": e, "actor_role": r, "status": "pending",
                        "highlight_ar": None, "steps": []} for i, (k, a, e, r) in enumerate(STAGES)],
            "result": {}, "error_ar": None, "_t0": time.perf_counter(),
        }
        with self.lock:
            self.items[sid] = sc
            self.latest_id = sid
        return sc

    def start(self, background: bool = True) -> dict:
        with self.lock:
            running = any(s["status"] == "running" for s in self.items.values())
        if running:
            current = self.items[self.latest_id]
            return current
        sc = self._new()
        if background:
            threading.Thread(target=self._run, args=(sc,), daemon=True).start()
        else:
            self._run(sc)
        return sc

    def get(self, sid: str) -> dict | None:
        with self.lock:
            sc = self.items.get(sid)
            return self.public(sc) if sc else None

    def latest(self) -> dict | None:
        return self.get(self.latest_id) if self.latest_id else None

    @staticmethod
    def public(sc: dict) -> dict:
        out = {k: v for k, v in sc.items() if not k.startswith("_")}
        if sc["status"] == "running":
            out["duration_ms"] = round((time.perf_counter() - sc["_t0"]) * 1000)
        out["stages"] = [dict(s, steps=list(s["steps"])) for s in sc["stages"]]
        return out

    # --------------------------------------------------------------------------
    def _run(self, sc: dict) -> None:
        ctx, db, orch = self.ctx, self.ctx.db, self.ctx.orchestrator
        delay = float(ctx.settings.scenario_delay)
        overrides: dict[str, int] = {}

        def stage(n: int) -> dict:
            return sc["stages"][n - 1]

        def begin(n: int) -> None:
            with self.lock:
                for s in sc["stages"][: n - 1]:
                    if s["status"] in ("pending", "running"):
                        s["status"] = "done"
                stage(n)["status"] = "running"
                sc["current_stage"] = n

        def on_step(step: dict) -> None:
            n = overrides.get(step["agent"], sc["current_stage"])
            with self.lock:
                if n != sc["current_stage"]:
                    for s in sc["stages"][: n - 1]:
                        if s["status"] in ("pending", "running"):
                            s["status"] = "done"
                    stage(n)["status"] = "running"
                    sc["current_stage"] = n
                stage(n)["steps"].append(step)

        def done(n: int, highlight: str) -> None:
            with self.lock:
                stage(n)["status"] = "done"
                stage(n)["highlight_ar"] = highlight

        try:
            client = repo.default_user(db, "client")
            manager = repo.default_user(db, "manager")

            # 1-2: intake, then the chained proposal draft
            begin(1)
            overrides = {"proposal": 2}
            run, res = orch.dispatch("client.request_submitted", {"text": SCENARIO_TEXT}, client, on_step=on_step, step_delay=delay)
            req = db.get("requests", res["request_id"])
            brief = loads(req["brief_json"], {})
            done(1, brief_headline(brief))
            sc["result"]["request_id"] = res["request_id"]
            if not res.get("proposal_id"):
                raise RuntimeError("intake did not complete the brief")
            prop = db.get("proposals", res["proposal_id"])
            done(2, f"{clock.ltr(prop['code'])} · الإجمالي {fmt_num(prop['total'])} ريال شامل الضريبة")
            sc["result"]["proposal_id"] = prop["id"]

            # 3-5: approval, acceptance, then the chained plan and team assignment
            begin(3)
            overrides = {"planner": 4, "team": 5}
            orch.dispatch("proposal.approved", {"proposal_id": prop["id"]}, manager, on_step=on_step, step_delay=delay)
            run, res = orch.dispatch("proposal.accepted", {"proposal_id": prop["id"]}, client, on_step=on_step, step_delay=delay)
            project = db.get("projects", res["project_id"])
            sc["result"]["project_id"] = project["id"]
            done(3, f"اعتمد {manager['name_ar']} العرض وقبله العميل · المشروع {clock.ltr(project['code'])}")
            n_tasks = db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project["id"],))
            done(4, f"المهام: {n_tasks} · من {clock.ar_date(project['start_date'])} إلى {clock.ar_date(project['end_date'])}")
            members = [db.get("users", m) for m in repo.member_ids(db, project["id"])]
            done(5, "الفريق: " + "، ".join(m["name_ar"] for m in members if m and m["role"] == "engineer"))

            # 6: an architect uploads the ground-floor plan; the structural engineer uploads draft calculations
            begin(6)
            overrides = {}
            from .seed import demo_content

            arch = db.one("SELECT u.* FROM users u JOIN project_members m ON m.user_id = u.id WHERE m.project_id = ? "
                          "AND u.discipline = 'architectural' AND u.role = 'engineer' ORDER BY u.is_licensed DESC, u.id LIMIT 1",
                          (project["id"],))
            struct = db.one("SELECT u.* FROM users u JOIN project_members m ON m.user_id = u.id WHERE m.project_id = ? "
                            "AND u.discipline = 'structural' ORDER BY u.id LIMIT 1", (project["id"],))
            fname = f"مسقط الدور الأرضي - {project['name_ar'].split(' — ')[0]}.pdf"
            run, up = orch.dispatch("file.uploaded", {"project_id": project["id"], "filename": fname,
                                                      "content": demo_content(fname, f"{project['code']} ground floor {sc['scenario_id']}")},
                                    arch, on_step=on_step, step_delay=delay)
            doc_id = up["document_id"]
            run, up2 = orch.dispatch("file.uploaded", {"project_id": project["id"], "filename": "حسابات إنشائية أولية.xlsx",
                                                       "content": f"draft structural calcs {sc['scenario_id']}".encode()},
                                     struct or arch, on_step=on_step, step_delay=delay)
            doc = db.get("documents", doc_id)
            done(6, f"{clock.ltr(doc['code'] + ' · ' + doc['revision'])} + ملف حسابات إنشائية (قيد العمل)")
            sc["result"]["document_id"] = doc_id

            # 7: QA on the drawing, licensed sign-off, share, publish (the QA gate passes)
            begin(7)
            run, qa = orch.dispatch("qa.requested", {"project_id": project["id"], "document_id": doc_id}, arch, on_step=on_step, step_delay=delay)
            signer = arch if arch["is_licensed"] else repo.default_user(db, "manager")
            orch.dispatch("qa.signed_off", {"qa_report_id": qa["qa_report_id"], "note": "مراجعة السيناريو التجريبي"}, signer,
                          on_step=on_step, step_delay=delay)
            orch.dispatch("file.status_changed", {"document_id": doc_id, "to_state": "SHARED"}, arch, on_step=on_step, step_delay=delay)
            run, pub = orch.dispatch("file.status_changed", {"document_id": doc_id, "to_state": "PUBLISHED"}, arch,
                                     on_step=on_step, step_delay=delay)
            doc = db.get("documents", doc_id)
            done(7, f"وقّع {signer['name_ar']} ثم نُشر {clock.ltr(doc['code'])} بالإصدار {doc['revision']} مع خطاب إرسال")
            sc["result"]["qa_report_id"] = qa["qa_report_id"]

            # 8: the client tries to download the unpublished calculations -> blocked + alert
            begin(8)
            alert_id = None
            try:
                orch.dispatch("file.download", {"document_id": up2["document_id"]}, client, on_step=on_step, step_delay=delay)
            except Denied as d:
                alert_id = d.alert_id
            done(8, "مُنع العميل من ملف قيد العمل وأُطلق تنبيه أمني" if alert_id else "مُنع الوصول وسُجّل في سجل التدقيق")
            sc["result"]["alert_id"] = alert_id

            # 9: the reporting agent sends the client an update
            begin(9)
            run, rep = orch.dispatch("report.weekly", {"project_id": project["id"], "send_to_client": True, "kind": "client_update"},
                                     manager, on_step=on_step, step_delay=delay)
            report = db.get("reports", rep["report_id"])
            secs = loads(report["sections_json"], {})
            done(9, f"أُرسل للعميل تحديث بالأعمال القادمة ({len(secs.get('next', []))}) والمعالم ({len(secs.get('milestones', []))}) "
                    f"ونسبة الإنجاز {report['progress_pct']}%")
            sc["result"]["report_id"] = rep["report_id"]
            sc["status"] = "completed"
        except Exception as exc:  # the scenario reports failure instead of crashing the server
            sc["status"] = "failed"
            sc["error_ar"] = f"تعذّر إكمال السيناريو: {type(exc).__name__}: {exc}"
            with self.lock:
                for s in sc["stages"]:
                    if s["status"] == "running":
                        s["status"] = "failed"
            traceback.print_exc()
        finally:
            sc["finished_at"] = clock.now_iso()
            sc["duration_ms"] = round((time.perf_counter() - sc["_t0"]) * 1000)
