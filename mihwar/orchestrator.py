"""The Orchestrator (المنسّق).

Every website action is an event. The orchestrator routes each event through an explicit
graph of agents (Security first for anything a person does), passes state between them,
records one trace step per agent operation, chains follow-up events, and turns failures
into clean errors. API routes call `dispatch()`; they never call business logic directly.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Callable

from . import clock, labels, repo
from .agents.base import BaseAgent, Check, DomainError, StepResult
from .agents.documents import TRANSITIONS
from .db import dumps

ROUTES: list[dict] = [
    {"event": "client.request_submitted", "agents": ["security", "intake"], "emits": ["brief.ready"]},
    {"event": "client.message", "agents": ["security", "intake"], "emits": ["brief.ready"]},
    {"event": "brief.ready", "agents": ["proposal"], "emits": []},
    {"event": "proposal.approved", "agents": ["security", "proposal"], "emits": []},
    {"event": "proposal.accepted", "agents": ["security", "proposal", "planner"], "emits": ["plan.created"]},
    {"event": "plan.created", "agents": ["team"], "emits": []},
    {"event": "task.changed", "agents": ["security", "team"], "emits": []},
    {"event": "team.rebalance", "agents": ["security", "team"], "emits": []},
    {"event": "project.params_changed", "agents": ["security", "compliance"], "emits": []},
    {"event": "file.uploaded", "agents": ["security", "documents"], "emits": []},
    {"event": "file.status_changed", "agents": ["security", "compliance", "documents"], "emits": []},
    {"event": "file.download", "agents": ["security"], "emits": []},
    {"event": "qa.requested", "agents": ["security", "compliance"], "emits": []},
    {"event": "qa.signed_off", "agents": ["security", "compliance"], "emits": []},
    {"event": "report.weekly", "agents": ["security", "reporting"], "emits": []},
    {"event": "client.question", "agents": ["security", "reporting"], "emits": []},
    {"event": "security.alert_ack", "agents": ["security"], "emits": []},
    {"event": "security.simulate", "agents": ["security"], "emits": []},
]


class Denied(Exception):
    """Raised when the Security agent refuses an action."""

    def __init__(self, reason_ar: str, run_id: str | None = None, alert_id: int | None = None):
        super().__init__(reason_ar)
        self.reason_ar = reason_ar
        self.run_id = run_id
        self.alert_id = alert_id


class AgentFailure(Exception):
    """An unexpected exception inside an agent. The run is marked as an error; the platform keeps working."""

    def __init__(self, agent: str, run_id: str, message: str):
        super().__init__(message)
        self.agent = agent
        self.run_id = run_id


class Run:
    def __init__(self, orch: "Orchestrator", event: str, actor: dict | None, chain: bool = True,
                 on_step: Callable[[dict], None] | None = None, step_delay: float = 0.0):
        self.orch = orch
        self.db = orch.ctx.db
        self.run_id = "r_" + secrets.token_hex(4)
        self.event = event
        self.actor = actor
        self.chain = chain
        self.on_step = on_step
        self.step_delay = step_delay
        self.seq = 0
        self.emitted: list[str] = []
        self.t0 = time.perf_counter()
        self.started_at = clock.now_iso()
        self.db.insert("runs", {"run_id": self.run_id, "event": event, "actor_id": actor["id"] if actor else None,
                                "status": "running", "started_at": self.started_at, "duration_ms": 0, "emitted_json": []})

    # -------------------------------------------------------------------------
    def _record(self, agent: BaseAgent, event: str, status: str, mode: str, t_start: float, input_summary: str,
                output_summary: str, inp: dict | None, out: dict | None) -> dict:
        self.seq += 1
        duration = round((time.perf_counter() - t_start) * 1000, 1)
        ts = clock.now_iso()
        safe_out = {k: v for k, v in (out or {}).items() if not isinstance(v, (bytes, bytearray))}
        sid = self.db.insert("steps", {
            "run_id": self.run_id, "seq": self.seq, "agent": agent.key, "event": event, "status": status, "mode": mode,
            "duration_ms": duration, "input_summary": input_summary, "output_summary": output_summary, "ts": ts,
            "input_json": dumps(inp or {}), "output_json": dumps(safe_out),
        })
        step = {
            "id": sid, "run_id": self.run_id, "seq": self.seq, "agent": agent.key, "agent_name_ar": agent.name_ar,
            "agent_name_en": agent.name_en, "event": event, "event_label_ar": labels.EVENTS.get(event, event),
            "status": status, "mode": mode, "duration_ms": duration, "input_summary": input_summary,
            "output_summary": output_summary, "ts": ts, "input": inp or {}, "output": safe_out,
        }
        if self.on_step:
            try:
                self.on_step(step)
            except Exception:  # a UI callback must never break a run
                pass
        if self.step_delay:
            time.sleep(self.step_delay)
        return step

    def step(self, agent_key: str, op: str, event: str | None = None, **payload: Any) -> StepResult:
        agent = self.orch.ctx.agents[agent_key]
        ev = event or self.event
        t = time.perf_counter()
        try:
            res = agent.run(op, **payload)
        except DomainError as exc:
            self._record(agent, ev, "error", "offline", t, f"{agent.name_ar} · {op}", exc.message_ar, {"op": op},
                         {"error": exc.code})
            raise
        except Exception as exc:
            self._record(agent, ev, "error", "offline", t, f"{agent.name_ar} · {op}",
                         f"خطأ غير متوقع: {type(exc).__name__}", {"op": op}, {"error": str(exc)[:300]})
            raise AgentFailure(agent_key, self.run_id, str(exc)) from exc
        self._record(agent, ev, res.status, res.mode, t, res.input_summary, res.output_summary, res.input, res.output)
        return res

    def authorize(self, action: str, resource: str) -> StepResult:
        res = self.step("security", "authorize", actor=self.actor, action=action, resource=resource, run_id=self.run_id)
        if res.status == "denied":
            raise Denied(res.output["reason_ar"], self.run_id, res.output.get("alert_id"))
        return res

    def emit(self, event: str) -> None:
        self.emitted.append(event)

    def finish(self, status: str) -> None:
        self.db.update("runs", self.run_id, {
            "status": status, "duration_ms": round((time.perf_counter() - self.t0) * 1000, 1), "emitted_json": self.emitted,
        }, key="run_id")


class Orchestrator:
    def __init__(self, ctx):
        self.ctx = ctx
        self.handlers: dict[str, Callable] = {
            "client.request_submitted": self.h_request_submitted,
            "client.message": self.h_client_message,
            "brief.ready": self.h_brief_ready,
            "proposal.approved": self.h_proposal_approved,
            "proposal.accepted": self.h_proposal_accepted,
            "plan.created": self.h_plan_created,
            "task.changed": self.h_task_changed,
            "team.rebalance": self.h_team_rebalance,
            "project.params_changed": self.h_params_changed,
            "file.uploaded": self.h_file_uploaded,
            "file.status_changed": self.h_file_status_changed,
            "file.download": self.h_file_download,
            "qa.requested": self.h_qa_requested,
            "qa.signed_off": self.h_qa_signed_off,
            "report.weekly": self.h_report_weekly,
            "client.question": self.h_client_question,
            "security.alert_ack": self.h_alert_ack,
            "security.simulate": self.h_simulate,
        }

    @property
    def db(self):
        return self.ctx.db

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, event: str, payload: dict, actor: dict | None, *, chain: bool = True,
                 on_step: Callable[[dict], None] | None = None, step_delay: float = 0.0) -> tuple[Run, dict]:
        handler = self.handlers.get(event)
        if handler is None:
            raise DomainError("validation_error", "حدث غير معروف", f"Unknown event {event}", 422)
        run = Run(self, event, actor, chain=chain, on_step=on_step, step_delay=step_delay)
        try:
            result = handler(run, payload or {}, actor)
        except Denied as exc:
            run.finish("denied")
            exc.run_id = run.run_id
            raise
        except DomainError as exc:
            run.finish("error")
            exc.extra["run_id"] = run.run_id
            raise
        except AgentFailure:
            run.finish("error")
            raise
        except Exception as exc:
            run.finish("error")
            raise AgentFailure("orchestrator", run.run_id, str(exc)) from exc
        run.finish("ok")
        return run, result or {}

    def authorize_read(self, actor: dict | None, action: str, resource: str = "office") -> dict:
        """GET requests: authorised by the Security agent without a trace step (denials are audited)."""
        res = self.ctx.agents["security"].evaluate(actor, action, resource, run_id=None, audit=False)
        if res["decision"] == "deny":
            raise Denied(res["reason_ar"], None, res["alert_id"])
        return res

    def graph(self) -> dict:
        agents = self.ctx.agents
        nodes = [{"id": "orchestrator", "label_ar": "المنسّق", "label_en": "Orchestrator", "kind": "orchestrator"}]
        nodes += [{"id": a.key, "label_ar": a.name_ar, "label_en": a.name_en, "kind": "agent"}
                  for a in sorted(agents.values(), key=lambda a: a.order) if a.key != "orchestrator"]
        edges = []
        for r in ROUTES:
            for ag in r["agents"]:
                edges.append({"from": "orchestrator", "to": ag, "event": r["event"], "label_ar": labels.EVENTS[r["event"]]})
        routes = [{"event": r["event"], "event_label_ar": labels.EVENTS[r["event"]], "agents": r["agents"], "emits": r["emits"]}
                  for r in ROUTES]
        return {"nodes": nodes, "edges": edges, "routes": routes}

    # ------------------------------------------------------------------ handlers
    def _need(self, table: str, row_id, what_ar: str) -> dict:
        row = self.db.get(table, row_id) if row_id is not None else None
        if not row:
            raise DomainError("not_found", f"{what_ar} غير موجود", f"{table} {row_id} not found", 404)
        return row

    def _after_intake(self, run: Run, res: StepResult) -> dict:
        out = {"request_id": res.output["request_id"], "proposal_id": None}
        if res.output["complete"]:
            run.emit("brief.ready")
            if run.chain:
                out["proposal_id"] = run.step("proposal", "draft", event="brief.ready",
                                              request_id=res.output["request_id"]).output["proposal_id"]
        return out

    def h_request_submitted(self, run: Run, p: dict, actor: dict) -> dict:
        run.authorize("portal.request.create", "office")
        res = run.step("intake", "submit", client_id=actor["client_id"], text=p.get("text", ""),
                       client_name=repo.client_name(self.db, actor["client_id"]))
        return self._after_intake(run, res)

    def h_client_message(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("requests", p.get("request_id"), "الطلب")
        run.authorize("portal.request.message", f"request:{p['request_id']}")
        res = run.step("intake", "message", request_id=p["request_id"], text=p.get("text", ""))
        return self._after_intake(run, res)

    def h_brief_ready(self, run: Run, p: dict, actor) -> dict:
        res = run.step("proposal", "draft", request_id=p["request_id"])
        return {"proposal_id": res.output["proposal_id"]}

    def h_proposal_approved(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("proposals", p.get("proposal_id"), "العرض")
        run.authorize("proposal.approve", f"proposal:{p['proposal_id']}")
        run.step("proposal", "approve", proposal_id=p["proposal_id"], manager=actor)
        return {"proposal_id": p["proposal_id"]}

    def h_proposal_accepted(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("proposals", p.get("proposal_id"), "العرض")
        run.authorize("proposal.accept", f"proposal:{p['proposal_id']}")
        res = run.step("proposal", "accept", proposal_id=p["proposal_id"], client=actor)
        project_id = res.output["project_id"]
        run.step("planner", "plan", project_id=project_id)
        run.emit("plan.created")
        if run.chain:
            run.step("team", "assign", event="plan.created", project_id=project_id)
        return {"proposal_id": p["proposal_id"], "project_id": project_id}

    def h_plan_created(self, run: Run, p: dict, actor) -> dict:
        run.step("team", "assign", project_id=p["project_id"])
        return {"project_id": p["project_id"]}

    def h_task_changed(self, run: Run, p: dict, actor: dict) -> dict:
        task = self._need("tasks", p.get("task_id"), "المهمة")
        run.authorize("task.update", f"task:{task['id']}")
        changes: dict = {}
        if p.get("assignee_id") is not None and p["assignee_id"] != task["assignee_id"]:
            if actor["role"] != "manager":
                raise DomainError("forbidden", "إعادة الإسناد من صلاحية مدير المكتب", "Only the manager can reassign", 403)
            changes["assignee_id"] = int(p["assignee_id"])
            repo.add_member(self.db, task["project_id"], changes["assignee_id"])
        status, progress = p.get("status"), p.get("progress")
        if status is not None:
            if status not in labels.TASK_STATUS:
                raise DomainError("validation_error", "حالة مهمة غير صحيحة", "Invalid task status", 422)
            changes["status"] = status
            if status == "done":
                changes["progress"] = 100
        if progress is not None:
            try:
                progress = int(progress)
            except (TypeError, ValueError):
                raise DomainError("validation_error", "نسبة الإنجاز يجب أن تكون رقمًا", "Progress must be a number", 422)
            if not 0 <= progress <= 100:
                raise DomainError("validation_error", "نسبة الإنجاز بين 0 و100", "Progress must be 0-100", 422)
            changes["progress"] = progress
            if progress == 100:
                changes["status"] = "done"
            elif progress > 0 and (changes.get("status") or task["status"]) == "todo":
                changes["status"] = "in_progress"
        if changes:
            self.db.update("tasks", task["id"], changes)
        run.step("team", "recompute", task_id=task["id"])
        return {"task_id": task["id"]}

    def h_team_rebalance(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("tasks", p.get("task_id"), "المهمة")
        run.authorize("team.rebalance", "office")
        run.step("team", "rebalance", task_id=int(p["task_id"]), to_engineer_id=int(p["to_engineer_id"]))
        return {"task_id": int(p["task_id"])}

    PARAM_KEYS = ("coverage_ratio", "setback_front_m", "setback_side_m", "setback_rear_m", "height_m", "floors", "parking_spaces")

    def h_params_changed(self, run: Run, p: dict, actor: dict) -> dict:
        project = self._need("projects", p.get("project_id"), "المشروع")
        run.authorize("project.edit", f"project:{project['id']}")
        params = repo.project_params(project)
        for k in self.PARAM_KEYS:
            if p.get(k) is None:
                continue
            try:
                v = float(p[k])
            except (TypeError, ValueError):
                raise DomainError("validation_error", f"قيمة غير صحيحة: {k}", f"Invalid value for {k}", 422)
            if v < 0 or (k == "coverage_ratio" and v > 1):
                raise DomainError("validation_error", f"قيمة خارج النطاق: {k}", f"Out-of-range value for {k}", 422)
            params[k] = int(v) if k in ("floors", "parking_spaces") else v
        self.db.update("projects", project["id"], {"params_json": params, "floors": params.get("floors", project["floors"])})
        res = run.step("compliance", "check", project_id=project["id"])
        return {"project_id": project["id"], "qa_report_id": res.output["qa_report_id"]}

    def h_file_uploaded(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("projects", p.get("project_id"), "المشروع")
        run.authorize("file.upload", f"project:{p['project_id']}")
        res = run.step("documents", "register", project_id=int(p["project_id"]), filename=p.get("filename", "file"),
                       content=p.get("content", b""), uploader=actor)
        return res.output

    def h_file_status_changed(self, run: Run, p: dict, actor: dict) -> dict:
        doc = self._need("documents", p.get("document_id"), "الملف")
        to_state = p.get("to_state")
        run.authorize("file.state", f"document:{doc['id']}")
        if (doc["state"], to_state) not in TRANSITIONS:
            raise DomainError("invalid_state",
                              f"لا يمكن نقل الملف من «{labels.CDE_STATE.get(doc['state'], doc['state'])}» إلى «{labels.CDE_STATE.get(to_state, to_state)}»",
                              f"Illegal transition {doc['state']} -> {to_state}", 409)
        gate = run.step("compliance", "gate", document_id=doc["id"], to_state=to_state)
        if gate.status == "denied":
            raise DomainError("qa_signoff_required", "لا يُنشر الملف قبل توقيع مهندس مرخّص على مراجعة الجودة",
                              "Publishing requires a QA report signed off by a licensed engineer", 409, {"gate": gate.output})
        res = run.step("documents", "transition", document_id=doc["id"], to_state=to_state, actor=actor)
        return {"document_id": doc["id"], "gate": gate.output, "transmittal_id": res.output["transmittal_id"]}

    def h_file_download(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("documents", p.get("document_id"), "الملف")
        run.authorize("file.download", f"document:{p['document_id']}")
        return {"document_id": p["document_id"]}

    def h_qa_requested(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("projects", p.get("project_id"), "المشروع")
        run.authorize("qa.run", f"project:{p['project_id']}")
        res = run.step("compliance", "check", project_id=int(p["project_id"]), document_id=p.get("document_id"))
        return {"qa_report_id": res.output["qa_report_id"]}

    def h_qa_signed_off(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("qa_reports", p.get("qa_report_id"), "تقرير المراجعة")
        run.authorize("qa.signoff", f"qa:{p['qa_report_id']}")
        run.step("compliance", "signoff", report_id=int(p["qa_report_id"]), engineer=actor, note=p.get("note"))
        return {"qa_report_id": int(p["qa_report_id"])}

    def h_report_weekly(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("projects", p.get("project_id"), "المشروع")
        run.authorize("report.create", f"project:{p['project_id']}")
        res = run.step("reporting", "weekly", project_id=int(p["project_id"]), send_to_client=bool(p.get("send_to_client")),
                       kind=p.get("kind", "weekly"))
        return {"report_id": res.output["report_id"]}

    def h_client_question(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("projects", p.get("project_id"), "المشروع")
        run.authorize("client.question", f"project:{p['project_id']}")
        res = run.step("reporting", "answer", project_id=int(p["project_id"]), text=p.get("text", ""), actor=actor)
        return {"answer": res.output}

    def h_alert_ack(self, run: Run, p: dict, actor: dict) -> dict:
        self._need("alerts", p.get("alert_id"), "التنبيه")
        run.authorize("security.manage", f"alert:{p['alert_id']}")
        run.step("security", "ack", alert_id=int(p["alert_id"]), actor=actor, run_id=run.run_id)
        return {"alert_id": int(p["alert_id"])}

    def h_simulate(self, run: Run, p: dict, actor: dict) -> dict:
        run.authorize("security.manage", "office")
        res = run.step("security", "simulate", kind=p.get("kind", ""), actor=actor, run_id=run.run_id)
        return res.output


class OrchestratorAgent(BaseAgent):
    """Card and self-test for the orchestrator itself (agent #0)."""

    key = "orchestrator"
    order = 0
    name_ar = "المنسّق"
    name_en = "Orchestrator"
    role_ar = "يستقبل كل حدث في المنصة ويوجّهه إلى الوكلاء المناسبين بالترتيب، ويمرّر البيانات بينهم ويسجّل كل خطوة ويعالج الأعطال."
    role_en = "Routes every platform event through the right agents in order, passes state, records every step and handles failures."
    triggers = ("*",)
    outputs_ar = "سجل تتبّع كامل لكل عملية (Trace) + النتيجة المجمّعة"
    challenge_phrase_ar = "نماذج رقمية ممكنة بالذكاء الاصطناعي في بيئة موحدة"
    kpi_ar = "نسبة العمليات المنفذة آليًا من البداية للنهاية"

    def self_test(self) -> list[Check]:
        orch = self.ctx.orchestrator
        checks = []
        missing = [r["event"] for r in ROUTES if r["event"] not in orch.handlers]
        unknown = [a for r in ROUTES for a in r["agents"] if a not in self.ctx.agents]
        checks.append(self.check("Every route has a handler and known agents", "كل مسار له معالج ووكلاء معروفون",
                                 not missing and not unknown, f"{len(ROUTES)} مسارًا"))
        checks.append(self.check("Every event has an Arabic label", "لكل حدث وصف عربي", all(r["event"] in labels.EVENTS for r in ROUTES), ""))
        client = repo.default_user(self.db, "client")
        run, result = orch.dispatch("client.request_submitted", {
            "text": "أبغى تصميم معماري وإنشائي لفيلا في جدة مساحة الأرض 400 م2 دورين"}, client)
        agents_run = [s["agent"] for s in self.db.all("SELECT agent FROM steps WHERE run_id = ? ORDER BY seq", (run.run_id,))]
        checks.append(self.check("Chained event: request → intake → proposal draft", "تسلسل الأحداث: طلب ← استقبال ← عرض",
                                 agents_run == ["security", "intake", "proposal"] and "brief.ready" in run.emitted and result.get("proposal_id"),
                                 " → ".join(agents_run)))
        engineer = self.db.one("SELECT * FROM users WHERE role = 'engineer' LIMIT 1")
        denied = False
        try:
            orch.dispatch("proposal.approved", {"proposal_id": result["proposal_id"]}, engineer)
        except Denied:
            denied = True
        last = self.db.one("SELECT status FROM runs ORDER BY rowid DESC LIMIT 1")
        checks.append(self.check("Security denial stops the run", "الرفض الأمني يوقف العملية", denied and last["status"] == "denied", last["status"]))
        errored = False
        try:
            orch.dispatch("qa.requested", {"project_id": 999999}, repo.default_user(self.db, "manager"))
        except DomainError:
            errored = True
        checks.append(self.check("Bad input fails cleanly without breaking the platform", "الإدخال الخاطئ يفشل بأمان", errored, "not_found"))
        return checks
