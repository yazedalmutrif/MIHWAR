"""Proposal & Pricing agent (وكيل العروض والتسعير).

Builds the scope of services, a fee estimate from the office's editable price list,
VAT, payment milestones, validity and exclusions. Drafts always wait for the office
manager's approval before the client sees them (human in the loop). When the client
accepts, it opens the project record.
"""
from __future__ import annotations

from datetime import timedelta

from .. import clock, labels, repo
from ..config import load_config
from ..db import dumps, loads
from .base import BaseAgent, Check, DomainError, StepResult, fmt_num


def round100(value: float) -> float:
    return float(round(value / 100.0) * 100)


class ProposalAgent(BaseAgent):
    key = "proposal"
    order = 2
    name_ar = "وكيل العروض والتسعير"
    name_en = "Proposal & Pricing"
    role_ar = "يجهّز نطاق الخدمات والأتعاب والضريبة ودفعات السداد من قائمة أسعار المكتب، وينتظر اعتماد المدير قبل إرساله للعميل."
    role_en = "Drafts scope, fees, VAT and payment milestones from the office price list; waits for manager approval before the client sees it."
    triggers = ("brief.ready", "proposal.approved", "proposal.accepted")
    outputs_ar = "عرض سعر (مسودة ← معتمد ← مُرسل ← مقبول) + إنشاء المشروع عند القبول"
    challenge_phrase_ar = "تقديم خدماتها عن بُعد وتخفض التكلفة"
    kpi_ar = "زمن إعداد عرض السعر من استلام الطلب"

    # ------------------------------------------------------------------ pricing
    @staticmethod
    def estimate_bua(brief: dict, cfg: dict) -> float:
        land = float(brief.get("land_area_m2") or 0)
        if brief.get("project_type") in ("interior", "renovation"):
            return round(land)
        floors = int(brief.get("floors") or 1)
        footprint = land * cfg["coverage_factor"]
        bua = footprint * floors + (footprint * cfg["annex_factor"] if brief.get("has_annex") else 0)
        return round(bua)

    def price(self, brief: dict) -> dict:
        cfg = load_config("price_list")
        ptype = brief.get("project_type") or "villa"
        mult = float(cfg["type_multipliers"].get(ptype, 1.0))
        bua = self.estimate_bua(brief, cfg)
        land = float(brief.get("land_area_m2") or 0)
        lines = []
        for code in brief.get("services") or []:
            svc = cfg["services"].get(code)
            if not svc:
                continue
            basis, rate = svc["basis"], float(svc["rate"])
            if basis == "per_m2":
                qty, m, basis_ar = bua, mult, f"{fmt_num(bua)} م² × {fmt_num(rate)} ريال × {mult:.2f}"
            elif basis == "per_m2_land":
                qty, m, basis_ar = land, 1.0, f"{fmt_num(land)} م² من الأرض × {fmt_num(rate)} ريال"
            elif basis == "per_month":
                months = int(svc.get("months_by_type", {}).get(ptype, svc.get("months_default", 12)))
                qty, m, basis_ar = months, 1.0, f"{months} شهر × {fmt_num(rate)} ريال"
            else:
                qty, m, basis_ar = 1, 1.0, "مبلغ مقطوع"
            amount = float(round(qty * rate * m))
            if amount < svc["min_fee"]:
                amount = float(svc["min_fee"])
                basis_ar += " (الحد الأدنى للأتعاب)"
            lines.append({"service_code": code, "name_ar": labels.SERVICE[code], "basis_ar": basis_ar, "qty": qty,
                          "unit_ar": svc["unit_ar"], "rate": rate, "multiplier": m, "amount": amount})
        subtotal = round(sum(l["amount"] for l in lines), 2)
        vat_rate = float(cfg["vat_rate"])
        vat = round(subtotal * vat_rate, 2)
        total = round(subtotal + vat, 2)
        milestones, allocated = [], 0.0
        for i, ms in enumerate(cfg["milestones"]):
            amt = round(total * ms["pct"] / 100.0, 2) if i < len(cfg["milestones"]) - 1 else round(total - allocated, 2)
            allocated += amt
            milestones.append({"name_ar": ms["name_ar"], "pct": ms["pct"], "amount": amt, "trigger_ar": ms["trigger_ar"]})
        return {"bua_m2": bua, "lines": lines, "subtotal": subtotal, "vat_rate": vat_rate, "vat": vat, "total": total,
                "milestones": milestones, "validity_days": int(cfg["validity_days"]),
                "exclusions": cfg["exclusions_ar"], "assumptions": cfg["assumptions_ar"]}

    # ------------------------------------------------------------------ operations
    def op_draft(self, request_id: int) -> StepResult:
        req = self.db.get("requests", request_id)
        if not req:
            raise DomainError("not_found", "الطلب غير موجود", "Request not found", 404)
        brief = loads(req["brief_json"], {})
        if req.get("proposal_id"):
            existing = self.db.get("proposals", req["proposal_id"])
            if existing and existing["status"] in ("draft", "approved", "sent", "accepted"):
                return StepResult(output={"proposal_id": existing["id"], "reused": True},
                                  input_summary=f"طلب #{request_id}", output_summary=f"العرض {existing['code']} موجود مسبقًا")
        p = self.price(brief)
        year = clock.today().year
        seq = (self.db.scalar("SELECT COUNT(*) FROM proposals") or 0) + 1
        code = f"PR-{year}-{seq:03d}"
        ptype = labels.PROJECT_TYPE.get(brief.get("project_type"), "مشروع")
        where = brief.get("city") or ""
        if brief.get("district"):
            where += f" – حي {brief['district']}"
        title = f"عرض خدمات هندسية: {ptype}" + (f" في {where}" if where else "")
        now = clock.now_iso()
        pid = self.db.insert("proposals", {
            "code": code, "request_id": request_id, "client_id": req["client_id"], "project_id": None,
            "status": "draft", "title_ar": title, "brief_json": brief, "bua_m2": p["bua_m2"],
            "lines_json": p["lines"], "subtotal": p["subtotal"], "vat_rate": p["vat_rate"], "vat": p["vat"],
            "total": p["total"], "milestones_json": p["milestones"], "validity_days": p["validity_days"],
            "valid_until": (clock.today() + timedelta(days=p["validity_days"])).isoformat(),
            "exclusions_json": p["exclusions"], "assumptions_json": p["assumptions"],
            "history_json": [{"status": "draft", "at": now, "by": None}], "created_at": now,
        })
        self.db.update("requests", request_id, {"status": "proposal_draft", "proposal_id": pid})
        return StepResult(
            output={"proposal_id": pid, "code": code, "total": p["total"], "lines": len(p["lines"])},
            input_summary=f"طلب #{request_id}: {', '.join(brief.get('services_labels_ar') or [])}",
            output_summary=f"{code} · البنود: {len(p['lines'])} · الإجمالي {fmt_num(p['total'])} ريال شامل الضريبة — بانتظار اعتماد المدير",
            input={"request_id": request_id},
        )

    def _history(self, prop: dict, status: str, by: dict | None) -> list:
        hist = loads(prop["history_json"], []) or []
        hist.append({"status": status, "at": clock.now_iso(), "by": by["id"] if by else None})
        return hist

    def op_approve(self, proposal_id: int, manager: dict) -> StepResult:
        prop = self.db.get("proposals", proposal_id)
        if not prop:
            raise DomainError("not_found", "العرض غير موجود", "Proposal not found", 404)
        if prop["status"] != "draft":
            raise DomainError("invalid_state", "يمكن اعتماد المسودات فقط", "Only draft proposals can be approved", 409)
        now = clock.now_iso()
        hist = self._history(prop, "approved", manager)
        prop["history_json"] = dumps(hist)
        hist = self._history(prop, "sent", manager)
        self.db.update("proposals", proposal_id, {
            "status": "sent", "approved_by": manager["id"], "approved_at": now, "sent_at": now, "history_json": hist})
        if prop.get("request_id"):
            self.db.update("requests", prop["request_id"], {"status": "proposal_sent"})
            self.db.insert("messages", {
                "request_id": prop["request_id"], "sender": "agent", "agent": self.key, "ts": clock.now_iso(),
                "text": f"اعتمد مدير المكتب عرض السعر {prop['code']} بقيمة {fmt_num(prop['total'])} ريال شاملة الضريبة. "
                        f"يمكنك مراجعته وقبوله من بوابة العملاء، وهو ساري حتى {clock.ar_date(prop['valid_until'])}."})
        return StepResult(
            output={"proposal_id": proposal_id, "status": "sent"},
            input_summary=f"{prop['code']} · اعتماد {manager['name_ar']}",
            output_summary="اعتُمد العرض وأُرسل إلى العميل عبر البوابة",
            input={"proposal_id": proposal_id},
        )

    @staticmethod
    def default_params(brief: dict, cfg: dict) -> dict:
        floors = int(brief.get("floors") or 1)
        ptype = brief.get("project_type") or "villa"
        units = {"residential_building": max(2, floors * 2), "mixed_use": max(2, floors * 2)}.get(ptype, 1)
        height = round(floors * 3.6 + (3.0 if brief.get("has_annex") else 0), 1)
        return {"coverage_ratio": cfg["coverage_factor"], "setback_front_m": 4.0, "setback_side_m": 2.0,
                "setback_rear_m": 2.0, "height_m": height, "floors": floors, "parking_spaces": max(units, 2),
                "units": units}

    def op_accept(self, proposal_id: int, client: dict) -> StepResult:
        prop = self.db.get("proposals", proposal_id)
        if not prop:
            raise DomainError("not_found", "العرض غير موجود", "Proposal not found", 404)
        if prop["status"] != "sent":
            raise DomainError("invalid_state", "يمكن قبول العروض المرسلة فقط", "Only sent proposals can be accepted", 409)
        brief = loads(prop["brief_json"], {})
        cfg = load_config("price_list")
        office = repo.office()
        year = clock.today().year
        seq = (self.db.scalar("SELECT MAX(CAST(substr(code, -3) AS INTEGER)) FROM projects") or 0) + 1
        code = f"{office['code']}-{year}-{seq:03d}"
        ptype = brief.get("project_type") or "villa"
        cname = repo.client_name(self.db, prop["client_id"])
        short_client = cname.split(" (")[0]
        family = short_client.split()[-1] if short_client else ""
        name_ar = f"{labels.PROJECT_TYPE[ptype]} {family}".strip()
        if brief.get("district"):
            name_ar += f" — حي {brief['district']}"
        elif brief.get("city"):
            name_ar += f" — {brief['city']}"
        now = clock.now_iso()
        project_id = self.db.insert("projects", {
            "code": code, "name_ar": name_ar, "name_en": f"{ptype.replace('_', ' ').title()} project {code}",
            "client_id": prop["client_id"], "type": ptype, "city": brief.get("city") or "", "district": brief.get("district"),
            "status": "planning", "start_date": None, "end_date": None,
            "land_area_m2": brief.get("land_area_m2") or 0, "floors": int(brief.get("floors") or 1),
            "bua_m2": prop["bua_m2"], "description_ar": f"مشروع أُنشئ تلقائيًا من العرض {prop['code']} بعد قبول العميل.",
            "params_json": self.default_params(brief, cfg), "services_json": brief.get("services") or [],
            "proposal_id": proposal_id, "created_at": now,
        })
        hist = self._history(prop, "accepted", client)
        self.db.update("proposals", proposal_id, {"status": "accepted", "accepted_at": now, "project_id": project_id,
                                                   "history_json": hist})
        if prop.get("request_id"):
            self.db.update("requests", prop["request_id"], {"status": "accepted"})
            self.db.insert("messages", {
                "request_id": prop["request_id"], "sender": "agent", "agent": self.key, "ts": clock.now_iso(),
                "text": f"شكرًا لثقتك. أُنشئ مشروعك برقم {code}، ويجري الآن إعداد الجدول الزمني وتشكيل فريق العمل."})
        return StepResult(
            output={"proposal_id": proposal_id, "project_id": project_id, "project_code": code},
            input_summary=f"{prop['code']} · قبول {client['name_ar']}",
            output_summary=f"قُبل العرض وأُنشئ المشروع {code}",
            input={"proposal_id": proposal_id},
        )

    # ------------------------------------------------------------------ self-test
    def self_test(self) -> list[Check]:
        checks = []
        brief = {"project_type": "villa", "city": "الرياض", "land_area_m2": 625, "floors": 2, "has_annex": False,
                 "services": ["arch_design", "struct_design", "permit"]}
        p = self.price(brief)
        checks.append(self.check("Built-up area estimate", "تقدير مسطحات البناء", p["bua_m2"] == 750, f"{p['bua_m2']} م²"))
        arch = next(l for l in p["lines"] if l["service_code"] == "arch_design")
        checks.append(self.check("Per-m² fee line", "بند أتعاب بالمتر المربع", arch["amount"] == 26250, f"{arch['basis_ar']} = {arch['amount']}"))
        checks.append(self.check("Subtotal equals sum of lines", "المجموع يساوي مجموع البنود",
                                 abs(p["subtotal"] - sum(l["amount"] for l in p["lines"])) < 0.01, str(p["subtotal"])))
        checks.append(self.check("VAT 15%", "ضريبة القيمة المضافة 15%", abs(p["vat"] - p["subtotal"] * 0.15) < 0.01, str(p["vat"])))
        checks.append(self.check("Milestones add up to 100% of total", "الدفعات تساوي الإجمالي",
                                 sum(m["pct"] for m in p["milestones"]) == 100 and abs(sum(m["amount"] for m in p["milestones"]) - p["total"]) < 0.01,
                                 " + ".join(str(m["pct"]) for m in p["milestones"])))
        small = self.price({"project_type": "renovation", "land_area_m2": 80, "services": ["arch_design"]})
        checks.append(self.check("Minimum fee applied to small jobs", "تطبيق الحد الأدنى للأتعاب", small["lines"][0]["amount"] == 15000, small["lines"][0]["basis_ar"]))
        # full lifecycle on the seeded database: draft -> approve -> accept
        req = self.db.one("SELECT * FROM requests WHERE status = 'brief_ready' ORDER BY id LIMIT 1")
        if req is None:
            client = repo.default_user(self.db, "client")
            rid = self.db.insert("requests", {"client_id": client["client_id"], "status": "brief_ready", "created_at": clock.now_iso(),
                                              "original_text": "self-test", "brief_json": {**brief, "services_labels_ar": []},
                                              "missing_json": [], "questions_json": [], "complete": True})
        else:
            rid = req["id"]
        d = self.op_draft(rid)
        manager = repo.default_user(self.db, "manager")
        client_user = self.db.one("SELECT * FROM users WHERE role='client' AND client_id = (SELECT client_id FROM requests WHERE id=?)", (rid,))
        blocked = False
        try:
            self.op_accept(d.output["proposal_id"], client_user)
        except DomainError:
            blocked = True
        checks.append(self.check("Client cannot accept before manager approval", "لا قبول قبل اعتماد المدير", blocked, "invalid_state"))
        self.op_approve(d.output["proposal_id"], manager)
        acc = self.op_accept(d.output["proposal_id"], client_user)
        prop = self.db.get("proposals", d.output["proposal_id"])
        checks.append(self.check("Draft → approved → sent → accepted creates a project", "دورة العرض كاملة وإنشاء المشروع",
                                 prop["status"] == "accepted" and acc.output["project_id"] is not None,
                                 acc.output.get("project_code", "")))
        return checks
