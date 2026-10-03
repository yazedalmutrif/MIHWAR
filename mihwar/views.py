"""Read models: database rows -> the JSON shapes in docs/api-contract.md."""
from __future__ import annotations

from . import clock, labels, repo
from .agents.planner import phases_of
from .agents.reporting import health_of, progress_of, project_tasks
from .config import load_config
from .db import loads


# ---------------------------------------------------------------------------- users
def demo_user(u: dict) -> dict:
    return {
        **repo.user_ref(u),
        "title_ar": u["title_ar"],
        "discipline": u["discipline"],
        "discipline_label_ar": labels.label(labels.DISCIPLINE, u["discipline"]),
        "initials": u["initials"],
        "is_licensed": bool(u["is_licensed"]),
        "license_no": u["license_no"],
        "client_id": u["client_id"],
        "default_for_role": bool(u["default_for_role"]),
    }


def _users(db) -> dict[int, dict]:
    return {u["id"]: u for u in db.all("SELECT * FROM users")}


def _mini(u: dict | None) -> dict | None:
    return {"id": u["id"], "name_ar": u["name_ar"]} if u else None


# ---------------------------------------------------------------------------- trace
def trace_step(row: dict, ctx, full: bool = False) -> dict:
    agent = ctx.agents.get(row["agent"])
    return {
        "id": row["id"], "run_id": row["run_id"], "seq": row["seq"], "agent": row["agent"],
        "agent_name_ar": agent.name_ar if agent else row["agent"], "agent_name_en": agent.name_en if agent else row["agent"],
        "event": row["event"], "event_label_ar": labels.EVENTS.get(row["event"], row["event"]),
        "status": row["status"], "mode": row["mode"], "duration_ms": row["duration_ms"],
        "input_summary": row["input_summary"], "output_summary": row["output_summary"], "ts": row["ts"],
        "input": loads(row["input_json"], {}) if full else None,
        "output": loads(row["output_json"], {}) if full else None,
    }


def run_view(ctx, run_id: str, full: bool = True) -> dict | None:
    db = ctx.db
    r = db.get("runs", run_id, key="run_id")
    if not r:
        return None
    steps = db.all("SELECT * FROM steps WHERE run_id = ? ORDER BY seq", (run_id,))
    return {
        "run_id": r["run_id"], "event": r["event"], "event_label_ar": labels.EVENTS.get(r["event"], r["event"]),
        "actor": repo.user_ref(repo.get_user(db, r["actor_id"])), "status": r["status"],
        "status_label_ar": labels.RUN_STATUS.get(r["status"], r["status"]), "started_at": r["started_at"],
        "duration_ms": r["duration_ms"], "steps": [trace_step(s, ctx, full) for s in steps],
        "emitted": loads(r["emitted_json"], []),
    }


# ---------------------------------------------------------------------------- portal
def request_view(db, row: dict) -> dict:
    brief = loads(row["brief_json"], {}) or {}
    missing = loads(row["missing_json"], []) or []
    from .agents.intake import FIELD_LABELS

    msgs = db.all("SELECT * FROM messages WHERE request_id = ? ORDER BY id", (row["id"],))
    return {
        "id": row["id"], "client": {"id": row["client_id"], "name_ar": repo.client_name(db, row["client_id"])},
        "status": row["status"], "status_label_ar": labels.REQUEST_STATUS.get(row["status"], row["status"]),
        "created_at": row["created_at"], "original_text": row["original_text"], "brief": brief,
        "missing_fields": missing, "missing_fields_labels_ar": [FIELD_LABELS.get(f, f) for f in missing],
        "follow_up_questions_ar": loads(row["questions_json"], []) or [], "complete": bool(row["complete"]),
        "messages": [{"id": m["id"], "sender": m["sender"], "agent": m["agent"], "text": m["text"], "ts": m["ts"]} for m in msgs],
        "proposal_id": row["proposal_id"],
    }


def proposal_view(db, row: dict | None) -> dict | None:
    if not row:
        return None
    users = _users(db)
    hist = []
    for h in loads(row["history_json"], []) or []:
        hist.append({"status": h["status"], "status_label_ar": labels.PROPOSAL_STATUS.get(h["status"], h["status"]),
                     "at": h["at"], "by": repo.user_ref(users.get(h.get("by")))})
    return {
        "id": row["id"], "code": row["code"], "request_id": row["request_id"],
        "client": {"id": row["client_id"], "name_ar": repo.client_name(db, row["client_id"])}, "project_id": row["project_id"],
        "status": row["status"], "status_label_ar": labels.PROPOSAL_STATUS.get(row["status"], row["status"]),
        "title_ar": row["title_ar"], "brief": loads(row["brief_json"], {}), "bua_m2": row["bua_m2"],
        "lines": loads(row["lines_json"], []), "subtotal": row["subtotal"], "vat_rate": row["vat_rate"], "vat": row["vat"],
        "total": row["total"], "currency": "SAR", "milestones": loads(row["milestones_json"], []),
        "validity_days": row["validity_days"], "valid_until": row["valid_until"],
        "exclusions_ar": loads(row["exclusions_json"], []), "assumptions_ar": loads(row["assumptions_json"], []),
        "notice_ar": labels.NOTICES["placeholder_ar"], "history": hist, "created_at": row["created_at"],
        "approved_by": repo.user_ref(users.get(row["approved_by"])), "approved_at": row["approved_at"],
        "sent_at": row["sent_at"], "accepted_at": row["accepted_at"],
    }


# ---------------------------------------------------------------------------- projects
def project_item(db, row: dict, users: dict | None = None) -> dict:
    users = users or _users(db)
    tasks = project_tasks(db, row["id"])
    health = health_of(db, row, tasks)
    team = []
    for uid in sorted(repo.member_ids(db, row["id"])):
        u = users.get(uid)
        if u and u["role"] in ("engineer", "manager"):
            team.append({"id": u["id"], "name_ar": u["name_ar"], "discipline": u["discipline"],
                         "discipline_label_ar": labels.label(labels.DISCIPLINE, u["discipline"])})
    latest = db.one("SELECT * FROM qa_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (row["id"],))
    open_issues = len(loads(latest["issues_json"], [])) if latest and latest["status"] != "signed_off" else 0
    ms = next((t for t in tasks if t["is_milestone"] and t["status"] != "done"), None)
    return {
        "id": row["id"], "code": row["code"], "name_ar": row["name_ar"], "name_en": row["name_en"],
        "client": {"id": row["client_id"], "name_ar": repo.client_name(db, row["client_id"])},
        "type": row["type"], "type_label_ar": labels.PROJECT_TYPE.get(row["type"], row["type"]),
        "city": row["city"], "district": row["district"],
        "status": row["status"], "status_label_ar": labels.PROJECT_STATUS.get(row["status"], row["status"]),
        "health": health, "health_label_ar": labels.PROJECT_HEALTH[health], "progress": progress_of(tasks),
        "start_date": row["start_date"], "end_date": row["end_date"], "team": team, "open_issues": open_issues,
        "next_milestone": {"name_ar": ms["name_ar"], "date": ms["end"]} if ms else None,
    }


def task_view(row: dict, users: dict) -> dict:
    return {
        "id": row["id"], "project_id": row["project_id"], "phase": row["phase"], "phase_name_ar": row["phase_name_ar"],
        "name_ar": row["name_ar"], "discipline": row["discipline"],
        "discipline_label_ar": labels.label(labels.DISCIPLINE, row["discipline"]), "start": row["start"], "end": row["end"],
        "duration_days": row["duration_days"], "hours": row["hours"], "depends_on": loads(row["depends_json"], []),
        "assignee": _mini(users.get(row["assignee_id"])), "status": row["status"],
        "status_label_ar": labels.TASK_STATUS.get(row["status"], row["status"]), "progress": row["progress"],
        "is_milestone": bool(row["is_milestone"]),
    }


def document_view(db, row: dict, users: dict | None = None, projects: dict | None = None) -> dict:
    users = users or _users(db)
    proj = (projects or {}).get(row["project_id"]) or db.get("projects", row["project_id"]) or {}
    return {
        "id": row["id"], "project_id": row["project_id"], "project_code": proj.get("code"), "code": row["code"],
        "title": row["title"], "filename": row["filename"], "discipline": row["discipline"],
        "discipline_code": labels.DISCIPLINE_CODE.get(row["discipline"], "Z"),
        "discipline_label_ar": labels.label(labels.DISCIPLINE, row["discipline"]), "doc_type": row["doc_type"],
        "doc_type_label_ar": labels.DOC_TYPE.get(row["doc_type"], row["doc_type"]), "revision": row["revision"],
        "state": row["state"], "state_label_ar": labels.CDE_STATE.get(row["state"], row["state"]),
        "size_bytes": row["size_bytes"], "uploaded_by": _mini(users.get(row["uploaded_by"])), "uploaded_at": row["uploaded_at"],
        "qa_status": row["qa_status"], "qa_status_label_ar": labels.QA_STATUS.get(row["qa_status"], row["qa_status"]),
        "is_latest": row["superseded_by"] is None, "superseded_by": row["superseded_by"],
        "sha256_short": (row["sha256"] or "")[:8],
    }


def transmittal_view(db, row: dict, users: dict | None = None) -> dict:
    users = users or _users(db)
    proj = db.get("projects", row["project_id"]) or {}
    return {
        "id": row["id"], "code": row["code"], "project_id": row["project_id"], "project_code": proj.get("code"),
        "purpose_ar": row["purpose_ar"], "documents": loads(row["docs_json"], []),
        "issued_to": _mini(users.get(row["issued_to"])), "created_by": _mini(users.get(row["created_by"])),
        "created_at": row["created_at"],
    }


def qa_report_view(db, row: dict, viewer: dict | None) -> dict:
    users = _users(db)
    proj = db.get("projects", row["project_id"]) or {}
    doc = db.get("documents", row["document_id"]) if row["document_id"] else None
    issues = loads(row["issues_json"], []) or []
    high = any(i["severity"] == "high" for i in issues)
    signer = users.get(row["signed_off_by"])
    can = bool(viewer and viewer.get("is_licensed") and viewer["role"] in ("engineer", "manager")
               and row["status"] != "signed_off" and not high)
    if row["status"] == "signed_off":
        blocking = None
    elif high:
        blocking = "توجد ملاحظات عالية الخطورة مفتوحة؛ عالجها وأعد الفحص قبل التوقيع"
    elif viewer and not viewer.get("is_licensed"):
        blocking = "التوقيع مقصور على المهندسين المرخّصين"
    else:
        blocking = None
    pack = load_config("rule_pack")
    return {
        "id": row["id"], "project_id": row["project_id"], "project_code": proj.get("code"), "document_id": row["document_id"],
        "document_code": doc["code"] if doc else None, "phase": row["phase"],
        "phase_name_ar": pack["phase_names"].get(row["phase"], row["phase"]), "status": row["status"],
        "status_label_ar": labels.QA_STATUS.get(row["status"], row["status"]), "summary_ar": row["summary_ar"], "issues": issues,
        "checks_total": row["checks_total"], "checks_passed": row["checks_passed"],
        "deliverables": loads(row["deliverables_json"], []), "created_at": row["created_at"],
        "signed_off_by": ({**repo.user_ref(signer), "license_no": signer["license_no"]} if signer else None),
        "signed_off_at": row["signed_off_at"], "signoff_note": row["signoff_note"], "can_sign_off": can,
        "blocking_reason_ar": blocking, "notice_ar": pack["notice_ar"],
    }


def report_view(db, row: dict) -> dict:
    proj = db.get("projects", row["project_id"]) or {}
    return {
        "id": row["id"], "project_id": row["project_id"], "project_code": proj.get("code"), "kind": row["kind"],
        "title_ar": row["title_ar"], "period_start": row["period_start"], "period_end": row["period_end"],
        "progress_pct": row["progress_pct"], "body_ar": row["body_ar"], "sections": loads(row["sections_json"], {}),
        "sent_to_client": bool(row["sent_to_client"]), "sent_at": row["sent_at"], "created_at": row["created_at"],
        "mode": row.get("mode"),
    }


def project_detail(ctx, row: dict, viewer: dict) -> dict:
    db = ctx.db
    users = _users(db)
    item = project_item(db, row, users)
    params = repo.project_params(row)
    tasks = project_tasks(db, row["id"])
    tv = [task_view(t, users) for t in tasks]
    is_client = viewer["role"] == "client"
    doc_rows = db.all("SELECT * FROM documents WHERE project_id = ? ORDER BY superseded_by IS NOT NULL, id DESC", (row["id"],))
    if is_client:
        doc_rows = [d for d in doc_rows if d["state"] == "PUBLISHED"]
    qa_rows = [] if is_client else db.all("SELECT * FROM qa_reports WHERE project_id = ? ORDER BY id DESC", (row["id"],))
    rep_rows = db.all("SELECT * FROM reports WHERE project_id = ? ORDER BY id DESC", (row["id"],))
    if is_client:
        rep_rows = [r for r in rep_rows if r["sent_to_client"]]
    prop = db.get("proposals", row["proposal_id"]) if row["proposal_id"] else None
    approvals = []
    if prop:
        approvals.append({"kind": "proposal", "label_ar": f"اعتماد عرض السعر {prop['code']}", "status": prop["status"],
                          "status_label_ar": labels.PROPOSAL_STATUS[prop["status"]], "by": repo.user_ref(users.get(prop["approved_by"])),
                          "at": prop["approved_at"], "ref_id": prop["id"]})
    for q in qa_rows[:5]:
        approvals.append({"kind": "qa_signoff", "label_ar": f"توقيع مراجعة الجودة #{q['id']}", "status": q["status"],
                          "status_label_ar": labels.QA_STATUS[q["status"]], "by": repo.user_ref(users.get(q["signed_off_by"])),
                          "at": q["signed_off_at"], "ref_id": q["id"]})
    phases = phases_of([{**t, "start": t["start"], "end": t["end"]} for t in tasks])
    return {
        "project": {
            **item, "land_area_m2": row["land_area_m2"], "floors": row["floors"], "bua_m2": row["bua_m2"],
            "description_ar": row["description_ar"], "params": params,
            "params_labels_ar": {"coverage_ratio": "نسبة التغطية", "setback_front_m": "الارتداد الأمامي (م)",
                                 "setback_side_m": "الارتداد الجانبي (م)", "setback_rear_m": "الارتداد الخلفي (م)",
                                 "height_m": "ارتفاع المبنى (م)", "floors": "عدد الأدوار", "parking_spaces": "مواقف السيارات",
                                 "units": "عدد الوحدات"},
            "services": [{"code": s, "name_ar": labels.SERVICE[s]} for s in repo.project_services(row)],
            "proposal_id": row["proposal_id"],
        },
        "phases": phases,
        "tasks": tv,
        "documents": [document_view(db, d, users) for d in doc_rows],
        "qa_reports": [qa_report_view(db, q, viewer) for q in qa_rows],
        "reports": [report_view(db, r) for r in rep_rows],
        "proposal": proposal_view(db, prop) if (not is_client or (prop and prop["status"] in ("sent", "accepted"))) else None,
        "approvals": approvals,
        "calendar": {"working_days_ar": "الأحد – الخميس", "weekend_ar": "الجمعة والسبت", "today": clock.today().isoformat(),
                     "holidays": []},
        "planner_notice_ar": load_config("phase_templates")["notice_ar"],
    }


# ---------------------------------------------------------------------------- security
def audit_view(db, row: dict, users: dict) -> dict:
    return {
        "id": row["id"], "ts": row["ts"], "actor": repo.user_ref(users.get(row["actor_id"])), "action": row["action"],
        "action_label_ar": labels.ACTIONS.get(row["action"], row["action"]), "resource": row["resource"],
        "decision": row["decision"], "reason_ar": row["reason_ar"], "run_id": row["run_id"],
    }


def alert_view(db, row: dict, users: dict | None = None) -> dict:
    users = users or _users(db)
    return {
        "id": row["id"], "ts": row["ts"], "severity": row["severity"], "severity_label_ar": labels.SEVERITY[row["severity"]],
        "type": row["type"], "type_label_ar": labels.ALERT_TYPE.get(row["type"], row["type"]), "message_ar": row["message_ar"],
        "actor": repo.user_ref(users.get(row["actor_id"])), "resource": row["resource"], "status": row["status"],
        "status_label_ar": labels.ALERT_STATUS.get(row["status"], row["status"]),
    }


# ---------------------------------------------------------------------------- dashboard
def visible_projects(db, viewer: dict) -> list[dict]:
    if viewer["role"] == "manager":
        return db.all("SELECT * FROM projects ORDER BY id")
    if viewer["role"] == "engineer":
        return db.all("SELECT p.* FROM projects p JOIN project_members m ON m.project_id = p.id WHERE m.user_id = ? ORDER BY p.id",
                      (viewer["id"],))
    return db.all("SELECT * FROM projects WHERE client_id = ? ORDER BY id", (viewer["client_id"],))


def dashboard(ctx, viewer: dict) -> dict:
    db = ctx.db
    k = ctx.agents["reporting"].kpis()
    pending = []
    for p in db.all("SELECT * FROM proposals WHERE status = 'draft' ORDER BY id DESC"):
        pending.append({"kind": "proposal", "id": p["id"], "title_ar": f"اعتماد عرض السعر {p['code']}",
                        "subtitle_ar": f"{repo.client_name(db, p['client_id'])} · {p['total']:,.0f} ريال", "created_at": p["created_at"]})
    for q in db.all("SELECT * FROM qa_reports WHERE status IN ('passed', 'issues') ORDER BY id DESC"):
        issues = loads(q["issues_json"], [])
        if any(i["severity"] == "high" for i in issues):
            continue
        latest = db.scalar("SELECT MAX(id) FROM qa_reports WHERE project_id = ? AND (document_id IS ? )", (q["project_id"], q["document_id"]))
        if latest != q["id"]:
            continue
        proj = db.get("projects", q["project_id"])
        pending.append({"kind": "qa_signoff", "id": q["id"], "title_ar": f"توقيع مراجعة الجودة — {proj['code']}",
                        "subtitle_ar": q["summary_ar"], "created_at": q["created_at"]})
    projects = visible_projects(db, viewer)
    by_status: dict[str, int] = {}
    for p in projects:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    upcoming = []
    today = clock.today().isoformat()
    for p in projects:
        for t in db.all("SELECT * FROM tasks WHERE project_id = ? AND is_milestone = 1 AND status != 'done' AND end >= ? ORDER BY end LIMIT 2",
                        (p["id"], today)):
            upcoming.append({"project_id": p["id"], "project_code": p["code"], "name_ar": t["name_ar"], "date": t["end"]})
    upcoming.sort(key=lambda x: x["date"])
    start_today = clock.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    runs_today = db.scalar("SELECT COUNT(*) FROM runs WHERE started_at >= ?", (start_today,)) or 0
    recent = db.all("SELECT * FROM steps ORDER BY id DESC LIMIT 15")
    return {
        **k,
        "pending_approvals": pending[:8],
        "projects_by_status": [{"status": s, "label_ar": labels.PROJECT_STATUS[s], "count": c} for s, c in by_status.items()],
        "upcoming_milestones": upcoming[:6],
        "agent_runs_today": runs_today,
        "recent_activity": [trace_step(s, ctx) for s in recent],
    }


def compliance_view(ctx, viewer: dict) -> dict:
    db = ctx.db
    pack = load_config("rule_pack")
    rules = []
    for r in pack["rules"]:
        rules.append({"id": r["id"], "name_ar": r["name_ar"], "param": r["param"],
                      "param_label_ar": {"coverage_ratio": "نسبة التغطية", "setback_front_m": "الارتداد الأمامي",
                                         "setback_side_m": "الارتداد الجانبي", "setback_rear_m": "الارتداد الخلفي",
                                         "height_m": "ارتفاع المبنى", "floors": "عدد الأدوار",
                                         "parking_spaces": "مواقف السيارات"}.get(r["param"], r["param"]),
                      "op": r["op"], "value": r["value"], "unit_ar": r["unit_ar"], "severity": r["severity"],
                      "severity_label_ar": labels.SEVERITY[r["severity"]], "applies_to": r["applies_to"],
                      "applies_to_labels_ar": [labels.PROJECT_TYPE[t] for t in r["applies_to"]], "fix_ar": r["fix_ar"]})
    reports, counts = [], {"high": 0, "medium": 0, "low": 0}
    awaiting = 0
    for p in visible_projects(db, viewer):
        q = db.one("SELECT * FROM qa_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (p["id"],))
        if not q:
            continue
        v = qa_report_view(db, q, viewer)
        reports.append(v)
        if q["status"] != "signed_off":
            for i in v["issues"]:
                counts[i["severity"]] += 1
            if not any(i["severity"] == "high" for i in v["issues"]):
                awaiting += 1
    return {"notice_ar": pack["notice_ar"], "rule_pack": {"name_ar": pack["name_ar"], "version": pack["version"], "rules": rules},
            "reports": reports, "summary": {"projects_checked": len(reports), "open_high": counts["high"],
                                            "open_medium": counts["medium"], "open_low": counts["low"], "awaiting_signoff": awaiting}}


# ---------------------------------------------------------------------------- agents
def agent_card(ctx, agent) -> dict:
    db = ctx.db
    if agent.key == "orchestrator":
        stats_row = db.one("SELECT COUNT(*) AS runs, SUM(status = 'error') AS errors, SUM(status = 'denied') AS denied, "
                           "MAX(started_at) AS last, AVG(duration_ms) AS avg FROM runs")
        fallbacks = db.scalar("SELECT COUNT(*) FROM steps WHERE mode = 'offline-fallback'") or 0
    else:
        stats_row = db.one("SELECT COUNT(*) AS runs, SUM(status = 'error') AS errors, SUM(status = 'denied') AS denied, "
                           "MAX(ts) AS last, AVG(duration_ms) AS avg FROM steps WHERE agent = ?", (agent.key,))
        fallbacks = db.scalar("SELECT COUNT(*) FROM steps WHERE agent = ? AND mode = 'offline-fallback'", (agent.key,)) or 0
    st = db.get("selftests", agent.key, key="agent")
    runs = stats_row["runs"] or 0
    errors = stats_row["errors"] or 0
    if st is None:
        health = "untested" if runs == 0 else ("healthy" if errors == 0 else "degraded")
    elif not st["passed"]:
        health = "failing"
    else:
        health = "healthy" if (errors == 0 or errors / max(runs, 1) < 0.2) else "degraded"
    info = agent.info()
    return {
        **info,
        "triggers_labels_ar": [labels.EVENTS.get(t, "كل العمليات") for t in info["triggers"]],
        "mode": agent.effective_mode(),
        "stats": {"runs": runs, "errors": errors, "denied": stats_row["denied"] or 0, "fallbacks": fallbacks,
                  "last_run_at": stats_row["last"], "avg_duration_ms": round(stats_row["avg"], 1) if stats_row["avg"] else None},
        "health": health, "health_label_ar": labels.AGENT_HEALTH[health],
        "last_self_test": ({"passed": bool(st["passed"]), "at": st["at"], "checks_passed": st["checks_passed"],
                            "checks_total": st["checks_total"]} if st else None),
    }
