"""FastAPI application. See docs/api-contract.md for every endpoint and payload.

Mutations are events dispatched to the orchestrator; reads are authorised by the Security
agent and served from read models. Run with:  python -m mihwar
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import APP_NAME_AR, APP_NAME_EN, __version__, clock, labels, repo, views
from .agents.base import DomainError
from .agents.documents import NAMING_PATTERN
from .agents.security import LEGEND_AR, PERMISSIONS
from .config import WEB_DIR, Settings, load_config, load_settings
from .context import Context
from .db import loads
from .orchestrator import AgentFailure, Denied
from .selftest import run_self_tests
from .seed import ensure_seeded, reset


class ApiError(Exception):
    def __init__(self, status: int, code: str, message_ar: str, message_en: str, run_id: str | None = None):
        super().__init__(message_en)
        self.status, self.code, self.message_ar, self.message_en, self.run_id = status, code, message_ar, message_en, run_id


def _err(status: int, code: str, message_ar: str, message_en: str, run_id: str | None = None, extra: dict | None = None):
    detail = {"code": code, "message_ar": message_ar, "message_en": message_en, "run_id": run_id}
    if extra:
        detail.update(extra)
    return JSONResponse(status_code=status, content={"detail": detail})


# ------------------------------------------------------------------ request bodies
class TextBody(BaseModel):
    text: str


class QuestionBody(BaseModel):
    project_id: int
    text: str


class ParamsBody(BaseModel):
    coverage_ratio: float | None = None
    setback_front_m: float | None = None
    setback_side_m: float | None = None
    setback_rear_m: float | None = None
    height_m: float | None = None
    floors: int | None = None
    parking_spaces: int | None = None


class TaskBody(BaseModel):
    status: str | None = None
    assignee_id: int | None = None
    progress: int | None = None


class WeeklyBody(BaseModel):
    send_to_client: bool = False


class QaBody(BaseModel):
    document_id: int | None = None


class SignoffBody(BaseModel):
    note: str | None = None


class RebalanceBody(BaseModel):
    task_id: int
    to_engineer_id: int


class StateBody(BaseModel):
    to_state: str


class SimulateBody(BaseModel):
    kind: str


NAMING_FIELDS = [("project", "المشروع"), ("originator", "الجهة المُعِدّة"), ("volume", "المنطقة"), ("level", "المستوى"),
                 ("type", "نوع الوثيقة"), ("role", "التخصص"), ("number", "الرقم التسلسلي")]


def create_app(settings: Settings | None = None, ctx: Context | None = None) -> FastAPI:
    ctx = ctx or Context(settings or load_settings())
    ensure_seeded(ctx)
    db, orch = ctx.db, ctx.orchestrator
    app = FastAPI(title="Mihwar API", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.state.ctx = ctx

    # ------------------------------------------------------------------ errors
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _err(exc.status, exc.code, exc.message_ar, exc.message_en, exc.run_id)

    @app.exception_handler(Denied)
    async def _denied(_: Request, exc: Denied):
        return _err(403, "forbidden", exc.reason_ar, "Forbidden by the Security agent", exc.run_id,
                    {"alert_id": exc.alert_id})

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        extra = {k: v for k, v in exc.extra.items() if k != "run_id"}
        return _err(exc.status, exc.code, exc.message_ar, exc.message_en, exc.extra.get("run_id"), extra or None)

    @app.exception_handler(AgentFailure)
    async def _agent_failure(_: Request, exc: AgentFailure):
        return _err(500, "agent_error", f"تعذّر على الوكيل «{exc.agent}» إكمال العملية؛ سُجّل الخطأ في سجل التتبّع.",
                    f"Agent '{exc.agent}' failed: {exc}", exc.run_id)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return _err(422, "validation_error", "البيانات المرسلة غير مكتملة أو غير صحيحة", str(exc.errors())[:400])

    # ------------------------------------------------------------------ helpers
    def actor(request: Request) -> dict | None:
        raw = request.headers.get("X-Demo-User")
        if not raw:
            return None
        try:
            uid = int(raw)
        except ValueError:
            raise ApiError(401, "unauthenticated", "هوية غير صحيحة", "Invalid demo identity")
        user = db.get("users", uid)
        if not user:
            raise ApiError(401, "unauthenticated", "هوية غير معروفة", "Unknown demo identity")
        return user

    def require(request: Request, action: str | None = None, resource: str = "office") -> dict:
        user = actor(request)
        if user is None:
            raise ApiError(401, "unauthenticated", "اختر هوية تجريبية أولًا من شريط الأدوار", "Pick a demo identity first")
        if action:
            orch.authorize_read(user, action, resource)
        return user

    def mutate(event: str, payload: dict, user: dict) -> tuple[dict, dict]:
        run, result = orch.dispatch(event, payload, user)
        return views.run_view(ctx, run.run_id), result

    def not_found(what_ar: str):
        raise ApiError(404, "not_found", f"{what_ar} غير موجود", "Not found")

    def upload_result(res: dict, run: dict) -> dict:
        doc = db.get("documents", res["document_id"])
        c = res["classification"]
        prev = res.get("previous")
        code = doc["code"]
        parts = code.split("-")
        return {
            "document": views.document_view(db, doc),
            "classification": {"discipline": c["discipline"], "discipline_label_ar": labels.DISCIPLINE[c["discipline"]],
                               "doc_type": c["doc_type"], "doc_type_label_ar": labels.DOC_TYPE[c["doc_type"]],
                               "confidence": c["confidence"], "reasons_ar": c["reasons_ar"]},
            "naming": {"code": code, "fields": [{"key": k, "label_ar": l, "value": parts[i] if i < len(parts) else ""}
                                                for i, (k, l) in enumerate(NAMING_FIELDS)]},
            "revision": {"value": doc["revision"], "is_new_revision": bool(res.get("is_new_revision")),
                         "previous": prev},
            "duplicate_of": ({"id": doc["id"], "code": doc["code"], "revision": doc["revision"]} if res.get("duplicate_of") else None),
            "warnings_ar": res.get("warnings", []),
            "run": run,
        }

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "llm" if ctx.llm.enabled else "offline", "version": __version__}

    @app.get("/api/meta")
    def meta():
        office = load_config("office")
        return {
            "app": {"name_ar": APP_NAME_AR, "name_en": APP_NAME_EN, "version": __version__,
                    "tagline_ar": "المكتب الهندسي السحابي.. يديره فريق من وكلاء الذكاء الاصطناعي"},
            "mode": {"llm_enabled": ctx.llm.enabled, "label_ar": labels.MODE["llm" if ctx.llm.enabled else "offline"],
                     "model": ctx.settings.model if ctx.llm.enabled else None},
            "office": {"name_ar": office["name_ar"], "name_en": office["name_en"]},
            "notices": labels.NOTICES, "today": clock.today().isoformat(), "timezone": "Asia/Riyadh",
        }

    @app.get("/api/demo/users")
    def demo_users():
        return {"items": [views.demo_user(u) for u in db.all("SELECT * FROM users ORDER BY id")]}

    @app.get("/api/me")
    def me(request: Request):
        return views.demo_user(require(request))

    @app.post("/api/demo/reset")
    def demo_reset(request: Request):
        require(request, "demo.reset")
        reset(ctx)
        return {"ok": True}

    # ------------------------------------------------------------------ portal
    @app.get("/api/portal/office")
    def portal_office():
        office = load_config("office")
        price = load_config("price_list")
        services = []
        for code, name in labels.SERVICE.items():
            svc = price["services"][code]
            hint = {"per_m2": f"تبدأ من {svc['rate']} ريال للمتر المربع", "per_m2_land": f"تبدأ من {svc['rate']} ريال لكل م² من الأرض",
                    "per_month": f"تبدأ من {svc['rate']:,} ريال شهريًا", "lump_sum": f"تبدأ من {svc['rate']:,} ريال"}[svc["basis"]]
            services.append({"code": code, "name_ar": name, "name_en": code.replace("_", " ").title(),
                             "description_ar": office["service_descriptions_ar"][code], "price_hint_ar": hint + " (قيمة توضيحية)"})
        return {"office": {k: office[k] for k in ("name_ar", "name_en", "city_ar", "about_ar", "phone", "email", "hours_ar",
                                                  "fictional_notice_ar")},
                "services": services, "cities_served_ar": office["cities_served_ar"]}

    @app.get("/api/portal/requests")
    def portal_requests(request: Request):
        user = require(request, "portal.request.view")
        if user["role"] == "client":
            rows = db.all("SELECT * FROM requests WHERE client_id = ? ORDER BY id DESC", (user["client_id"],))
        else:
            rows = db.all("SELECT * FROM requests ORDER BY id DESC")
        return {"items": [views.request_view(db, r) for r in rows]}

    @app.get("/api/portal/requests/{rid}")
    def portal_request(rid: int, request: Request):
        row = db.get("requests", rid) or not_found("الطلب")
        require(request, "portal.request.view", f"request:{rid}")
        return views.request_view(db, row)

    def _request_response(run: dict, result: dict) -> dict:
        req = db.get("requests", result["request_id"])
        prop = db.get("proposals", result["proposal_id"]) if result.get("proposal_id") else None
        return {"request": views.request_view(db, req), "proposal": views.proposal_view(db, prop), "run": run}

    @app.post("/api/portal/requests")
    def portal_submit(body: TextBody, request: Request):
        user = require(request)
        run, result = mutate("client.request_submitted", {"text": body.text}, user)
        return _request_response(run, result)

    @app.post("/api/portal/requests/{rid}/messages")
    def portal_message(rid: int, body: TextBody, request: Request):
        user = require(request)
        run, result = mutate("client.message", {"request_id": rid, "text": body.text}, user)
        return _request_response(run, result)

    @app.get("/api/portal/projects")
    def portal_projects(request: Request):
        user = require(request)
        if user["role"] == "client":
            rows = db.all("SELECT * FROM projects WHERE client_id = ? ORDER BY id DESC", (user["client_id"],))
        elif user["role"] == "manager":
            rows = db.all("SELECT * FROM projects ORDER BY id DESC")
        else:
            orch.authorize_read(user, "portal.request.view")
            rows = []
        out = []
        for p in rows:
            docs = db.all("SELECT * FROM documents WHERE project_id = ? AND state = 'PUBLISHED' ORDER BY id DESC", (p["id"],))
            reps = db.all("SELECT * FROM reports WHERE project_id = ? AND sent_to_client = 1 ORDER BY id DESC", (p["id"],))
            prop = db.get("proposals", p["proposal_id"]) if p["proposal_id"] else None
            out.append({"project": views.project_item(db, p), "published_documents": [views.document_view(db, d) for d in docs],
                        "updates": [views.report_view(db, r) for r in reps], "proposal": views.proposal_view(db, prop)})
        return {"items": out}

    @app.post("/api/portal/questions")
    def portal_question(body: QuestionBody, request: Request):
        user = require(request)
        run, result = mutate("client.question", {"project_id": body.project_id, "text": body.text}, user)
        return {"answer": result["answer"], "run": run}

    # ------------------------------------------------------------------ proposals
    @app.get("/api/proposals")
    def proposals_list(request: Request, status: str | None = None):
        user = require(request, "proposal.view")
        if user["role"] == "client":
            rows = db.all("SELECT * FROM proposals WHERE client_id = ? AND status IN ('sent', 'accepted', 'rejected') ORDER BY id DESC",
                          (user["client_id"],))
        else:
            rows = db.all("SELECT * FROM proposals ORDER BY id DESC")
        if status:
            rows = [r for r in rows if r["status"] == status]
        return {"items": [views.proposal_view(db, r) for r in rows]}

    @app.get("/api/proposals/{pid}")
    def proposal_get(pid: int, request: Request):
        row = db.get("proposals", pid) or not_found("العرض")
        require(request, "proposal.view", f"proposal:{pid}")
        return views.proposal_view(db, row)

    @app.post("/api/proposals/{pid}/approve")
    def proposal_approve(pid: int, request: Request):
        user = require(request)
        run, _ = mutate("proposal.approved", {"proposal_id": pid}, user)
        return {"proposal": views.proposal_view(db, db.get("proposals", pid)), "run": run}

    @app.post("/api/proposals/{pid}/accept")
    def proposal_accept(pid: int, request: Request):
        user = require(request)
        run, result = mutate("proposal.accepted", {"proposal_id": pid}, user)
        project = db.get("projects", result["project_id"])
        return {"proposal": views.proposal_view(db, db.get("proposals", pid)), "project": views.project_item(db, project), "run": run}

    # ------------------------------------------------------------------ dashboard & activity
    @app.get("/api/dashboard")
    def dashboard(request: Request):
        user = require(request, "dashboard.view")
        return views.dashboard(ctx, user)

    @app.get("/api/activity")
    def activity(request: Request, after_id: int = 0, limit: int = 30):
        require(request, "dashboard.view")
        limit = max(1, min(limit, 100))
        rows = db.all("SELECT * FROM steps WHERE id > ? ORDER BY id DESC LIMIT ?", (after_id, limit))
        last = db.scalar("SELECT MAX(id) FROM steps") or 0
        return {"items": [views.trace_step(r, ctx) for r in rows], "last_id": last}

    @app.get("/api/runs/{run_id}")
    def run_get(run_id: str, request: Request):
        require(request, "dashboard.view")
        return views.run_view(ctx, run_id) or not_found("سجل العملية")

    # ------------------------------------------------------------------ projects
    @app.get("/api/projects")
    def projects(request: Request):
        user = require(request, "project.view")
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        return {"items": [views.project_item(db, p, users) for p in views.visible_projects(db, user)]}

    @app.get("/api/projects/{pid}")
    def project_get(pid: int, request: Request):
        row = db.get("projects", pid) or not_found("المشروع")
        user = require(request, "project.view", f"project:{pid}")
        return views.project_detail(ctx, row, user)

    @app.patch("/api/projects/{pid}/params")
    def project_params(pid: int, body: ParamsBody, request: Request):
        user = require(request)
        run, result = mutate("project.params_changed", {"project_id": pid, **body.model_dump(exclude_none=True)}, user)
        detail = views.project_detail(ctx, db.get("projects", pid), user)
        return {"project": detail, "qa_report": views.qa_report_view(db, db.get("qa_reports", result["qa_report_id"]), user), "run": run}

    @app.patch("/api/tasks/{tid}")
    def task_patch(tid: int, body: TaskBody, request: Request):
        user = require(request)
        run, _ = mutate("task.changed", {"task_id": tid, **body.model_dump(exclude_none=True)}, user)
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        return {"task": views.task_view(db.get("tasks", tid), users), "team": ctx.agents["team"].view(), "run": run}

    @app.post("/api/projects/{pid}/reports/weekly")
    def weekly(pid: int, body: WeeklyBody, request: Request):
        user = require(request)
        run, result = mutate("report.weekly", {"project_id": pid, "send_to_client": body.send_to_client}, user)
        return {"report": views.report_view(db, db.get("reports", result["report_id"])), "run": run}

    @app.post("/api/projects/{pid}/qa")
    def qa_run(pid: int, body: QaBody, request: Request):
        user = require(request)
        run, result = mutate("qa.requested", {"project_id": pid, "document_id": body.document_id}, user)
        return {"qa_report": views.qa_report_view(db, db.get("qa_reports", result["qa_report_id"]), user), "run": run}

    @app.post("/api/qa/{qid}/signoff")
    def qa_signoff(qid: int, body: SignoffBody, request: Request):
        user = require(request)
        run, _ = mutate("qa.signed_off", {"qa_report_id": qid, "note": body.note}, user)
        return {"qa_report": views.qa_report_view(db, db.get("qa_reports", qid), user), "run": run}

    # ------------------------------------------------------------------ team
    @app.get("/api/team")
    def team(request: Request):
        require(request, "team.view")
        return ctx.agents["team"].view()

    @app.post("/api/team/rebalance")
    def team_rebalance(body: RebalanceBody, request: Request):
        user = require(request)
        run, _ = mutate("team.rebalance", body.model_dump(), user)
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        return {"task": views.task_view(db.get("tasks", body.task_id), users), "team": ctx.agents["team"].view(), "run": run}

    # ------------------------------------------------------------------ files
    @app.get("/api/files")
    def files(request: Request, project_id: int | None = None, state: str | None = None, latest_only: bool = True):
        user = require(request, "file.view", f"project:{project_id}" if project_id else "office")
        sql, params = "SELECT d.* FROM documents d JOIN projects p ON p.id = d.project_id WHERE 1=1", []
        if user["role"] == "engineer":
            sql += " AND d.project_id IN (SELECT project_id FROM project_members WHERE user_id = ?)"
            params.append(user["id"])
        elif user["role"] == "client":
            sql += " AND p.client_id = ? AND d.state = 'PUBLISHED'"
            params.append(user["client_id"])
        if project_id:
            sql += " AND d.project_id = ?"
            params.append(project_id)
        all_rows = db.all(sql + " ORDER BY d.id DESC", params)
        counts = {s: 0 for s in labels.CDE_STATE}
        for r in all_rows:
            if r["superseded_by"] is None or not latest_only:
                counts[r["state"]] = counts.get(r["state"], 0) + 1
        rows = [r for r in all_rows if (not latest_only or r["superseded_by"] is None) and (not state or r["state"] == state)]
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        projects_map = {p["id"]: p for p in db.all("SELECT * FROM projects")}
        office = load_config("office")
        return {"items": [views.document_view(db, r, users, projects_map) for r in rows], "counts": counts,
                "naming": {"pattern": NAMING_PATTERN, "example": f"MST011-{office['code']}-ZZ-00-DR-A-0001",
                           "fields": [{"key": k, "label_ar": l} for k, l in NAMING_FIELDS],
                           "notice_ar": "منهجية ترميز مستوحاة من ISO 19650 ومبسّطة لأغراض النموذج الأولي."}}

    @app.post("/api/files")
    async def file_upload(request: Request, project_id: int = Form(...), file: UploadFile = File(...)):
        user = require(request)
        content = await file.read()
        run, result = await run_in_threadpool(mutate, "file.uploaded",
                                              {"project_id": project_id, "filename": file.filename or "file", "content": content}, user)
        return upload_result(result, run)

    @app.post("/api/files/{did}/state")
    def file_state(did: int, body: StateBody, request: Request):
        user = require(request)
        run, result = mutate("file.status_changed", {"document_id": did, "to_state": body.to_state}, user)
        tr = db.get("transmittals", result["transmittal_id"]) if result.get("transmittal_id") else None
        gate = result.get("gate") or {}
        return {"document": views.document_view(db, db.get("documents", did)), "gate": gate,
                "transmittal": views.transmittal_view(db, tr) if tr else None, "run": run}

    @app.get("/api/files/{did}/download")
    def file_download(did: int, request: Request):
        doc = db.get("documents", did) or not_found("الملف")
        user = require(request)
        orch.dispatch("file.download", {"document_id": did}, user)
        if not doc["stored_path"]:
            not_found("محتوى الملف")
        return FileResponse(doc["stored_path"], filename=doc["filename"])

    @app.get("/api/transmittals")
    def transmittals(request: Request, project_id: int | None = None):
        user = require(request, "file.view", f"project:{project_id}" if project_id else "office")
        rows = db.all("SELECT * FROM transmittals ORDER BY id DESC")
        visible = {p["id"] for p in views.visible_projects(db, user)}
        rows = [r for r in rows if r["project_id"] in visible and (not project_id or r["project_id"] == project_id)]
        return {"items": [views.transmittal_view(db, r) for r in rows]}

    # ------------------------------------------------------------------ compliance
    @app.get("/api/compliance")
    def compliance(request: Request):
        user = require(request, "compliance.view")
        return views.compliance_view(ctx, user)

    # ------------------------------------------------------------------ security
    @app.get("/api/security/audit")
    def audit(request: Request, limit: int = 100, decision: str | None = None):
        require(request, "security.view")
        limit = max(1, min(limit, 500))
        sql, params = "SELECT * FROM audit", []
        if decision in ("allow", "deny"):
            sql += " WHERE decision = ?"
            params.append(decision)
        total = db.scalar(sql.replace("SELECT *", "SELECT COUNT(*)"), params)
        rows = db.all(sql + " ORDER BY id DESC LIMIT ?", params + [limit])
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        return {"items": [views.audit_view(db, r, users) for r in rows], "total": total}

    @app.get("/api/security/alerts")
    def alerts(request: Request, status: str | None = None):
        require(request, "security.view")
        rows = db.all("SELECT * FROM alerts" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC",
                      (status,) if status else ())
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        return {"items": [views.alert_view(db, r, users) for r in rows]}

    @app.post("/api/security/alerts/{aid}/ack")
    def alert_ack(aid: int, request: Request):
        user = require(request)
        run, _ = mutate("security.alert_ack", {"alert_id": aid}, user)
        return {"alert": views.alert_view(db, db.get("alerts", aid)), "run": run}

    @app.get("/api/security/roles")
    def roles(request: Request):
        require(request, "agents.view")
        perms = [{"key": k, "label_ar": labels.ACTIONS.get(k, k), "manager": v[0], "engineer": v[1], "client": v[2]}
                 for k, v in PERMISSIONS.items()]
        return {"roles": [{"key": r, "label_ar": labels.ROLE[r]} for r in ("manager", "engineer", "client")],
                "permissions": perms, "legend_ar": LEGEND_AR}

    @app.post("/api/security/simulate")
    def simulate(body: SimulateBody, request: Request):
        user = require(request)
        run, result = mutate("security.simulate", {"kind": body.kind}, user)
        alert = db.get("alerts", result["alert_id"]) if result.get("alert_id") else None
        return {"attempt_ar": result["attempt_ar"], "decision": result["decision"],
                "alert": views.alert_view(db, alert) if alert else None, "run": run}

    # ------------------------------------------------------------------ agents, self-tests, scenario
    @app.get("/api/agents")
    def agents(request: Request):
        require(request, "agents.view")
        return {"items": [views.agent_card(ctx, a) for a in ctx.ordered_agents()]}

    @app.get("/api/agents/graph")
    def agents_graph(request: Request):
        require(request, "agents.view")
        return orch.graph()

    @app.post("/api/agents/self-test")
    def self_test_all(request: Request):
        require(request, "agents.view")
        return run_self_tests(ctx.settings, record_db=db)

    @app.post("/api/agents/{key}/self-test")
    def self_test_one(key: str, request: Request):
        require(request, "agents.view")
        if key not in ctx.agents:
            not_found("الوكيل")
        return run_self_tests(ctx.settings, [key], record_db=db)["results"][0]

    @app.post("/api/scenario/run", status_code=202)
    def scenario_run(request: Request):
        require(request, "scenario.run")
        sc = ctx.scenarios.start(background=True)
        return {"scenario_id": sc["scenario_id"], "status": sc["status"], "stages_total": len(sc["stages"])}

    @app.get("/api/scenario/latest")
    def scenario_latest(request: Request):
        require(request, "agents.view")
        return ctx.scenarios.latest() or not_found("السيناريو")

    @app.get("/api/scenario/{sid}")
    def scenario_get(sid: str, request: Request):
        require(request, "agents.view")
        return ctx.scenarios.get(sid) or not_found("السيناريو")

    # ------------------------------------------------------------------ web app
    if (WEB_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))

    return app
