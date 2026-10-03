"""Security & Access agent (وكيل الأمن والصلاحيات).

Authorises every action with role-based access control, writes the audit log, detects
unusual behaviour and raises alerts. Every mutating API call passes through it first.
"""
from __future__ import annotations

from datetime import timedelta

from .. import clock, labels, repo
from .base import BaseAgent, Check, StepResult

# action -> (manager, engineer, client)
PERMISSIONS: dict[str, tuple[str, str, str]] = {
    "portal.request.create": ("deny", "deny", "allow"),
    "portal.request.view": ("allow", "deny", "own"),
    "portal.request.message": ("deny", "deny", "own"),
    "proposal.view": ("allow", "deny", "own"),
    "proposal.approve": ("allow", "deny", "deny"),
    "proposal.accept": ("deny", "deny", "own"),
    "project.view": ("allow", "assigned", "own"),
    "project.edit": ("allow", "assigned", "deny"),
    "task.update": ("allow", "assigned", "deny"),
    "team.view": ("allow", "allow", "deny"),
    "team.rebalance": ("allow", "deny", "deny"),
    "file.view": ("allow", "assigned", "published"),
    "file.upload": ("allow", "assigned", "deny"),
    "file.state": ("allow", "assigned", "deny"),
    "file.download": ("allow", "assigned", "published"),
    "qa.run": ("allow", "assigned", "deny"),
    "qa.signoff": ("licensed", "licensed", "deny"),
    "report.create": ("allow", "assigned", "deny"),
    "client.question": ("allow", "deny", "own"),
    "dashboard.view": ("allow", "allow", "deny"),
    "agents.view": ("allow", "allow", "deny"),
    "scenario.run": ("allow", "deny", "deny"),
    "security.view": ("allow", "deny", "deny"),
    "security.manage": ("allow", "deny", "deny"),
    "compliance.view": ("allow", "allow", "deny"),
    "demo.reset": ("allow", "deny", "deny"),
}
ROLE_INDEX = {"manager": 0, "engineer": 1, "client": 2}

LEGEND_AR = {
    "allow": "مسموح",
    "deny": "غير مسموح",
    "assigned": "المشاريع المسندة إليه فقط",
    "own": "طلباته ومشاريعه فقط",
    "published": "الملفات المنشورة من مشاريعه فقط",
    "licensed": "المهندس المرخّص فقط",
}

BURST_WINDOW_S = 60
BURST_COUNT = 5
DENIAL_WINDOW_MIN = 10
DENIAL_COUNT = 3


class SecurityAgent(BaseAgent):
    key = "security"
    order = 7
    name_ar = "وكيل الأمن والصلاحيات"
    name_en = "Security & Access"
    role_ar = "يتحقق من صلاحية كل عملية حسب الدور، ويسجّلها في سجل التدقيق، ويكشف السلوك غير المعتاد ويطلق التنبيهات."
    role_en = "Authorises every action (RBAC), writes the audit log, detects anomalies and raises alerts."
    triggers = ("*",)
    outputs_ar = "قرار السماح أو المنع + سجل تدقيق + تنبيهات أمنية"
    challenge_phrase_ar = "من خلال بيئة موحدة وآمنة"
    kpi_ar = "صفر وصول غير مصرّح به للملفات غير المعتمدة"

    # facts --------------------------------------------------------------
    def resolve(self, resource: str) -> dict:
        facts: dict = {"resource": resource, "type": "office", "id": None}
        if not resource or ":" not in resource:
            return facts
        rtype, _, rid = resource.partition(":")
        facts["type"] = rtype
        try:
            facts["id"] = int(rid)
        except ValueError:
            return facts
        db = self.db
        if rtype == "project":
            p = db.get("projects", facts["id"])
            if p:
                facts.update(project_id=p["id"], client_id=p["client_id"], project_code=p["code"])
        elif rtype == "document":
            d = db.get("documents", facts["id"])
            if d:
                p = db.get("projects", d["project_id"]) or {}
                facts.update(project_id=d["project_id"], client_id=p.get("client_id"), doc_state=d["state"],
                             doc_code=d["code"], project_code=p.get("code"))
        elif rtype == "proposal":
            pr = db.get("proposals", facts["id"])
            if pr:
                facts.update(client_id=pr["client_id"], proposal_status=pr["status"], project_id=pr["project_id"])
        elif rtype == "request":
            rq = db.get("requests", facts["id"])
            if rq:
                facts.update(client_id=rq["client_id"])
        elif rtype == "task":
            t = db.get("tasks", facts["id"])
            if t:
                p = db.get("projects", t["project_id"]) or {}
                facts.update(project_id=t["project_id"], assignee_id=t["assignee_id"], client_id=p.get("client_id"),
                             project_code=p.get("code"))
        elif rtype == "qa":
            q = db.get("qa_reports", facts["id"])
            if q:
                p = db.get("projects", q["project_id"]) or {}
                facts.update(project_id=q["project_id"], client_id=p.get("client_id"), project_code=p.get("code"))
        return facts

    # decision -----------------------------------------------------------
    def decide(self, actor: dict | None, action: str, facts: dict) -> tuple[str, str, str]:
        """Returns (decision, reason_code, reason_ar)."""
        if actor is None:
            return "deny", "unauthenticated", "مرفوض: يجب تحديد هوية المستخدم أولًا"
        if action not in PERMISSIONS:
            return "deny", "unknown_action", "مرفوض: عملية غير معروفة"
        role = actor["role"]
        if role not in ROLE_INDEX:
            return "deny", "unknown_role", "مرفوض: دور غير معروف"
        rule = PERMISSIONS[action][ROLE_INDEX[role]]
        role_label = labels.ROLE[role]
        if rule == "allow":
            return "allow", "role", f"مسموح: صلاحية {role_label}"
        if rule == "deny":
            return "deny", "role", f"مرفوض: هذه العملية غير متاحة لدور «{role_label}»"
        if rule == "licensed":
            if actor.get("is_licensed"):
                return "allow", "licensed", f"مسموح: مهندس مرخّص ({actor.get('license_no') or '—'})"
            return "deny", "unlicensed", "مرفوض: التوقيع مقصور على المهندسين المرخّصين"
        if facts.get("type") == "office":
            return "allow", "scoped", "مسموح: تُعرض البيانات المسموح بها لهذا الدور فقط"
        if rule == "assigned":
            if action == "task.update" and facts.get("assignee_id") is not None:
                if facts["assignee_id"] == actor["id"]:
                    return "allow", "assignee", "مسموح: المهندس هو المسؤول عن المهمة"
                return "deny", "not_assignee", "مرفوض: المهمة مسندة إلى مهندس آخر"
            pid = facts.get("project_id")
            if pid is not None and repo.is_member(self.db, pid, actor["id"]):
                return "allow", "assigned", "مسموح: المهندس مسند إلى المشروع"
            return "deny", "unassigned", "مرفوض: المهندس غير مسند إلى هذا المشروع"
        if rule in ("own", "published"):
            if facts.get("client_id") is None or facts.get("client_id") != actor.get("client_id"):
                return "deny", "other_client", "مرفوض: لا يمكن الوصول إلى بيانات عميل آخر"
            if action == "proposal.view" and facts.get("proposal_status") not in ("sent", "accepted", "rejected"):
                return "deny", "proposal_not_sent", "مرفوض: العرض لم يُعتمد ويُرسل بعد"
            if rule == "published" and facts.get("type") == "document" and facts.get("doc_state") != "PUBLISHED":
                return "deny", "client_unpublished", "مرفوض: يطّلع العميل على الملفات المنشورة فقط"
            return "allow", "owner", "مسموح: العميل مالك الطلب أو المشروع"
        return "deny", "rule", "مرفوض"

    # audit + anomalies ----------------------------------------------------
    def _audit(self, actor, action, resource, decision, reason_ar, run_id) -> int:
        return self.db.insert("audit", {
            "ts": clock.now_iso(), "actor_id": actor["id"] if actor else None, "action": action,
            "resource": resource, "decision": decision, "reason_ar": reason_ar, "run_id": run_id,
        })

    def _raise_alert(self, atype: str, severity: str, message_ar: str, actor, resource: str) -> dict:
        cutoff = (clock.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
        existing = self.db.one(
            "SELECT * FROM alerts WHERE type = ? AND actor_id IS ? AND resource = ? AND status = 'open' AND ts >= ?",
            (atype, actor["id"] if actor else None, resource, cutoff),
        )
        if existing:
            return existing
        aid = self.db.insert("alerts", {
            "ts": clock.now_iso(), "severity": severity, "type": atype, "message_ar": message_ar,
            "actor_id": actor["id"] if actor else None, "resource": resource, "status": "open",
        })
        return self.db.get("alerts", aid)

    def detect(self, actor, action, facts, decision, code) -> dict | None:
        if actor is None:
            return None
        name = actor["name_ar"]
        alert = None
        if decision == "deny":
            if actor["role"] == "client" and code == "client_unpublished":
                alert = self._raise_alert(
                    "client_wip_request", "high",
                    f"حاول العميل {name} الوصول إلى ملف غير منشور ({clock.ltr(facts.get('doc_code') or facts['resource'])}) — تم المنع",
                    actor, facts["resource"])
            elif actor["role"] == "engineer" and code == "unassigned":
                alert = self._raise_alert(
                    "unassigned_access", "medium",
                    f"حاول {name} الوصول إلى مشروع غير مسند إليه ({clock.ltr(facts.get('project_code') or facts['resource'])}) — تم المنع",
                    actor, f"project:{facts.get('project_id')}")
            cutoff = (clock.now() - timedelta(minutes=DENIAL_WINDOW_MIN)).isoformat(timespec="seconds")
            n = self.db.scalar(
                "SELECT COUNT(*) FROM audit WHERE actor_id = ? AND decision = 'deny' AND ts >= ?", (actor["id"], cutoff))
            if n and n >= DENIAL_COUNT:
                alert = self._raise_alert(
                    "repeated_denials", "high",
                    f"{n} محاولات مرفوضة خلال {DENIAL_WINDOW_MIN} دقائق من {name}", actor, f"user:{actor['id']}")
        elif action == "file.download":
            cutoff = (clock.now() - timedelta(seconds=BURST_WINDOW_S)).isoformat(timespec="seconds")
            n = self.db.scalar(
                "SELECT COUNT(*) FROM audit WHERE actor_id = ? AND action = 'file.download' AND decision = 'allow' AND ts >= ?",
                (actor["id"], cutoff))
            if n and n >= BURST_COUNT:
                alert = self._raise_alert(
                    "burst_download", "high",
                    f"تنزيل {n} ملفات خلال دقيقة واحدة من {name} — نمط غير معتاد", actor, f"user:{actor['id']}")
        return alert

    def evaluate(self, actor, action: str, resource: str, run_id: str | None = None, audit: bool = True) -> dict:
        facts = self.resolve(resource)
        decision, code, reason = self.decide(actor, action, facts)
        audit_id = None
        if audit or decision == "deny":
            audit_id = self._audit(actor, action, resource, decision, reason, run_id)
        alert = self.detect(actor, action, facts, decision, code) if audit_id else None
        return {"decision": decision, "reason_code": code, "reason_ar": reason, "audit_id": audit_id,
                "alert_id": alert["id"] if alert else None, "facts": facts}

    # operations -----------------------------------------------------------
    def op_authorize(self, actor, action: str, resource: str, run_id: str | None = None) -> StepResult:
        res = self.evaluate(actor, action, resource, run_id=run_id, audit=True)
        who = f"{actor['name_ar']} ({labels.ROLE.get(actor['role'])})" if actor else "مستخدم مجهول"
        out = {k: v for k, v in res.items() if k != "facts"}
        summary = ("✔ " if res["decision"] == "allow" else "✖ ") + res["reason_ar"]
        if res["alert_id"]:
            summary += " · أُطلق تنبيه أمني"
        return StepResult(
            output=out,
            input_summary=f"{who} · {labels.ACTIONS.get(action, action)} · {resource}",
            output_summary=summary,
            status="ok" if res["decision"] == "allow" else "denied",
            input={"actor_id": actor["id"] if actor else None, "action": action, "resource": resource},
        )

    def op_ack(self, alert_id: int, actor, run_id: str | None = None) -> StepResult:
        from .base import DomainError

        alert = self.db.get("alerts", alert_id)
        if not alert:
            raise DomainError("not_found", "التنبيه غير موجود", "Alert not found", 404)
        self.db.update("alerts", alert_id, {"status": "acknowledged"})
        self._audit(actor, "security.manage", f"alert:{alert_id}", "allow", "معالجة تنبيه أمني", run_id)
        return StepResult(
            output={"alert_id": alert_id, "status": "acknowledged"},
            input_summary=f"تنبيه #{alert_id}: {labels.ALERT_TYPE.get(alert['type'])}",
            output_summary="أُغلق التنبيه وسُجّلت المعالجة في سجل التدقيق",
            input={"alert_id": alert_id},
        )

    def op_simulate(self, kind: str, actor, run_id: str | None = None) -> StepResult:
        from .base import DomainError

        db = self.db
        alert_id = None
        if kind == "client_wip":
            client = repo.default_user(db, "client")
            doc = db.one(
                "SELECT d.* FROM documents d JOIN projects p ON p.id = d.project_id "
                "WHERE p.client_id = ? AND d.state != 'PUBLISHED' AND d.superseded_by IS NULL ORDER BY d.id LIMIT 1",
                (client["client_id"],))
            if not doc:
                raise DomainError("invalid_state", "لا يوجد ملف غير منشور للمحاكاة", "No unpublished file to simulate", 409)
            res = self.evaluate(client, "file.download", f"document:{doc['id']}", run_id=run_id)
            attempt = f"محاكاة: العميل {client['name_ar']} يحاول تنزيل «{doc['title']}» وهو في حالة {labels.CDE_STATE[doc['state']]}"
            decision, alert_id, sim_actor = res["decision"], res["alert_id"], client
        elif kind == "unassigned_access":
            pair = db.one(
                "SELECT u.id AS uid, p.id AS pid, p.code FROM users u CROSS JOIN projects p "
                "WHERE u.role = 'engineer' AND NOT EXISTS (SELECT 1 FROM project_members m WHERE m.user_id = u.id AND m.project_id = p.id) "
                "ORDER BY p.id, u.id LIMIT 1")
            if not pair:
                raise DomainError("invalid_state", "لا توجد حالة مناسبة للمحاكاة", "No unassigned pair to simulate", 409)
            eng = db.get("users", pair["uid"])
            res = self.evaluate(eng, "project.view", f"project:{pair['pid']}", run_id=run_id)
            attempt = f"محاكاة: {eng['name_ar']} يحاول فتح المشروع {pair['code']} وهو غير مسند إليه"
            decision, alert_id, sim_actor = res["decision"], res["alert_id"], eng
        elif kind == "burst_download":
            row = db.one(
                "SELECT m.user_id, d.project_id, COUNT(*) AS n FROM documents d JOIN project_members m ON m.project_id = d.project_id "
                "JOIN users u ON u.id = m.user_id WHERE u.role = 'engineer' GROUP BY m.user_id, d.project_id ORDER BY n DESC LIMIT 1")
            if not row:
                raise DomainError("invalid_state", "لا توجد ملفات كافية للمحاكاة", "Not enough files to simulate", 409)
            eng = db.get("users", row["user_id"])
            docs = db.all("SELECT id FROM documents WHERE project_id = ? ORDER BY id", (row["project_id"],))
            decision = "allow"
            for i in range(BURST_COUNT + 1):
                d = docs[i % len(docs)]
                res = self.evaluate(eng, "file.download", f"document:{d['id']}", run_id=run_id)
                alert_id = res["alert_id"] or alert_id
            attempt = f"محاكاة: {eng['name_ar']} ينزّل {BURST_COUNT + 1} ملفات خلال ثوانٍ"
            sim_actor = eng
        else:
            raise DomainError("validation_error", "نوع المحاكاة غير معروف", "Unknown simulation kind", 422)
        status = "denied" if decision == "deny" else "ok"
        summary = ("✖ منع الوصول" if decision == "deny" else "✔ سُمح بالعملية") + (" · أُطلق تنبيه" if alert_id else "")
        return StepResult(
            output={"attempt_ar": attempt, "decision": decision, "alert_id": alert_id, "simulated_actor_id": sim_actor["id"]},
            input_summary=attempt,
            output_summary=summary,
            status=status,
            input={"kind": kind},
        )

    # self-test --------------------------------------------------------------
    def self_test(self) -> list[Check]:
        db = self.db
        checks: list[Check] = []
        eng_pair = db.one(
            "SELECT u.id AS uid, p.id AS pid FROM users u CROSS JOIN projects p WHERE u.role='engineer' AND NOT EXISTS "
            "(SELECT 1 FROM project_members m WHERE m.user_id=u.id AND m.project_id=p.id) LIMIT 1")
        eng = db.get("users", eng_pair["uid"])
        d1 = self.evaluate(eng, "project.view", f"project:{eng_pair['pid']}")
        checks.append(self.check("Unassigned engineer is denied", "منع مهندس غير مسند من فتح مشروع",
                                 d1["decision"] == "deny" and d1["reason_code"] == "unassigned", d1["reason_ar"]))
        mem = db.one("SELECT user_id, project_id FROM project_members m JOIN users u ON u.id=m.user_id WHERE u.role='engineer' LIMIT 1")
        d2 = self.evaluate(db.get("users", mem["user_id"]), "project.view", f"project:{mem['project_id']}")
        checks.append(self.check("Assigned engineer is allowed", "السماح لمهندس مسند إلى المشروع", d2["decision"] == "allow", d2["reason_ar"]))
        client = repo.default_user(db, "client")
        pub = db.one("SELECT d.id FROM documents d JOIN projects p ON p.id=d.project_id WHERE p.client_id=? AND d.state='PUBLISHED' LIMIT 1", (client["client_id"],))
        wip = db.one("SELECT d.id FROM documents d JOIN projects p ON p.id=d.project_id WHERE p.client_id=? AND d.state!='PUBLISHED' LIMIT 1", (client["client_id"],))
        d3 = self.evaluate(client, "file.download", f"document:{pub['id']}")
        d4 = self.evaluate(client, "file.download", f"document:{wip['id']}")
        checks.append(self.check("Client can download own published file", "العميل ينزّل ملفًا منشورًا من مشروعه", d3["decision"] == "allow", d3["reason_ar"]))
        checks.append(self.check("Client is blocked from WIP files and an alert is raised", "منع العميل من ملف غير منشور مع تنبيه",
                                 d4["decision"] == "deny" and d4["alert_id"] is not None, d4["reason_ar"]))
        other = db.one("SELECT id FROM projects WHERE client_id != ? LIMIT 1", (client["client_id"],))
        d5 = self.evaluate(client, "project.view", f"project:{other['id']}")
        checks.append(self.check("Client cannot open another client's project", "منع العميل من بيانات عميل آخر", d5["reason_code"] == "other_client", d5["reason_ar"]))
        unlicensed = db.one("SELECT * FROM users WHERE role='engineer' AND is_licensed=0 LIMIT 1")
        licensed = db.one("SELECT * FROM users WHERE role='engineer' AND is_licensed=1 LIMIT 1")
        d6 = self.evaluate(unlicensed, "qa.signoff", "qa:1")
        d7 = self.evaluate(licensed, "qa.signoff", "qa:1")
        checks.append(self.check("Only licensed engineers can sign off QA", "التوقيع مقصور على المرخّصين",
                                 d6["decision"] == "deny" and d7["decision"] == "allow", f"{d6['reason_ar']} / {d7['reason_ar']}"))
        docs = db.all("SELECT id FROM documents WHERE project_id = ? ORDER BY id", (mem["project_id"],))
        member = db.get("users", mem["user_id"])
        last = None
        for i in range(BURST_COUNT + 1):
            last = self.evaluate(member, "file.download", f"document:{docs[i % len(docs)]['id']}")
        alert = db.get("alerts", last["alert_id"]) if last and last["alert_id"] else None
        checks.append(self.check("Burst downloads raise an alert", "كشف التنزيل الجماعي وإطلاق تنبيه",
                                 bool(alert and alert["type"] == "burst_download"), alert["message_ar"] if alert else "no alert"))
        n_audit = db.scalar("SELECT COUNT(*) FROM audit")
        checks.append(self.check("Every decision is written to the audit log", "تسجيل كل قرار في سجل التدقيق", n_audit >= 7 + BURST_COUNT, f"{n_audit} entries"))
        return checks
