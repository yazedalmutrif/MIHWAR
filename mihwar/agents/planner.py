"""Project Planner agent (وكيل تخطيط المشاريع).

Turns an accepted proposal into phases, tasks, dependencies, milestones and dates on the
Saudi working week (Sunday–Thursday). Durations come from editable templates and scale
with the project's built-up area.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import clock, labels, repo
from ..config import load_config
from ..db import dumps
from .base import BaseAgent, Check, DomainError, StepResult


def size_factor(bua: float, cfg: dict) -> float:
    for limit, factor in cfg["size_factors"]:
        if limit is None or bua <= limit:
            return float(factor)
    return 1.0


def build_plan(services: list[str], bua: float, start: date) -> list[dict]:
    """Pure function: returns ordered task dicts with start/end dates and dependency keys."""
    cfg = load_config("phase_templates")
    factor = size_factor(bua or 0, cfg)
    selected = [dict(t) for t in cfg["tasks"] if t["service"] == "*" or t["service"] in services]
    keys = [t["key"] for t in selected]
    design_keys = [t["key"] for t in selected if t["phase"] in cfg["design_phases"] and not t.get("milestone")]
    by_key: dict[str, dict] = {}
    for t in selected:
        deps: list[str] = []
        for d in t["after"]:
            if d == "*design_done":
                deps += [k for k in design_keys if k != t["key"]]
            elif d in keys:
                deps.append(d)
        if not deps and t["key"] != "brief":
            deps = ["brief"]
        t["deps"] = list(dict.fromkeys(deps))
        milestone = bool(t.get("milestone"))
        days = 1 if milestone else max(1, round(t["days"] * factor))
        if t["deps"]:
            latest = max(by_key[d]["end_date"] for d in t["deps"])
            s = clock.next_working_day(latest + timedelta(days=1))
        else:
            s = clock.next_working_day(start)
        e = clock.add_working_days(s, days)
        t.update(
            start_date=s, end_date=e, duration_days=days, is_milestone=milestone,
            hours=0.0 if milestone else round(days * cfg["hours_per_day"] * float(t.get("load", 0.5)), 1),
            phase_name_ar=cfg["phases"][t["phase"]],
        )
        by_key[t["key"]] = t
    return selected


def phases_of(tasks: list[dict]) -> list[dict]:
    cfg = load_config("phase_templates")
    out = []
    for key in cfg["phase_order"]:
        ts = [t for t in tasks if t["phase"] == key]
        if not ts:
            continue
        hours = sum(float(t["hours"] or 0) for t in ts if not t["is_milestone"])
        prog = (sum(float(t["hours"] or 0) * (t.get("progress") or 0) for t in ts if not t["is_milestone"]) / hours) if hours else (
            100 if all((t.get("progress") or 0) >= 100 for t in ts) else 0)
        out.append({"key": key, "name_ar": cfg["phases"][key],
                    "start": min(str(t["start"]) for t in ts), "end": max(str(t["end"]) for t in ts),
                    "progress": round(prog)})
    return out


class PlannerAgent(BaseAgent):
    key = "planner"
    order = 3
    name_ar = "وكيل تخطيط المشاريع"
    name_en = "Project Planner"
    role_ar = "يحوّل العرض المقبول إلى مراحل ومهام واعتماديات ومعالم وجدول زمني على أيام العمل من الأحد إلى الخميس."
    role_en = "Turns an accepted proposal into phases, tasks, dependencies, milestones and dates (Sun–Thu working week)."
    triggers = ("proposal.accepted",)
    outputs_ar = "خطة المشروع (مخطط جانت) ومعالمه"
    challenge_phrase_ar = "وإدارة مشاريعها"
    kpi_ar = "زمن إعداد الجدول الزمني ودقة الالتزام بالمواعيد"

    def op_plan(self, project_id: int, start: str | None = None) -> StepResult:
        project = self.db.get("projects", project_id)
        if not project:
            raise DomainError("not_found", "المشروع غير موجود", "Project not found", 404)
        services = repo.project_services(project)
        start_date = clock.parse_date(start) if start else clock.next_working_day(clock.today() + timedelta(days=1))
        plan = build_plan(services, project["bua_m2"] or 0, start_date)
        self.db.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
        key_to_id: dict[str, int] = {}
        for seq, t in enumerate(plan, 1):
            tid = self.db.insert("tasks", {
                "project_id": project_id, "seq": seq, "tkey": t["key"], "phase": t["phase"],
                "phase_name_ar": t["phase_name_ar"], "name_ar": t["name_ar"], "discipline": t["discipline"],
                "start": t["start_date"].isoformat(), "end": t["end_date"].isoformat(),
                "duration_days": t["duration_days"], "hours": t["hours"], "depends_json": [],
                "assignee_id": None, "status": "todo", "progress": 0, "is_milestone": t["is_milestone"],
            })
            key_to_id[t["key"]] = tid
        for t in plan:
            self.db.update("tasks", key_to_id[t["key"]], {"depends_json": dumps([key_to_id[d] for d in t["deps"]])})
        end = max(t["end_date"] for t in plan)
        self.db.update("projects", project_id, {"start_date": start_date.isoformat(), "end_date": end.isoformat(),
                                                "status": "design" if project["status"] == "planning" else project["status"]})
        n_phases = len({t["phase"] for t in plan})
        n_ms = sum(1 for t in plan if t["is_milestone"])
        return StepResult(
            output={"project_id": project_id, "tasks": len(plan), "phases": n_phases, "milestones": n_ms,
                    "start_date": start_date.isoformat(), "end_date": end.isoformat()},
            input_summary=f"{project['code']} · الخدمات: {'، '.join(labels.SERVICE[s] for s in services)} · {project['bua_m2']:,.0f} م²",
            output_summary=f"المهام: {len(plan)} · المراحل: {n_phases} · المعالم: {n_ms} · من {clock.ar_date(start_date)} إلى {clock.ar_date(end)}",
            input={"project_id": project_id, "start": start_date.isoformat()},
        )

    def self_test(self) -> list[Check]:
        checks = []
        start = date(2026, 10, 1)  # a Thursday
        plan = build_plan(["arch_design", "struct_design", "mep_design", "permit"], 750, start)
        keys = {t["key"]: t for t in plan}
        checks.append(self.check("Tasks generated for every service", "توليد مهام لكل خدمة",
                                 {"concept", "struct_calc", "elec", "permit_ok", "handover"} <= set(keys), f"{len(plan)} مهمة"))
        weekend_ok = all(clock.is_working_day(t["start_date"]) and clock.is_working_day(t["end_date"]) for t in plan)
        checks.append(self.check("No task starts or ends on Friday/Saturday", "لا مهام تبدأ أو تنتهي يومي الجمعة والسبت", weekend_ok,
                                 "الأحد–الخميس"))
        deps_ok = all(t["start_date"] > keys[d]["end_date"] for t in plan for d in t["deps"])
        checks.append(self.check("Every task starts after its dependencies end", "كل مهمة تبدأ بعد انتهاء ما تعتمد عليه", deps_ok, ""))
        checks.append(self.check("Structural design waits for concept approval", "التصميم الإنشائي ينتظر اعتماد التصميم المبدئي",
                                 keys["struct_calc"]["start_date"] > keys["concept_ok"]["end_date"], keys["struct_calc"]["start_date"].isoformat()))
        checks.append(self.check("Milestones are one-day, zero-hour items", "المعالم يوم واحد دون ساعات عمل",
                                 all(t["duration_days"] == 1 and t["hours"] == 0 for t in plan if t["is_milestone"]), ""))
        big = build_plan(["arch_design"], 5000, start)
        small = build_plan(["arch_design"], 300, start)
        dur = lambda p: next(t for t in p if t["key"] == "arch_detail")["duration_days"]
        checks.append(self.check("Durations scale with project size", "المدد تتناسب مع حجم المشروع", dur(big) > dur(small), f"{dur(small)} ← {dur(big)} يوم"))
        project = self.db.one("SELECT * FROM projects ORDER BY id LIMIT 1")
        res = self.op_plan(project["id"])
        n = self.db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project["id"],))
        checks.append(self.check("Plan is written to the project", "حفظ الخطة في المشروع", n == res.output["tasks"] and n > 0, res.output_summary))
        return checks
