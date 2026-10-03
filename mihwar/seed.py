"""Fictional demo data. The office, people, clients and projects are not real.

Plans and assignments are produced by the real Planner and Team agents, documents are
registered by the Document Control agent, and a short warm-up of real events is run
through the orchestrator so the dashboard and activity feed are not empty on first load.
"""
from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

from . import clock, labels, repo
from .agents.planner import build_plan
from .agents.proposal import ProposalAgent
from .agents.team import task_week_hours
from .config import load_config
from .db import dumps

CLIENTS = [
    (1, "عبدالله السبيعي", "Abdullah Alsubaie", "الرياض"),
    (2, "شركة عقارية (عميل افتراضي)", "Real-estate company (demo client)", "جدة"),
    (3, "هيفاء العمري", "Haifa Alomari", "الطائف"),
    (4, "مؤسسة ضيافة (عميل افتراضي)", "Hospitality company (demo client)", "أبها"),
]

# id, name_ar, name_en, role, title_ar, discipline, initials, licensed, license_no, client_id, default, capacity
USERS = [
    (1, "م. خالد الشهري", "Eng. Khalid Alshehri", "manager", "مدير المكتب · مهندس معماري استشاري", "architectural", "خ ش", 1, "DEMO-ENG-1001", None, 1, 20),
    (2, "م. سارة القحطاني", "Eng. Sarah Alqahtani", "engineer", "مهندسة معمارية أولى", "architectural", "س ق", 1, "DEMO-ENG-1042", None, 1, 40),
    (3, "م. فهد الدوسري", "Eng. Fahad Aldosari", "engineer", "مهندس معماري", "architectural", "ف د", 0, None, None, 0, 40),
    (4, "م. نورة الحربي", "Eng. Noura Alharbi", "engineer", "مهندسة إنشائية أولى", "structural", "ن ح", 1, "DEMO-ENG-1077", None, 0, 40),
    (5, "م. عبدالرحمن الزهراني", "Eng. Abdulrahman Alzahrani", "engineer", "مهندس كهرباء", "electrical", "ع ز", 0, None, None, 0, 40),
    (6, "م. لمى الغامدي", "Eng. Lama Alghamdi", "engineer", "مهندسة ميكانيكا وتكييف", "mechanical", "ل غ", 0, None, None, 0, 40),
    (7, "م. ماجد العنزي", "Eng. Majed Alanazi", "engineer", "مهندس صحي (سباكة وصرف)", "plumbing", "م ع", 0, None, None, 0, 40),
    (8, "أ. ليان المطيري", "Layan Almutairi", "engineer", "منسقة المشاريع والرخص", "general", "ل م", 0, None, None, 0, 40),
    (9, "عبدالله السبيعي", "Abdullah Alsubaie", "client", "عميل · مالك فيلا", None, "ع س", 0, None, 1, 1, 0),
    (10, "تركي القرني", "Turki Alqarni", "client", "عميل · ممثل شركة عقارية", None, "ت ق", 0, None, 2, 0, 0),
    (11, "هيفاء العمري", "Haifa Alomari", "client", "عميلة · مالكة استراحة", None, "ه ع", 0, None, 3, 0, 0),
    (12, "سعد الأحمري", "Saad Alahmari", "client", "عميل · ممثل مؤسسة ضيافة", None, "س أ", 0, None, 4, 0, 0),
]

# code, name_ar, name_en, client, type, city, district, land, floors, annex, services, status, start offset (working days ago), params
PROJECTS = [
    ("MST-2026-004", "مبنى مكاتب — أبها", "Office building, Abha", 4, "office", "أبها", "المنسك", 1500, 3, False,
     ["arch_design", "struct_design", "mep_design", "supervision"], "supervision", 80,
     {"coverage_ratio": 0.5, "setback_front_m": 6, "setback_side_m": 3, "setback_rear_m": 3, "height_m": 13, "floors": 3, "parking_spaces": 30, "units": 1}),
    ("MST-2026-007", "فيلا السبيعي — حي النرجس", "Alsubaie villa, Alnarjis", 1, "villa", "الرياض", "النرجس", 625, 2, True,
     ["arch_design", "struct_design", "mep_design", "permit"], "design", 30,
     {"coverage_ratio": 0.58, "setback_front_m": 4, "setback_side_m": 1.8, "setback_rear_m": 2, "height_m": 10.2, "floors": 2, "parking_spaces": 2, "units": 1}),
    ("MST-2026-009", "عمارة سكنية — حي الياقوت", "Residential building, Alyaqoot", 2, "residential_building", "جدة", "الياقوت", 900, 4, False,
     ["arch_design", "struct_design", "mep_design", "bim"], "design", 15,
     {"coverage_ratio": 0.65, "setback_front_m": 5, "setback_side_m": 2.5, "setback_rear_m": 2.5, "height_m": 16, "floors": 4, "parking_spaces": 8, "units": 8}),
    ("MST-2026-011", "استراحة العمري — الهدا", "Alomari rest house, Alhada", 3, "rest_house", "الطائف", "الهدا", 1200, 1, False,
     ["arch_design", "struct_design", "permit"], "permit", 46,
     {"coverage_ratio": 0.35, "setback_front_m": 5, "setback_side_m": 3, "setback_rear_m": 3, "height_m": 5, "floors": 1, "parking_spaces": 3, "units": 1}),
]

# project code -> list of (filename, uploader id, final state, qa_status)
DOCUMENTS = {
    "MST-2026-004": [
        ("مساقط الأدوار المعمارية.pdf", 2, "PUBLISHED", "signed_off"),
        ("S-101 Foundation and Column Layout.pdf", 4, "PUBLISHED", "signed_off"),
        ("حسابات التصميم الإنشائي.xlsx", 4, "PUBLISHED", "signed_off"),
        ("E-201 Lighting and Power Layout.pdf", 5, "PUBLISHED", "signed_off"),
        ("HVAC Ducting Layout.dwg", 6, "PUBLISHED", "signed_off"),
        ("مخطط شبكات الصرف والتغذية.pdf", 7, "PUBLISHED", "signed_off"),
        ("تقرير زيارة إشراف رقم 07.pdf", 4, "PUBLISHED", "signed_off"),
        ("تقرير زيارة إشراف رقم 08.pdf", 4, "SHARED", "not_requested"),
    ],
    "MST-2026-007": [
        ("مسقط الدور الأرضي.pdf", 2, "PUBLISHED", "signed_off"),
        ("مسقط الدور الأول.pdf", 2, "PUBLISHED", "signed_off"),
        ("الواجهات والقطاعات.pdf", 3, "SHARED", "not_requested"),
        ("S-101 مخطط الأساسات.pdf", 4, "WIP", "not_requested"),
        ("حسابات إنشائية - الأساسات.xlsx", 4, "WIP", "not_requested"),
        ("E-201 مخطط الإنارة.pdf", 5, "WIP", "not_requested"),
    ],
    "MST-2026-009": [
        ("مسقط الدور المتكرر - التصميم المبدئي.pdf", 2, "SHARED", "issues"),
        ("منظور خارجي للواجهة الرئيسية.jpg", 3, "PUBLISHED", "signed_off"),
        ("تقرير الرفع المساحي للموقع.pdf", 8, "WIP", "not_requested"),
    ],
    "MST-2026-011": [
        ("مساقط وواجهات الاستراحة.pdf", 3, "PUBLISHED", "signed_off"),
        ("مخطط الأساسات والأعمدة.pdf", 4, "PUBLISHED", "signed_off"),
        ("حسابات التسليح.xlsx", 4, "PUBLISHED", "signed_off"),
        ("تقرير فحص التربة.pdf", 8, "PUBLISHED", "signed_off"),
        ("نموذج طلب رخصة البناء.pdf", 8, "WIP", "not_requested"),
    ],
}


def demo_pdf(title: str, code: str) -> bytes:
    """A small, valid one-page PDF used as placeholder content for demo files."""
    def esc(s: str) -> str:
        s = s.encode("ascii", "replace").decode("ascii")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "\n".join([
        "0.8 w 30 30 782 535 re S", "30 120 m 812 120 l S", "560 30 m 560 120 l S",
        "0.6 0.6 0.6 RG 0.3 w",
        *[f"{x} 140 m {x} 545 l S" for x in range(110, 800, 90)],
        *[f"40 {y} m 802 {y} l S" for y in range(170, 545, 75)],
        "0 0 0 RG",
        "BT /F1 22 Tf 50 90 Td (Mihwar - demo engineering document) Tj ET",
        f"BT /F1 12 Tf 50 62 Td ({esc(code)}) Tj ET",
        "BT /F1 10 Tf 50 44 Td (Placeholder content for the hackathon prototype - not a real drawing.) Tj ET",
        f"BT /F1 10 Tf 575 90 Td (Doc: {esc(title)[:40]}) Tj ET",
        "BT /F1 10 Tf 575 62 Td (Office: Demo Engineering Consultancy \\(fictional\\)) Tj ET",
    ])
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    return bytes(out)


def demo_content(filename: str, code_hint: str) -> bytes:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return demo_pdf(filename, code_hint)
    return f"Mihwar demo file placeholder: {filename} ({code_hint})\n".encode("utf-8")


def _set_progress(db, project_id: int, today, lag: int = 0) -> None:
    for t in db.all("SELECT * FROM tasks WHERE project_id = ?", (project_id,)):
        s, e = clock.parse_date(t["start"]), clock.parse_date(t["end"])
        if e < today:
            status, prog = "done", 100
        elif s <= today:
            frac = clock.working_days_between(s, today) / max(1, clock.working_days_between(s, e))
            prog = max(5, min(95, int(frac * 100 / 5) * 5 - lag))
            status = "in_progress"
            if t["is_milestone"]:
                status, prog = "todo", 0
        else:
            status, prog = "todo", 0
        db.update("tasks", t["id"], {"status": status, "progress": prog})


def seed(ctx, activity: bool | None = None) -> None:
    db = ctx.db
    today = clock.today()
    activity = ctx.settings.seed_activity if activity is None else activity
    uploads = Path(ctx.settings.uploads_dir)
    if uploads.exists():
        shutil.rmtree(uploads, ignore_errors=True)
    uploads.mkdir(parents=True, exist_ok=True)

    for cid, name_ar, name_en, city in CLIENTS:
        db.insert("clients", {"id": cid, "name_ar": name_ar, "name_en": name_en, "city": city,
                              "phone": "+966 5X XXX XXXX", "email": f"client{cid}@example.demo"})
    for (uid, name_ar, name_en, role, title, disc, ini, lic, lic_no, cid, dflt, cap) in USERS:
        db.insert("users", {"id": uid, "name_ar": name_ar, "name_en": name_en, "role": role, "title_ar": title,
                            "discipline": disc, "initials": ini, "is_licensed": lic, "license_no": lic_no, "client_id": cid,
                            "default_for_role": dflt, "capacity_hours_week": cap})

    price_cfg = load_config("price_list")
    proposals: ProposalAgent = ctx.agents["proposal"]
    team = ctx.agents["team"]
    staff = team._staff()
    project_ids: dict[str, int] = {}
    for (code, name_ar, name_en, client_id, ptype, city, district, land, floors, annex, services, status, offset, params) in PROJECTS:
        brief = {"project_type": ptype, "city": city, "district": district, "land_area_m2": land, "floors": floors,
                 "has_annex": annex, "services": services}
        bua = proposals.estimate_bua(brief, price_cfg)
        start = clock.subtract_working_days(today, offset)
        pid = db.insert("projects", {
            "code": code, "name_ar": name_ar, "name_en": name_en, "client_id": client_id, "type": ptype, "city": city,
            "district": district, "status": status, "start_date": start.isoformat(), "end_date": None, "land_area_m2": land,
            "floors": floors, "bua_m2": bua, "description_ar": f"{labels.PROJECT_TYPE[ptype]} في {city} – حي {district} (مشروع افتراضي للعرض).",
            "params_json": params, "services_json": services, "proposal_id": None,
            "created_at": (clock.now() - timedelta(days=offset * 7 // 5)).isoformat(timespec="seconds"),
        })
        project_ids[code] = pid
        plan = build_plan(services, bua, start)
        key_to_id = {}
        for seq, t in enumerate(plan, 1):
            key_to_id[t["key"]] = db.insert("tasks", {
                "project_id": pid, "seq": seq, "tkey": t["key"], "phase": t["phase"], "phase_name_ar": t["phase_name_ar"],
                "name_ar": t["name_ar"], "discipline": t["discipline"], "start": t["start_date"].isoformat(),
                "end": t["end_date"].isoformat(), "duration_days": t["duration_days"], "hours": t["hours"], "depends_json": [],
                "assignee_id": None, "status": "todo", "progress": 0, "is_milestone": t["is_milestone"]})
        for t in plan:
            db.update("tasks", key_to_id[t["key"]], {"depends_json": dumps([key_to_id[d] for d in t["deps"]])})
        db.update("projects", pid, {"end_date": max(t["end_date"] for t in plan).isoformat()})
        _set_progress(db, pid, today, lag=10 if code == "MST-2026-009" else 0)
        # accepted proposal behind every project (used by the payment answers)
        p = proposals.price({**brief})
        created = (clock.now() - timedelta(days=offset * 7 // 5 + 3)).isoformat(timespec="seconds")
        prop_id = db.insert("proposals", {
            "code": f"PR-2026-{pid:03d}", "request_id": None, "client_id": client_id, "project_id": pid, "status": "accepted",
            "title_ar": f"عرض خدمات هندسية: {labels.PROJECT_TYPE[ptype]} في {city} – حي {district}",
            "brief_json": {**brief, "project_type_label_ar": labels.PROJECT_TYPE[ptype], "services_labels_ar": [labels.SERVICE[s] for s in services]},
            "bua_m2": p["bua_m2"], "lines_json": p["lines"], "subtotal": p["subtotal"], "vat_rate": p["vat_rate"], "vat": p["vat"],
            "total": p["total"], "milestones_json": p["milestones"], "validity_days": p["validity_days"], "valid_until": start.isoformat(),
            "exclusions_json": p["exclusions"], "assumptions_json": p["assumptions"],
            "history_json": [{"status": "draft", "at": created, "by": None}, {"status": "approved", "at": created, "by": 1},
                             {"status": "sent", "at": created, "by": 1}, {"status": "accepted", "at": created, "by": None}],
            "created_at": created, "approved_by": 1, "approved_at": created, "sent_at": created, "accepted_at": created})
        db.update("projects", pid, {"proposal_id": prop_id})

    # team assignment by the Team agent, oldest project first
    for code in ("MST-2026-004", "MST-2026-011", "MST-2026-007", "MST-2026-009"):
        pid = project_ids[code]
        loads = team._loads(today)
        for t in db.all("SELECT * FROM tasks WHERE project_id = ? ORDER BY seq", (pid,)):
            if t["is_milestone"]:
                continue
            u = team.choose(t, staff, loads, today)
            db.update("tasks", t["id"], {"assignee_id": u["id"]})
            repo.add_member(db, pid, u["id"])
            for w, h in task_week_hours(t, today).items():
                loads.setdefault(u["id"], {})
                loads[u["id"]][w] = loads[u["id"]].get(w, 0) + h
    # the manager had pre-assigned two large tasks on the Jeddah building to Sarah before Mihwar: creates a visible overload
    for key in ("arch_detail", "elevations"):
        t = db.one("SELECT id FROM tasks WHERE project_id = ? AND tkey = ?", (project_ids["MST-2026-009"], key))
        if t:
            db.update("tasks", t["id"], {"assignee_id": 2})
    repo.add_member(db, project_ids["MST-2026-009"], 2)
    for code in project_ids:  # the office manager supervises every project
        repo.add_member(db, project_ids[code], 1)

    # documents, registered by the Document Control agent
    docs_agent = ctx.agents["documents"]
    for code, files in DOCUMENTS.items():
        pid = project_ids[code]
        for filename, uploader_id, state, qa in files:
            uploader = db.get("users", uploader_id)
            repo.add_member(db, pid, uploader_id)
            res = docs_agent.op_register(pid, filename, demo_content(filename, f"{code} / {filename}"), uploader)
            did = res.output["document_id"]
            update = {"state": state, "qa_status": qa,
                      "uploaded_at": (clock.now() - timedelta(days=3 + did % 9)).isoformat(timespec="seconds")}
            if state == "PUBLISHED":
                update["revision"] = "C01"
            db.update("documents", did, update)
            if state == "PUBLISHED":
                docs_agent.issue_transmittal(pid, [did], db.get("users", 1), "إصدار معتمد للعميل للعلم والاطلاع")
        if code == "MST-2026-007":  # a second revision of the elevations shows revision control
            uploader = db.get("users", 3)
            docs_agent.op_register(pid, "الواجهات والقطاعات rev2.pdf", demo_content("elev-rev2.pdf", f"{code} elevations P02"), uploader)

    # QA reports by the Compliance agent
    comp = ctx.agents["compliance"]
    comp.op_check(project_ids["MST-2026-007"])
    comp.op_check(project_ids["MST-2026-009"])
    r = comp.op_check(project_ids["MST-2026-011"])
    if r.output["high"] == 0:
        comp.op_signoff(r.output["qa_report_id"], db.get("users", 4), "مطابق للاشتراطات التوضيحية؛ جاهز لتقديم الرخصة.")
    r4 = comp.op_check(project_ids["MST-2026-004"])
    if r4.output["high"] == 0:
        comp.op_signoff(r4.output["qa_report_id"], db.get("users", 1), "اعتماد مخرجات التصميم قبل التنفيذ.")

    # an earlier weekly report for the rest house (already sent to the client)
    ctx.agents["reporting"].op_weekly(project_ids["MST-2026-011"], send_to_client=True)

    if activity:
        warm_up(ctx, project_ids)


def warm_up(ctx, project_ids: dict[str, int]) -> None:
    """A few real events through the orchestrator so the activity feed tells a story."""
    from .orchestrator import Denied

    orch, db = ctx.orchestrator, ctx.db
    u = lambda i: db.get("users", i)  # noqa: E731
    orch.dispatch("client.request_submitted", {
        "text": "السلام عليكم، أفكر أبني ملحق خارجي في بيتي، كم تكلفة التصميم؟"}, u(11))
    orch.dispatch("client.request_submitted", {
        "text": "مرحبًا، نحتاج تصميم داخلي لمكاتب الإدارة في مبنانا بأبها، المساحة ٤٥٠ متر مربع، ونتمنى الانتهاء خلال شهرين."}, u(12))
    orch.dispatch("file.uploaded", {"project_id": project_ids["MST-2026-007"], "filename": "S-102 تفاصيل الأعمدة.pdf",
                                    "content": demo_content("S-102.pdf", "MST-2026-007 S-102")}, u(4))
    orch.dispatch("qa.requested", {"project_id": project_ids["MST-2026-009"]}, u(2))
    orch.dispatch("report.weekly", {"project_id": project_ids["MST-2026-007"], "send_to_client": True}, u(2))
    orch.dispatch("client.question", {"project_id": project_ids["MST-2026-007"], "text": "وين وصل مشروعي؟"}, u(9))
    orch.dispatch("security.simulate", {"kind": "unassigned_access"}, u(1))
    try:
        orch.dispatch("file.download", {"project_id": None, "document_id": db.scalar(
            "SELECT id FROM documents WHERE project_id = ? AND state = 'WIP' ORDER BY id LIMIT 1", (project_ids["MST-2026-007"],))}, u(9))
    except Denied:
        pass  # expected: the Security agent blocks the client and raises an alert


def ensure_seeded(ctx) -> None:
    if not ctx.db.scalar("SELECT COUNT(*) FROM users"):
        seed(ctx)


def reset(ctx) -> None:
    ctx.db.reset()
    seed(ctx)
