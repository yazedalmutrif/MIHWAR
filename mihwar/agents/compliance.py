"""QA & Compliance agent (وكيل المراجعة والامتثال).

Checks project parameters against an editable rule pack (coverage, setbacks, height,
floors, parking), checks deliverable completeness for the current phase and, for a
specific document, its naming and revision hygiene. A licensed engineer must sign off
before a file can be published; the agent never approves a design on its own.
"""
from __future__ import annotations

from .. import clock, labels, repo
from ..config import load_config
from ..db import loads
from .base import BaseAgent, Check, DomainError, StepResult
from .documents import CODE_RE


def _display(value, kind: str, unit: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{float(value) * 100:.0f}%"
    if kind == "int":
        return f"{int(value)} {unit}".strip()
    return f"{float(value):g} {unit}".strip()


def evaluate_rules(project_type: str, params: dict) -> tuple[list[dict], int, int]:
    """Pure function: returns (issues, checks_total, checks_passed) for the zoning rules."""
    pack = load_config("rule_pack")
    issues, total, passed = [], 0, 0
    for r in pack["rules"]:
        if project_type not in r["applies_to"]:
            continue
        actual = params.get(r["param"])
        if actual is None:
            continue
        total += 1
        op, limit = r["op"], r["value"]
        if op == "<=":
            ok = float(actual) <= float(limit) + 1e-9
            limit_s = "≤ " + _display(limit, r.get("display", "num"), r["unit_ar"] if r.get("display") != "pct" else "")
        elif op == ">=":
            ok = float(actual) >= float(limit) - 1e-9
            limit_s = "≥ " + _display(limit, r.get("display", "num"), r["unit_ar"])
        elif op == ">=per_unit":
            units = int(params.get("units") or 1)
            need = float(limit) * units
            ok = float(actual) >= need
            limit_s = f"≥ {need:g} ({r['unit_ar']})"
        else:
            continue
        actual_s = _display(actual, r.get("display", "num"), r["unit_ar"] if r.get("display") not in ("pct",) else "")
        if op == ">=per_unit":
            actual_s = f"{int(actual)}"
        if ok:
            passed += 1
        else:
            issues.append({
                "rule_id": r["id"], "rule_name_ar": r["name_ar"], "category": "zoning", "severity": r["severity"],
                "severity_label_ar": labels.SEVERITY[r["severity"]], "actual": actual_s, "limit": limit_s,
                "message_ar": f"{r['name_ar']}: القيمة الحالية {actual_s} والمطلوب {limit_s}", "fix_ar": r["fix_ar"],
            })
    return issues, total, passed


class ComplianceAgent(BaseAgent):
    key = "compliance"
    order = 6
    name_ar = "وكيل المراجعة والامتثال"
    name_en = "QA & Compliance"
    role_ar = "يفحص بيانات المشروع مقابل قواعد اشتراطات قابلة للتخصيص واكتمال مخرجات المرحلة، ويطلب توقيع مهندس مرخّص قبل النشر."
    role_en = "Checks project data against an editable rule pack and phase deliverables; requires a licensed engineer's sign-off before publishing."
    triggers = ("qa.requested", "qa.signed_off", "project.params_changed", "file.status_changed")
    outputs_ar = "تقرير مراجعة جودة بالملاحظات ودرجة خطورتها والحل المقترح"
    challenge_phrase_ar = "ترفع الكفاءة (جودة التصميم والامتثال قبل التقديم)"
    kpi_ar = "اكتشاف الملاحظات قبل التقديم وتقليل إعادة العمل"

    def phase_key(self, project: dict) -> str:
        return "permit" if project["status"] in ("permit", "supervision", "completed") else "design"

    def deliverables(self, project: dict) -> list[dict]:
        pack = load_config("rule_pack")
        services = set(repo.project_services(project))
        phases = ["design"] if self.phase_key(project) == "design" else ["design", "permit"]
        out = []
        for ph in phases:
            items = []
            for d in pack["deliverables"][ph]:
                if d["service"] not in services:
                    continue
                present = self.db.scalar(
                    "SELECT 1 FROM documents WHERE project_id = ? AND discipline = ? AND doc_type = ? AND state != 'ARCHIVED' LIMIT 1",
                    (project["id"], d["discipline"], d["doc_type"])) is not None
                items.append({"discipline": d["discipline"], "doc_type": d["doc_type"], "label_ar": d["label_ar"], "present": present})
            if items:
                pct = round(100 * sum(1 for i in items if i["present"]) / len(items))
                out.append({"phase": ph, "phase_name_ar": pack["phase_names"][ph], "complete_pct": pct, "items": items})
        return out

    def run_checks(self, project: dict, document: dict | None) -> dict:
        params = repo.project_params(project)
        issues, total, passed = evaluate_rules(project["type"], params)
        dels = self.deliverables(project)
        for ph in dels:
            for item in ph["items"]:
                total += 1
                if item["present"]:
                    passed += 1
                else:
                    issues.append({
                        "rule_id": f"D-{labels.DISCIPLINE_CODE[item['discipline']]}{item['doc_type']}", "rule_name_ar": "اكتمال المخرجات",
                        "category": "deliverables", "severity": "medium", "severity_label_ar": labels.SEVERITY["medium"],
                        "actual": "غير مرفوع", "limit": "مطلوب",
                        "message_ar": f"لم يُرفع بعد: {item['label_ar']} ({ph['phase_name_ar']})",
                        "fix_ar": "ارفع الملف في سجل الوثائق أو حدّث حالة المهمة المرتبطة.",
                    })
        if document:
            doc_checks = [
                ("DOC-01", "ترميز الملف وفق المنهجية", bool(CODE_RE.match(document["code"] or "")), "high",
                 "أعد رفع الملف ليُرمَّز تلقائيًا."),
                ("DOC-02", "الملف هو أحدث إصدار", document["superseded_by"] is None, "high", "راجع أحدث إصدار بدل هذا الملف."),
                ("DOC-03", "تخصص الملف محدد", document["discipline"] != "general" or document["doc_type"] in ("RP", "SH", "SP"), "low",
                 "حدّد التخصص من سجل الوثائق."),
            ]
            for rid, name, ok, sev, fix in doc_checks:
                total += 1
                if ok:
                    passed += 1
                else:
                    issues.append({"rule_id": rid, "rule_name_ar": name, "category": "document", "severity": sev,
                                   "severity_label_ar": labels.SEVERITY[sev], "actual": "لا", "limit": "نعم",
                                   "message_ar": f"{name}: لم يتحقق", "fix_ar": fix})
        order = {"high": 0, "medium": 1, "low": 2}
        issues.sort(key=lambda i: order[i["severity"]])
        n_high = sum(1 for i in issues if i["severity"] == "high")
        summary = f"الفحوص الناجحة: {passed} من {total}"
        if issues:
            summary += f" · الملاحظات: {len(issues)}" + (f" (عالية الخطورة: {n_high})" if n_high else "")
        else:
            summary += " · لا توجد ملاحظات"
        return {"issues": issues, "checks_total": total, "checks_passed": passed, "deliverables": dels, "summary_ar": summary,
                "n_high": n_high}

    # ------------------------------------------------------------------ operations
    def op_check(self, project_id: int, document_id: int | None = None) -> StepResult:
        project = self.db.get("projects", project_id)
        if not project:
            raise DomainError("not_found", "المشروع غير موجود", "Project not found", 404)
        document = self.db.get("documents", document_id) if document_id else None
        if document_id and (not document or document["project_id"] != project_id):
            raise DomainError("not_found", "الملف غير موجود في هذا المشروع", "Document not found in this project", 404)
        res = self.run_checks(project, document)
        status = "issues" if res["issues"] else "passed"
        phase = self.phase_key(project)
        rid = self.db.insert("qa_reports", {
            "project_id": project_id, "document_id": document_id, "phase": phase, "status": status,
            "summary_ar": res["summary_ar"], "issues_json": res["issues"], "checks_total": res["checks_total"],
            "checks_passed": res["checks_passed"], "deliverables_json": res["deliverables"], "created_at": clock.now_iso(),
        })
        if document:
            self.db.update("documents", document_id, {"qa_status": status})
        target = clock.ltr(document["code"] if document else project["code"])
        return StepResult(
            output={"qa_report_id": rid, "status": status, "issues": len(res["issues"]), "high": res["n_high"]},
            input_summary=f"{target} · {load_config('rule_pack')['name_ar']}",
            output_summary=res["summary_ar"],
            input={"project_id": project_id, "document_id": document_id},
        )

    def op_signoff(self, report_id: int, engineer: dict, note: str | None = None) -> StepResult:
        rep = self.db.get("qa_reports", report_id)
        if not rep:
            raise DomainError("not_found", "تقرير المراجعة غير موجود", "QA report not found", 404)
        if rep["status"] == "signed_off":
            raise DomainError("invalid_state", "التقرير موقّع مسبقًا", "The report is already signed off", 409)
        if not engineer.get("is_licensed"):
            raise DomainError("forbidden", "التوقيع مقصور على المهندسين المرخّصين", "Only licensed engineers can sign off", 403)
        issues = loads(rep["issues_json"], []) or []
        if any(i["severity"] == "high" for i in issues):
            raise DomainError("invalid_state", "توجد ملاحظات عالية الخطورة مفتوحة؛ عالجها ثم أعد الفحص قبل التوقيع",
                              "High-severity issues are open; fix them and re-run the check before signing off", 409)
        now = clock.now_iso()
        self.db.update("qa_reports", report_id, {"status": "signed_off", "signed_off_by": engineer["id"], "signed_off_at": now,
                                                  "signoff_note": (note or "").strip() or None})
        if rep["document_id"]:
            self.db.update("documents", rep["document_id"], {"qa_status": "signed_off"})
        open_med = sum(1 for i in issues if i["severity"] != "high")
        return StepResult(
            output={"qa_report_id": report_id, "status": "signed_off", "signed_off_by": engineer["id"]},
            input_summary=f"تقرير #{report_id} · {engineer['name_ar']} ({engineer.get('license_no') or '—'})",
            output_summary="وُقّع التقرير من مهندس مرخّص" + (f" · ملاحظات غير حرجة موثقة: {open_med}" if open_med else ""),
            input={"qa_report_id": report_id},
        )

    def op_gate(self, document_id: int, to_state: str) -> StepResult:
        doc = self.db.get("documents", document_id)
        if not doc:
            raise DomainError("not_found", "الملف غير موجود", "Document not found", 404)
        required = to_state == "PUBLISHED"
        passed = (doc["qa_status"] == "signed_off") if required else True
        reason = ("مسموح: مراجعة الجودة موقّعة من مهندس مرخّص" if passed else "ممنوع: لا يوجد تقرير جودة موقّع لهذا الملف") if required \
            else "لا يتطلب هذا الانتقال بوابة جودة"
        return StepResult(
            output={"required": required, "passed": passed, "reason_ar": reason},
            input_summary=f"{clock.ltr(doc['code'])} ← {labels.CDE_STATE.get(to_state, to_state)}",
            output_summary=("✔ " if passed else "✖ ") + reason,
            status="ok" if passed else "denied",
            input={"document_id": document_id, "to_state": to_state},
        )

    # ------------------------------------------------------------------ self-test
    def self_test(self) -> list[Check]:
        checks = []
        ok_params = {"coverage_ratio": 0.55, "setback_front_m": 4, "setback_side_m": 2, "setback_rear_m": 2, "height_m": 10,
                     "floors": 2, "parking_spaces": 2, "units": 1}
        issues, total, passed = evaluate_rules("villa", ok_params)
        checks.append(self.check("Compliant villa passes every zoning rule", "فيلا مطابقة تجتاز كل القواعد", not issues and total == passed == 7,
                                 f"{passed}/{total}"))
        bad = dict(ok_params, coverage_ratio=0.68, setback_side_m=1.5)
        issues2, _, _ = evaluate_rules("villa", bad)
        ids = {i["rule_id"]: i for i in issues2}
        checks.append(self.check("Coverage violation is high severity", "مخالفة نسبة التغطية عالية الخطورة",
                                 ids.get("Z-01", {}).get("severity") == "high", ids.get("Z-01", {}).get("message_ar", "")))
        checks.append(self.check("Side setback violation is medium severity", "مخالفة الارتداد الجانبي متوسطة",
                                 ids.get("Z-04", {}).get("severity") == "medium", ids.get("Z-04", {}).get("message_ar", "")))
        issues3, _, _ = evaluate_rules("residential_building", {"parking_spaces": 5, "units": 8})
        checks.append(self.check("Parking per unit", "المواقف لكل وحدة", any(i["rule_id"] == "Z-08" for i in issues3),
                                 next((i["message_ar"] for i in issues3 if i["rule_id"] == "Z-08"), "")))
        project = self.db.one("SELECT * FROM projects WHERE type = 'residential_building' LIMIT 1") or self.db.one("SELECT * FROM projects LIMIT 1")
        rep = self.op_check(project["id"])
        report = self.db.get("qa_reports", rep.output["qa_report_id"])
        checks.append(self.check("Report is stored with deliverables", "حفظ التقرير مع اكتمال المخرجات",
                                 report is not None and loads(report["deliverables_json"], []) != [], rep.output_summary))
        licensed = self.db.one("SELECT * FROM users WHERE role='engineer' AND is_licensed=1 LIMIT 1")
        high_blocked = None
        if rep.output["high"]:
            try:
                self.op_signoff(rep.output["qa_report_id"], licensed)
            except DomainError as e:
                high_blocked = e.code
        checks.append(self.check("Sign-off is blocked while high-severity issues are open", "منع التوقيع مع وجود ملاحظات عالية",
                                 (high_blocked == "invalid_state") if rep.output["high"] else True,
                                 str(high_blocked) if rep.output["high"] else "لا ملاحظات عالية في هذا المشروع"))
        unlicensed = self.db.one("SELECT * FROM users WHERE role='engineer' AND is_licensed=0 LIMIT 1")
        clean = self.db.one("SELECT * FROM projects WHERE type = 'rest_house' LIMIT 1") or project
        rep2 = self.op_check(clean["id"])
        refused = None
        try:
            self.op_signoff(rep2.output["qa_report_id"], unlicensed)
        except DomainError as e:
            refused = e.code
        checks.append(self.check("Unlicensed engineers cannot sign off", "غير المرخّص لا يوقّع", refused == "forbidden", str(refused)))
        if rep2.output["high"] == 0:
            self.op_signoff(rep2.output["qa_report_id"], licensed, "selftest")
            signed = self.db.get("qa_reports", rep2.output["qa_report_id"])["status"] == "signed_off"
        else:
            signed = False
        checks.append(self.check("Licensed engineer signs off a clean report", "توقيع المهندس المرخّص لتقرير سليم", signed, clean["code"]))
        return checks
