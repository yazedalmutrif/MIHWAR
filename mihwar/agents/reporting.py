"""Reporting & Client Comms agent (وكيل التقارير والتواصل).

Writes weekly progress reports, answers client questions ("وين وصل مشروعي؟") strictly
from project data, and computes the office KPIs (including estimated hours saved,
clearly labelled as an estimate based on editable assumptions).
"""
from __future__ import annotations

import re
from datetime import timedelta

from .. import clock, labels, repo
from ..config import load_config
from ..db import dumps, loads
from ..llm import LLMUnavailable
from .base import BaseAgent, Check, DomainError, StepResult, fmt_num
from .intake import P, norm

INTENTS: list[tuple[str, re.Pattern]] = [
    ("payment", P(r"دفعة|دفعات|الدفعة|فاتورة|فواتير|سداد|المبلغ|كم باقي|كم الباقي|payment|invoice|pay")),
    ("files", P(r"مخطط|المخططات|ملف|الملفات|أرسل لي|ابي اشوف|أبي أشوف|drawing|file|plans")),
    ("team", P(r"مين المهندس|من المهندس|المهندس المسؤول|المسؤول|مدير المشروع|فريق|engineer|who is|contact")),
    ("schedule", P(r"متى|موعد|تاريخ|ينتهي|تنتهي|التسليم|تسليم|الرخصة|when|deadline|date|finish")),
    ("status", P(r"وين وصل|وش صار|ايش صار|إيش صار|نسبة الإنجاز|الانجاز|الإنجاز|التقدم|وصلتوا|وصلتو|وين صرتوا|progress|status|how far|update")),
]

LLM_SCHEMA = {
    "type": "object",
    "properties": {"text_ar": {"type": "string"}},
    "required": ["text_ar"],
    "additionalProperties": False,
}


def detect_intent(text: str) -> str:
    n = norm(text)
    for intent, rx in INTENTS:
        if rx.search(n):
            return intent
    return "other"


def project_tasks(db, project_id: int) -> list[dict]:
    return db.all("SELECT * FROM tasks WHERE project_id = ? ORDER BY seq", (project_id,))


def progress_of(tasks: list[dict]) -> int:
    work = [t for t in tasks if not t["is_milestone"] and (t["hours"] or 0) > 0]
    total = sum(float(t["hours"]) for t in work)
    if not total:
        return 100 if tasks and all(t["status"] == "done" for t in tasks) else 0
    return round(sum(float(t["hours"]) * float(t["progress"] or 0) for t in work) / total)


def planned_progress_of(tasks: list[dict], today) -> int:
    work = [t for t in tasks if not t["is_milestone"] and (t["hours"] or 0) > 0]
    total = sum(float(t["hours"]) for t in work)
    if not total:
        return 0
    acc = 0.0
    for t in work:
        s, e = clock.parse_date(t["start"]), clock.parse_date(t["end"])
        if today < s:
            frac = 0.0
        elif today >= e:
            frac = 1.0
        else:
            frac = clock.working_days_between(s, today) / max(1, clock.working_days_between(s, e))
        acc += float(t["hours"]) * frac
    return round(acc / total * 100)


def health_of(db, project: dict, tasks: list[dict] | None = None) -> str:
    tasks = tasks if tasks is not None else project_tasks(db, project["id"])
    if not tasks:
        return "on_track"
    today = clock.today()
    delta = planned_progress_of(tasks, today) - progress_of(tasks)
    latest = db.one("SELECT * FROM qa_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project["id"],))
    high_open = bool(latest and latest["status"] != "signed_off" and any(i["severity"] == "high" for i in loads(latest["issues_json"], [])))
    overdue = any(t["status"] != "done" and not t["is_milestone"] and clock.parse_date(t["end"]) < today for t in tasks)
    if delta > 15:
        return "delayed"
    if delta > 5 or high_open or overdue:
        return "at_risk"
    return "on_track"


class ReportingAgent(BaseAgent):
    key = "reporting"
    order = 8
    name_ar = "وكيل التقارير والتواصل"
    name_en = "Reporting & Client Comms"
    role_ar = "يكتب تقارير التقدم الأسبوعية ويرسلها للعملاء، ويجيب عن أسئلتهم من بيانات المشروع فقط، ويحسب مؤشرات أداء المكتب."
    role_en = "Writes weekly progress reports, answers client questions from project data only, and computes office KPIs."
    triggers = ("report.weekly", "client.question")
    outputs_ar = "تقرير تقدم أسبوعي + إجابة للعميل + مؤشرات أداء المكتب"
    llm_capable = True
    challenge_phrase_ar = "تقديم خدماتها عن بُعد وتوسيع نطاق الوصول للعملاء"
    kpi_ar = "ساعات العمل اليدوي الموفّرة في التقارير والرد على العملاء"

    # ------------------------------------------------------------------ report building
    def build_sections(self, project: dict) -> dict:
        db = self.db
        tasks = project_tasks(db, project["id"])
        today = clock.today()
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        done_recent = [t for t in tasks if t["status"] == "done" and not t["is_milestone"]
                       and clock.parse_date(t["end"]) >= today - timedelta(days=21)]
        if not done_recent:
            done_recent = [t for t in tasks if t["status"] == "done" and not t["is_milestone"]][-3:]
        done = [f"{t['name_ar']} ({labels.DISCIPLINE[t['discipline']]})" for t in done_recent][-5:]
        horizon = today + timedelta(days=14)
        nxt = []
        for t in tasks:
            if t["status"] == "done" or t["is_milestone"]:
                continue
            if t["status"] in ("in_progress", "review") or clock.parse_date(t["start"]) <= horizon:
                who = users.get(t["assignee_id"], {}).get("name_ar", "—")
                nxt.append(f"{t['name_ar']} — {who}، حتى {clock.ar_date(t['end'])} ({t['progress']}%)")
        milestones = [f"{t['name_ar']} — {clock.ar_date(t['end'])}" for t in tasks if t["is_milestone"] and t["status"] != "done"
                      and clock.parse_date(t["end"]) <= today + timedelta(days=90)][:4]
        risks = [f"تأخر «{t['name_ar']}» عن موعده المخطط ({clock.ar_date(t['end'])})" for t in tasks
                 if t["status"] != "done" and not t["is_milestone"] and clock.parse_date(t["end"]) < today]
        latest = db.one("SELECT * FROM qa_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project["id"],))
        if latest and latest["status"] != "signed_off":
            for i in loads(latest["issues_json"], []):
                if i["severity"] == "high":
                    risks.append(f"ملاحظة جودة عالية الخطورة: {i['message_ar']}")
        team = self.ctx.agents["team"].view(today)
        members = repo.member_ids(db, project["id"])
        for e in team["engineers"]:
            if e["id"] in members and e["status"] == "overload":
                risks.append(f"ضغط عمل على {e['name_ar']} (ذروة {e['peak_pct']}%) قد يؤثر على مواعيد المشروع")
        return {"done": done, "next": nxt[:5], "milestones": milestones, "risks": risks[:5],
                "progress": progress_of(tasks), "planned": planned_progress_of(tasks, today)}

    @staticmethod
    def compose_body(project: dict, s: dict, period_start: str, period_end: str, client_name: str) -> str:
        lines = [f"السلام عليكم {client_name}،", "",
                 f"نفيدكم بتقرير التقدم لمشروع «{project['name_ar']}» ({clock.ltr(project['code'])}) للفترة من "
                 f"{clock.ar_date(period_start)} إلى {clock.ar_date(period_end)}.",
                 f"نسبة الإنجاز الحالية: {s['progress']}% (المخطط حتى اليوم: {s['planned']}%).", ""]
        lines.append("ما أُنجز مؤخرًا:")
        lines += [f"- {x}" for x in (s["done"] or ["لا مهام منجزة في هذه الفترة"])]
        lines += ["", "الأعمال الجارية والقادمة:"]
        lines += [f"- {x}" for x in (s["next"] or ["لا أعمال مجدولة خلال الأسبوعين القادمين"])]
        if s["milestones"]:
            lines += ["", "المعالم القادمة:"] + [f"- {x}" for x in s["milestones"]]
        lines += ["", "المخاطر والملاحظات:"]
        lines += [f"- {x}" for x in (s["risks"] or ["لا توجد مخاطر مؤثرة حاليًا"])]
        lines += ["", "مع تحيات فريق المشروع"]
        return "\n".join(lines)

    def _polish(self, body: str, sections: dict) -> tuple[str, str]:
        if not self.ctx.llm.enabled:
            return body, "offline"
        try:
            data = self.ctx.llm.complete_json(
                "You edit progress reports for a Saudi engineering office. Rewrite the Arabic report below in clear, "
                "professional Modern Standard Arabic. Keep every fact, number, date and name exactly as given; add no new "
                "facts. Keep the same sections and the '- ' bullets.",
                body, LLM_SCHEMA, max_tokens=4096)
            text = str(data.get("text_ar", "")).strip()
            if str(sections["progress"]) not in text:
                raise LLMUnavailable("polished text lost the progress figure")
            return text, "llm"
        except LLMUnavailable:
            return body, "offline-fallback"

    # ------------------------------------------------------------------ operations
    def op_weekly(self, project_id: int, send_to_client: bool = False, kind: str = "weekly") -> StepResult:
        project = self.db.get("projects", project_id)
        if not project:
            raise DomainError("not_found", "المشروع غير موجود", "Project not found", 404)
        today = clock.today()
        p_start, p_end = (today - timedelta(days=6)).isoformat(), today.isoformat()
        s = self.build_sections(project)
        client = repo.client_name(self.db, project["client_id"])
        body, mode = self._polish(self.compose_body(project, s, p_start, p_end, client), s)
        title = (f"التقرير الأسبوعي — {clock.ltr(project['code'])} ({clock.ar_date(p_end)})" if kind == "weekly"
                 else f"تحديث للعميل — {project['name_ar']} ({clock.ar_date(p_end)})")
        now = clock.now_iso()
        rid = self.db.insert("reports", {
            "project_id": project_id, "kind": kind, "title_ar": title, "period_start": p_start, "period_end": p_end,
            "progress_pct": s["progress"], "body_ar": body,
            "sections_json": {k: s[k] for k in ("done", "next", "milestones", "risks")},
            "sent_to_client": bool(send_to_client), "sent_at": now if send_to_client else None, "created_at": now, "mode": mode,
        })
        return StepResult(
            output={"report_id": rid, "progress_pct": s["progress"], "risks": len(s["risks"]), "sent_to_client": bool(send_to_client)},
            input_summary=f"{clock.ltr(project['code'])} · الفترة من {clock.ar_date(p_start)} إلى {clock.ar_date(p_end)}",
            output_summary=f"نسبة الإنجاز {s['progress']}% · الأعمال القادمة: {len(s['next'])} · المخاطر: {len(s['risks'])}"
                           + (" · أُرسل للعميل" if send_to_client else ""),
            mode=mode, input={"project_id": project_id, "send_to_client": send_to_client, "kind": kind},
        )

    def facts_for(self, project: dict, intent: str) -> tuple[str, list[dict], bool]:
        db = self.db
        tasks = project_tasks(db, project["id"])
        prog = progress_of(tasks)
        status = labels.PROJECT_STATUS.get(project["status"], project["status"])
        users = {u["id"]: u for u in db.all("SELECT * FROM users")}
        nxt_ms = next((t for t in tasks if t["is_milestone"] and t["status"] != "done"), None)
        current = next((t for t in tasks if t["status"] in ("in_progress", "review")), None)
        facts = [{"label_ar": "نسبة الإنجاز", "value": f"{prog}%"}, {"label_ar": "المرحلة", "value": status}]
        if intent == "status":
            text = f"مشروعك «{project['name_ar']}» في مرحلة {status}، ونسبة الإنجاز الحالية {prog}%."
            if current:
                text += f" العمل الجاري الآن: {current['name_ar']} (حتى {clock.ar_date(current['end'])})."
            if nxt_ms:
                text += f" المعلم القادم: «{nxt_ms['name_ar']}» بتاريخ {clock.ar_date(nxt_ms['end'])}."
                facts.append({"label_ar": "المعلم القادم", "value": f"{nxt_ms['name_ar']} — {clock.ar_date(nxt_ms['end'])}"})
            return text, facts, False
        if intent == "schedule":
            text = f"الموعد المخطط لانتهاء المشروع {clock.ar_date(project['end_date'])}."
            if nxt_ms:
                text = f"المعلم القادم «{nxt_ms['name_ar']}» بتاريخ {clock.ar_date(nxt_ms['end'])}. " + text
                facts.append({"label_ar": "المعلم القادم", "value": f"{nxt_ms['name_ar']} — {clock.ar_date(nxt_ms['end'])}"})
            facts.append({"label_ar": "نهاية المشروع (مخطط)", "value": clock.ar_date(project["end_date"])})
            return text, facts, False
        if intent == "files":
            pubs = db.all("SELECT * FROM documents WHERE project_id = ? AND state = 'PUBLISHED' ORDER BY id DESC", (project["id"],))
            if pubs:
                text = (f"لديك {len(pubs)} ملفات منشورة في البوابة، أحدثها «{pubs[0]['title']}» (الإصدار {pubs[0]['revision']}). "
                        "تظهر لك الملفات الجديدة بعد مراجعة الجودة وتوقيع المهندس المرخّص.")
            else:
                text = "لا توجد ملفات منشورة لك بعد؛ تظهر الملفات في البوابة بعد مراجعة الجودة وتوقيع المهندس المرخّص."
            facts.append({"label_ar": "الملفات المنشورة", "value": str(len(pubs))})
            return text, facts, False
        if intent == "payment":
            prop = db.get("proposals", project["proposal_id"]) if project.get("proposal_id") else None
            if prop:
                ms = loads(prop["milestones_json"], [])
                parts = "، ".join(f"{m['name_ar']} {m['pct']}% ({m['trigger_ar']})" for m in ms)
                text = (f"قيمة العقد {fmt_num(prop['total'])} ريال شاملة الضريبة، موزعة على {len(ms)} دفعات: {parts}. "
                        "حالة السداد الفعلية غير مربوطة في النموذج الأولي، وسيؤكدها لك مدير المكتب.")
                facts.append({"label_ar": "قيمة العقد", "value": f"{fmt_num(prop['total'])} ريال"})
                return text, facts, True
            return "سأحوّل سؤالك عن الدفعات إلى مدير المكتب للرد عليك.", facts, True
        if intent == "team":
            members = [users[i] for i in repo.member_ids(db, project["id"]) if i in users]
            names = "، ".join(f"{u['name_ar']} ({labels.DISCIPLINE.get(u['discipline'], '')})" for u in members[:5])
            text = f"فريق مشروعك: {names}. يمكنك مراسلتهم عبر البوابة وسيصل سؤالك للمهندس المختص." if members else \
                "يُشكَّل فريق المشروع الآن، وسيظهر في البوابة قريبًا."
            facts.append({"label_ar": "عدد أعضاء الفريق", "value": str(len(members))})
            return text, facts, False
        return "شكرًا لسؤالك. حوّلته إلى مدير المشروع للرد عليك في أقرب وقت.", facts, True

    def op_answer(self, project_id: int, text: str, actor: dict | None = None) -> StepResult:
        project = self.db.get("projects", project_id)
        if not project:
            raise DomainError("not_found", "المشروع غير موجود", "Project not found", 404)
        if not (text or "").strip():
            raise DomainError("validation_error", "السؤال فارغ", "The question is empty", 422)
        intent = detect_intent(text)
        answer, facts, escalated = self.facts_for(project, intent)
        mode = "offline"
        if self.ctx.llm.enabled and intent != "other":
            try:
                data = self.ctx.llm.complete_json(
                    "You answer a client of a Saudi engineering office on its client portal. Answer in friendly, "
                    "professional Arabic in at most three sentences, using ONLY the facts given. Never invent dates, "
                    "amounts or names.",
                    f"Client question: {text}\nFacts (JSON): {dumps(facts)}\nDraft answer: {answer}", LLM_SCHEMA, max_tokens=2048)
                polished = str(data.get("text_ar", "")).strip()
                if polished:
                    answer, mode = polished, "llm"
            except LLMUnavailable:
                mode = "offline-fallback"
        return StepResult(
            output={"text_ar": answer, "intent": intent, "intent_label_ar": labels.INTENT[intent], "escalated": escalated,
                    "facts": facts},
            input_summary=f"«{text[:80]}» · {clock.ltr(project['code'])}",
            output_summary=f"النية: {labels.INTENT[intent]}" + (" · حُوّل لمدير المشروع" if escalated else " · أُجيب تلقائيًا"),
            mode=mode, input={"project_id": project_id, "text": text},
        )

    # ------------------------------------------------------------------ KPIs (read model, no trace step)
    def kpis(self) -> dict:
        db = self.db
        assumptions = load_config("assumptions")
        active = db.scalar("SELECT COUNT(*) FROM projects WHERE status NOT IN ('completed', 'on_hold')") or 0
        pending = db.scalar("SELECT COUNT(*) FROM proposals WHERE status = 'draft'") or 0
        pairs = db.all("SELECT r.created_at AS a, p.created_at AS b FROM proposals p JOIN requests r ON r.id = p.request_id")
        secs = [max(0.0, (clock.parse_ts(x["b"]) - clock.parse_ts(x["a"])).total_seconds()) for x in pairs]
        avg_s = round(sum(secs) / len(secs), 1) if secs else 0
        team = self.ctx.agents["team"].view()
        docs = db.scalar("SELECT COUNT(*) FROM documents") or 0
        open_issues = 0
        for p in db.all("SELECT id FROM projects"):
            latest = db.one("SELECT * FROM qa_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (p["id"],))
            if latest and latest["status"] != "signed_off":
                open_issues += len(loads(latest["issues_json"], []))
        alerts = db.scalar("SELECT COUNT(*) FROM alerts WHERE status = 'open'") or 0
        minutes = 0.0
        for row in db.all("SELECT agent, COUNT(*) AS n FROM steps WHERE status = 'ok' GROUP BY agent"):
            minutes += assumptions["minutes_saved_per_step"].get(row["agent"], 0) * row["n"]
        hours = round(minutes / 60.0, 1)
        cost = round(hours * float(assumptions["hourly_cost_sar"]))
        k = [
            ("active_projects", "المشاريع النشطة", active, "", False, None),
            ("proposals_pending", "عروض بانتظار الاعتماد", pending, "", False, "تحتاج اعتماد مدير المكتب"),
            ("avg_intake_to_proposal_s", "من الطلب إلى مسودة العرض", avg_s, "ثانية", False, "متوسط زمن المعالجة الآلية في المنصة"),
            ("team_utilisation_pct", "استغلال طاقة الفريق", team["summary"]["avg_utilisation_pct"], "%", False, "متوسط 8 أسابيع قادمة"),
            ("docs_controlled", "ملفات تحت التحكم", docs, "", False, None),
            ("qa_open_issues", "ملاحظات جودة مفتوحة", open_issues, "", False, None),
            ("security_alerts_open", "تنبيهات أمنية مفتوحة", alerts, "", False, None),
            ("hours_saved_est", "ساعات موفّرة (تقدير)", hours, "ساعة", True, assumptions["notice_ar"]),
            ("cost_saved_est", "تكلفة موفّرة (تقدير)", cost, "ريال", True, assumptions["notice_ar"]),
        ]
        return {"kpis": [{"key": a, "label_ar": b, "value": c, "unit_ar": d, "estimate": e, "hint_ar": f} for a, b, c, d, e, f in k],
                "estimate_notice_ar": assumptions["notice_ar"]}

    # ------------------------------------------------------------------ self-test
    def self_test(self) -> list[Check]:
        checks = []
        tasks = [{"is_milestone": 0, "hours": 30, "progress": 100, "status": "done"},
                 {"is_milestone": 0, "hours": 10, "progress": 50, "status": "in_progress"},
                 {"is_milestone": 1, "hours": 0, "progress": 0, "status": "todo"}]
        checks.append(self.check("Progress is weighted by hours", "نسبة الإنجاز موزونة بالساعات", progress_of(tasks) == 88, f"{progress_of(tasks)}%"))
        cases = {"وين وصل مشروعي؟": "status", "متى تطلع الرخصة؟": "schedule", "أبي أشوف المخططات": "files",
                 "كم الدفعة الجاية؟": "payment", "مين المهندس المسؤول؟": "team", "عندكم خصم للطلاب؟": "other",
                 "What is the progress?": "status"}
        wrong = {q: detect_intent(q) for q, exp in cases.items() if detect_intent(q) != exp}
        checks.append(self.check("Client questions are routed to the right intent", "تحديد نية سؤال العميل", not wrong,
                                 "كل الحالات صحيحة" if not wrong else str(wrong)))
        project = self.db.one("SELECT * FROM projects WHERE status = 'design' ORDER BY id LIMIT 1") or self.db.one("SELECT * FROM projects LIMIT 1")
        ans = self.op_answer(project["id"], "وين وصل مشروعي؟")
        prog = progress_of(project_tasks(self.db, project["id"]))
        checks.append(self.check("Status answer uses real project data", "الإجابة تستخدم بيانات المشروع الفعلية",
                                 f"{prog}%" in ans.output["text_ar"] and not ans.output["escalated"], ans.output["text_ar"][:120]))
        other = self.op_answer(project["id"], "عندكم خصم للطلاب؟")
        checks.append(self.check("Unknown questions are escalated to a human", "تحويل الأسئلة غير المعروفة لموظف", other.output["escalated"], other.output_summary))
        rep = self.op_weekly(project["id"], send_to_client=True)
        row = self.db.get("reports", rep.output["report_id"])
        sec = loads(row["sections_json"], {})
        checks.append(self.check("Weekly report has all sections and is sent", "التقرير الأسبوعي مكتمل الأقسام ومُرسل",
                                 set(sec) == {"done", "next", "milestones", "risks"} and row["sent_to_client"] == 1 and f"{row['progress_pct']}%" in row["body_ar"],
                                 rep.output_summary))
        k = {x["key"]: x for x in self.kpis()["kpis"]}
        checks.append(self.check("KPIs computed; savings flagged as estimates", "حساب المؤشرات ووسم التوفير كتقدير",
                                 len(k) == 9 and k["hours_saved_est"]["estimate"] and not k["active_projects"]["estimate"],
                                 f"{k['active_projects']['value']} مشاريع نشطة"))
        return checks
