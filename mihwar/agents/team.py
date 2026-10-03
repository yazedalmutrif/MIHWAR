"""Team & Resources agent (وكيل الفريق والموارد).

Assigns tasks to engineers by discipline and available capacity, computes weekly
utilisation, flags overloads and suggests concrete rebalancing moves.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .. import clock, labels, repo
from .base import BaseAgent, Check, DomainError, StepResult

WINDOW_WEEKS = 8
HIGH_PCT = 85
OVER_PCT = 100


def task_week_hours(task: dict, today: date) -> dict[date, float]:
    """Remaining hours of a task spread over its remaining working days, grouped by week (Sunday)."""
    if task["status"] == "done" or task.get("is_milestone") or not task.get("hours"):
        return {}
    remaining = float(task["hours"]) * (100 - float(task.get("progress") or 0)) / 100.0
    if remaining <= 0:
        return {}
    start, end = clock.parse_date(task["start"]), clock.parse_date(task["end"])
    if end < today:
        return {clock.week_start(today): remaining}
    s = max(start, today)
    days = []
    d = s
    while d <= end:
        if clock.is_working_day(d):
            days.append(d)
        d += timedelta(days=1)
    if not days:
        return {clock.week_start(today): remaining}
    per_day = remaining / len(days)
    out: dict[date, float] = defaultdict(float)
    for d in days:
        out[clock.week_start(d)] += per_day
    return dict(out)


class TeamAgent(BaseAgent):
    key = "team"
    order = 4
    name_ar = "وكيل الفريق والموارد"
    name_en = "Team & Resources"
    role_ar = "يوزّع المهام على المهندسين حسب التخصص والطاقة المتاحة، ويعرض نسب الاستغلال، وينبّه عند الضغط ويقترح إعادة التوزيع."
    role_en = "Assigns tasks by discipline and capacity, shows utilisation, flags overload and suggests rebalancing."
    triggers = ("plan.created", "task.changed", "team.rebalance")
    outputs_ar = "إسناد المهام + نسب الاستغلال الأسبوعية + تنبيهات واقتراحات"
    challenge_phrase_ar = "وإدارة فرقها عن بُعد"
    kpi_ar = "نسبة استغلال طاقة الفريق وتقليل الضغط غير المتوازن"

    # ------------------------------------------------------------------ load model
    def _staff(self) -> list[dict]:
        return self.db.all("SELECT * FROM users WHERE role IN ('engineer', 'manager') ORDER BY role DESC, id")

    def _loads(self, today: date, exclude_task: int | None = None) -> dict[int, dict[date, float]]:
        loads: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        rows = self.db.all("SELECT * FROM tasks WHERE assignee_id IS NOT NULL AND status != 'done'")
        for t in rows:
            if exclude_task and t["id"] == exclude_task:
                continue
            for w, h in task_week_hours(t, today).items():
                loads[t["assignee_id"]][w] += h
        return loads

    def _candidates(self, discipline: str, staff: list[dict]) -> list[dict]:
        cands = [u for u in staff if u["role"] == "engineer" and u["discipline"] == discipline]
        if not cands:
            cands = [u for u in staff if u["role"] == "engineer" and u["discipline"] == "general"]
        if not cands:
            cands = [u for u in staff if u["role"] == "manager"]
        return cands

    @staticmethod
    def _peak_after(load: dict[date, float], add: dict[date, float], cap: float) -> float:
        if not add:
            return 0.0
        return max(((load.get(w, 0) + add.get(w, 0)) / cap * 100) for w in add)

    def choose(self, task: dict, staff: list[dict], loads, today: date) -> dict | None:
        add = task_week_hours(task, today)
        best = None
        for u in self._candidates(task["discipline"], staff):
            cap = float(u["capacity_hours_week"] or 40)
            peak = self._peak_after(loads.get(u["id"], {}), add, cap)
            total = sum(loads.get(u["id"], {}).values()) / cap
            key = (round(peak, 1), round(total, 3), u["id"])
            if best is None or key < best[0]:
                best = (key, u)
        return best[1] if best else None

    # ------------------------------------------------------------------ view
    def view(self, today: date | None = None) -> dict:
        today = today or clock.today()
        start = clock.week_start(today)
        weeks = [start + timedelta(days=7 * i) for i in range(WINDOW_WEEKS)]
        loads = self._loads(today)
        staff = self._staff()
        engineers, alerts = [], []
        for u in staff:
            if u["role"] == "manager" and not loads.get(u["id"]):
                continue
            cap = float(u["capacity_hours_week"] or 40)
            weekly = []
            for w in weeks:
                h = loads.get(u["id"], {}).get(w, 0.0)
                weekly.append({"week_start": w.isoformat(), "hours": round(h, 1), "pct": round(h / cap * 100)})
            pcts = [x["pct"] for x in weekly]
            util, peak = round(sum(pcts) / len(pcts)), max(pcts)
            status = "overload" if peak > OVER_PCT else ("high" if peak >= HIGH_PCT else "ok")
            tasks = self.db.all("SELECT t.id, t.project_id, p.code FROM tasks t JOIN projects p ON p.id = t.project_id "
                                "WHERE t.assignee_id = ? AND t.status != 'done' AND t.is_milestone = 0", (u["id"],))
            projects = {}
            for t in tasks:
                projects[t["project_id"]] = {"id": t["project_id"], "code": t["code"]}
            engineers.append({
                "id": u["id"], "name_ar": u["name_ar"], "name_en": u["name_en"], "title_ar": u["title_ar"],
                "discipline": u["discipline"], "discipline_label_ar": labels.label(labels.DISCIPLINE, u["discipline"]),
                "is_licensed": bool(u["is_licensed"]), "capacity_hours_week": cap, "utilisation_pct": util,
                "peak_pct": peak, "status": status, "status_label_ar": labels.TEAM_STATUS[status], "weekly": weekly,
                "tasks_count": len(tasks), "projects": list(projects.values()),
            })
            for x in weekly:
                if x["pct"] > OVER_PCT:
                    alerts.append({"id": f"ov-{u['id']}-{x['week_start']}", "severity": "high", "engineer_id": u["id"],
                                   "week_start": x["week_start"],
                                   "message_ar": f"حمل {u['name_ar']} في أسبوع {clock.ar_date(x['week_start'], False)} يبلغ {x['pct']}% من الطاقة الأسبوعية"})
                elif x["pct"] >= HIGH_PCT:
                    alerts.append({"id": f"hi-{u['id']}-{x['week_start']}", "severity": "medium", "engineer_id": u["id"],
                                   "week_start": x["week_start"],
                                   "message_ar": f"حمل مرتفع على {u['name_ar']} في أسبوع {clock.ar_date(x['week_start'], False)} ({x['pct']}%)"})
        suggestions = self._suggestions(today, staff, loads)
        helped = {s["from"]["id"] for s in suggestions}
        capacity_notes = []
        for e in engineers:
            if e["status"] == "overload" and e["id"] not in helped:
                peers = [u for u in staff if u["role"] == "engineer" and u["discipline"] == e["discipline"] and u["id"] != e["id"]]
                why = "ولا يوجد مهندس آخر بالتخصص نفسه" if not peers else "وزملاؤه بالتخصص نفسه لا يملكون طاقة كافية في الأسابيع نفسها"
                capacity_notes.append({
                    "engineer_id": e["id"],
                    "message_ar": f"{e['name_ar']} ({e['discipline_label_ar']}) فوق الطاقة بذروة {e['peak_pct']}% {why}؛ "
                                  "يُقترح تمديد مدة إحدى مهامه أو الاستعانة بمهندس إضافي مؤقتًا."})
        avg = round(sum(e["utilisation_pct"] for e in engineers) / len(engineers)) if engineers else 0
        return {"window": {"start": start.isoformat(), "weeks": WINDOW_WEEKS}, "engineers": engineers, "alerts": alerts,
                "suggestions": suggestions, "capacity_notes": capacity_notes,
                "summary": {"avg_utilisation_pct": avg, "overloaded_count": sum(1 for e in engineers if e["status"] == "overload"),
                            "engineers_count": len(engineers)}}

    def _suggestions(self, today: date, staff: list[dict], loads) -> list[dict]:
        out = []
        by_id = {u["id"]: u for u in staff}
        for uid, wk in loads.items():
            u = by_id.get(uid)
            if not u:
                continue
            cap = float(u["capacity_hours_week"] or 40)
            over = sorted(((w, h) for w, h in wk.items() if h / cap * 100 > OVER_PCT), key=lambda x: x[0])
            if not over:
                continue
            week, hours = over[0]
            tasks = self.db.all("SELECT t.*, p.code AS project_code FROM tasks t JOIN projects p ON p.id = t.project_id "
                                "WHERE t.assignee_id = ? AND t.status != 'done' AND t.is_milestone = 0", (uid,))
            tasks = [t for t in tasks if week in task_week_hours(t, today)]
            tasks.sort(key=lambda t: -task_week_hours(t, today)[week])
            done = False
            for t in tasks:
                add = task_week_hours(t, today)
                for c in self._candidates(t["discipline"], staff):
                    if c["id"] == uid:
                        continue
                    ccap = float(c["capacity_hours_week"] or 40)
                    if self._peak_after(loads.get(c["id"], {}), add, ccap) <= OVER_PCT:
                        before = round(hours / cap * 100)
                        after = round((hours - add[week]) / cap * 100)
                        c_after = round((loads.get(c["id"], {}).get(week, 0) + add[week]) / ccap * 100)
                        out.append({
                            "id": f"sg-{t['id']}-{c['id']}", "task_id": t["id"], "task_name_ar": t["name_ar"],
                            "project_code": t["project_code"], "from": {"id": uid, "name_ar": u["name_ar"]},
                            "to": {"id": c["id"], "name_ar": c["name_ar"]}, "hours": round(add[week], 1),
                            "reason_ar": f"تجاوز الطاقة في أسبوع {clock.ar_date(week, False)} ({before}%)",
                            "effect_ar": f"ينخفض حمل {u['name_ar']} من {before}% إلى {after}%، ويصبح حمل {c['name_ar']} {c_after}%",
                        })
                        done = True
                        break
                if done:
                    break
        return out

    # ------------------------------------------------------------------ operations
    def op_assign(self, project_id: int) -> StepResult:
        project = self.db.get("projects", project_id)
        if not project:
            raise DomainError("not_found", "المشروع غير موجود", "Project not found", 404)
        today = clock.today()
        staff = self._staff()
        loads = self._loads(today)
        tasks = self.db.all("SELECT * FROM tasks WHERE project_id = ? AND assignee_id IS NULL ORDER BY seq", (project_id,))
        assigned: dict[int, int] = defaultdict(int)
        for t in tasks:
            if t["is_milestone"]:
                continue
            u = self.choose(t, staff, loads, today)
            if not u:
                continue
            self.db.update("tasks", t["id"], {"assignee_id": u["id"]})
            repo.add_member(self.db, project_id, u["id"])
            for w, h in task_week_hours(t, today).items():
                loads.setdefault(u["id"], defaultdict(float))
                loads[u["id"]][w] = loads[u["id"]].get(w, 0) + h
            assigned[u["id"]] += 1
        names = {u["id"]: u["name_ar"] for u in staff}
        detail = "، ".join(f"{names[k]}: {v}" for k, v in assigned.items())
        team = self.view(today)
        n_alerts = sum(1 for a in team["alerts"] if a["severity"] == "high")
        return StepResult(
            output={"project_id": project_id, "assigned": sum(assigned.values()), "engineers": len(assigned),
                    "overload_alerts": n_alerts},
            input_summary=f"{project['code']} · مهام بلا مسؤول: {len(tasks)}",
            output_summary=f"المهام المسندة: {sum(assigned.values())} ({detail})" +
                           (f" · تنبيهات الضغط: {n_alerts}" if n_alerts else ""),
            input={"project_id": project_id},
        )

    def op_recompute(self, task_id: int | None = None) -> StepResult:
        team = self.view()
        s = team["summary"]
        return StepResult(
            output={"avg_utilisation_pct": s["avg_utilisation_pct"], "overloaded_count": s["overloaded_count"],
                    "suggestions": len(team["suggestions"])},
            input_summary=f"تحديث المهمة #{task_id}" if task_id else "إعادة حساب الأحمال",
            output_summary=f"متوسط الاستغلال {s['avg_utilisation_pct']}% · فوق الطاقة: {s['overloaded_count']} · "
                           f"اقتراحات إعادة التوزيع: {len(team['suggestions'])}",
            input={"task_id": task_id},
        )

    def op_rebalance(self, task_id: int, to_engineer_id: int) -> StepResult:
        task = self.db.get("tasks", task_id)
        target = self.db.get("users", to_engineer_id)
        if not task or not target:
            raise DomainError("not_found", "المهمة أو المهندس غير موجود", "Task or engineer not found", 404)
        if target["role"] != "engineer":
            raise DomainError("validation_error", "يمكن الإسناد إلى المهندسين فقط", "Tasks can only go to engineers", 422)
        if task["discipline"] != "general" and target["discipline"] != task["discipline"]:
            raise DomainError("validation_error", "تخصص المهندس لا يطابق تخصص المهمة", "Engineer discipline does not match the task", 422)
        prev = self.db.get("users", task["assignee_id"]) if task["assignee_id"] else None
        self.db.update("tasks", task_id, {"assignee_id": to_engineer_id})
        repo.add_member(self.db, task["project_id"], to_engineer_id)
        team = self.view()
        return StepResult(
            output={"task_id": task_id, "from": prev["id"] if prev else None, "to": to_engineer_id},
            input_summary=f"«{task['name_ar']}»: من {prev['name_ar'] if prev else '—'} إلى {target['name_ar']}",
            output_summary=f"أُعيد الإسناد · متوسط الاستغلال الآن {team['summary']['avg_utilisation_pct']}%",
            input={"task_id": task_id, "to_engineer_id": to_engineer_id},
        )

    # ------------------------------------------------------------------ self-test
    def self_test(self) -> list[Check]:
        checks = []
        today = clock.today()
        t = {"status": "todo", "is_milestone": 0, "hours": 30, "progress": 0,
             "start": clock.next_working_day(today).isoformat(), "end": clock.add_working_days(clock.next_working_day(today), 5).isoformat()}
        spread = task_week_hours(t, today)
        checks.append(self.check("Task hours are spread over working days", "توزيع ساعات المهمة على أيام العمل",
                                 abs(sum(spread.values()) - 30) < 0.01, f"{len(spread)} أسبوع"))
        staff = self._staff()
        loads = {}
        struct_task = {**t, "discipline": "structural"}
        chosen = self.choose(struct_task, staff, loads, today)
        checks.append(self.check("Discipline match", "مطابقة التخصص", chosen is not None and chosen["discipline"] == "structural",
                                 chosen["name_ar"] if chosen else "none"))
        archs = [u for u in staff if u["role"] == "engineer" and u["discipline"] == "architectural"]
        busy = {archs[0]["id"]: {w: 200.0 for w in spread}}
        arch_task = {**t, "discipline": "architectural"}
        chosen2 = self.choose(arch_task, staff, busy, today)
        checks.append(self.check("Least-loaded engineer is chosen", "اختيار المهندس الأقل حملًا",
                                 len(archs) > 1 and chosen2["id"] != archs[0]["id"], chosen2["name_ar"]))
        view = self.view(today)
        checks.append(self.check("Overload is detected", "كشف تجاوز الطاقة", view["summary"]["overloaded_count"] >= 1,
                                 "، ".join(e["name_ar"] for e in view["engineers"] if e["status"] == "overload")))
        checks.append(self.check("A rebalancing suggestion is produced", "توليد اقتراح لإعادة التوزيع", len(view["suggestions"]) >= 1,
                                 view["suggestions"][0]["effect_ar"] if view["suggestions"] else ""))
        project = self.db.one("SELECT * FROM projects ORDER BY id DESC LIMIT 1")
        self.db.execute("UPDATE tasks SET assignee_id = NULL WHERE project_id = ?", (project["id"],))
        res = self.op_assign(project["id"])
        unassigned = self.db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id = ? AND assignee_id IS NULL AND is_milestone = 0", (project["id"],))
        checks.append(self.check("Every non-milestone task gets an engineer", "إسناد كل المهام", unassigned == 0, res.output_summary))
        return checks
