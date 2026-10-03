"""Unit tests per agent (normal cases and edge cases)."""
import pytest

from mihwar.agents.base import DomainError
from mihwar.agents.compliance import evaluate_rules
from mihwar.agents.documents import CODE_RE, classify
from mihwar.agents.intake import IntakeAgent, missing_fields, norm
from mihwar.agents.planner import build_plan
from mihwar.agents.reporting import detect_intent, progress_of
from mihwar.agents.team import task_week_hours
from mihwar import clock
from mihwar.selftest import run_agent_self_test

from conftest import CLIENT1, CLIENT2, FAHAD, MANAGER, NOURA, SARAH

AGENTS = ["orchestrator", "intake", "proposal", "planner", "team", "documents", "compliance", "security", "reporting"]


@pytest.mark.parametrize("key", AGENTS)
def test_every_agent_self_test_passes(settings, key):
    r = run_agent_self_test(settings, key)
    failed = [c for c in r["checks"] if not c["passed"]]
    assert r["passed"], failed
    assert len(r["checks"]) >= 5


# ------------------------------------------------------------------ intake
def test_intake_normalises_arabic_indic_digits_and_letters():
    assert norm("٦٢٥ م٢") == "625 م2"
    assert norm("الطائف") == "الطايف"


@pytest.mark.parametrize("text,expected", [
    ("أبي أبني عمارة ٣ أدوار بجدة على أرض ٨٠٠ متر، تصميم كامل", {"project_type": "residential_building", "city": "جدة", "floors": 3, "land_area_m2": 800}),
    ("فلة في الدمام مساحتها 450 دورين", {"project_type": "villa", "city": "الدمام", "floors": 2, "land_area_m2": 450}),
    ("نحتاج مستودع في الخبر مساحة الأرض 3000 م2 دور واحد", {"project_type": "warehouse", "city": "الخبر", "floors": 1, "land_area_m2": 3000}),
    ("Villa in Taif, G+1, 700 sqm, architectural and structural design", {"project_type": "villa", "city": "الطائف", "floors": 2, "land_area_m2": 700}),
])
def test_intake_extraction_variants(ctx, text, expected):
    b = ctx.agents["intake"].extract(text)
    for k, v in expected.items():
        assert b[k] == v, (k, b[k], v)


def test_intake_does_not_confuse_words(ctx):
    b = ctx.agents["intake"].extract("أبغى تصميم مبنى في جامعة الملك سعود")  # جامعة is not a mosque
    assert b["project_type"] != "mosque"
    b2 = ctx.agents["intake"].extract("مطعم سمكة في الرياض")  # سمكة must not match مكة
    assert b2["city"] == "الرياض"


def test_intake_missing_fields_and_questions(ctx):
    b = ctx.agents["intake"].extract("أبي أصمم بيت")
    miss = missing_fields(b)
    assert {"city", "land_area_m2", "services"} <= set(miss)
    reply, questions = IntakeAgent.compose_reply(b, miss)
    assert len(questions) == len(miss) and "أحتاج" in reply


def test_intake_budget_and_timeline(ctx):
    b = ctx.agents["intake"].extract("فيلا في الرياض 600 متر مربع دورين تصميم معماري، الميزانية ١٫٥ مليون ريال خلال شهرين")
    assert b["budget_sar"] == 1_500_000
    assert b["timeline_months"] == 2


def test_intake_rejects_empty_text(ctx):
    with pytest.raises(DomainError):
        ctx.agents["intake"].op_submit(1, "  ")


# ------------------------------------------------------------------ proposal
def test_proposal_pricing_consistency(ctx):
    p = ctx.agents["proposal"].price({"project_type": "residential_building", "land_area_m2": 900, "floors": 4,
                                      "services": ["arch_design", "struct_design", "mep_design", "supervision"]})
    assert p["bua_m2"] == 2160
    assert abs(p["total"] - p["subtotal"] * 1.15) < 0.02
    assert abs(sum(m["amount"] for m in p["milestones"]) - p["total"]) < 0.01
    sup = next(l for l in p["lines"] if l["service_code"] == "supervision")
    assert sup["qty"] == 16  # months for a residential building in the editable price list


def test_proposal_approve_twice_is_refused(ctx):
    db = ctx.db
    prop = db.one("SELECT * FROM proposals WHERE status = 'draft' LIMIT 1")
    ctx.agents["proposal"].op_approve(prop["id"], db.get("users", MANAGER))
    with pytest.raises(DomainError) as e:
        ctx.agents["proposal"].op_approve(prop["id"], db.get("users", MANAGER))
    assert e.value.code == "invalid_state"


# ------------------------------------------------------------------ planner
def test_planner_respects_weekend_and_dependencies():
    plan = build_plan(["arch_design", "struct_design", "mep_design", "permit", "supervision"], 2000, clock.today())
    by = {t["key"]: t for t in plan}
    for t in plan:
        assert clock.is_working_day(t["start_date"]) and clock.is_working_day(t["end_date"])
        for d in t["deps"]:
            assert t["start_date"] > by[d]["end_date"]
    assert by["supervision"]["start_date"] > by["permit_ok"]["end_date"]


def test_planner_interior_only_project():
    plan = build_plan(["interior"], 450, clock.today())
    keys = [t["key"] for t in plan]
    assert "interior" in keys and "concept" not in keys and "handover" in keys


# ------------------------------------------------------------------ team
def test_team_detects_seeded_overload_and_suggests(ctx):
    view = ctx.agents["team"].view()
    sarah = next(e for e in view["engineers"] if e["id"] == SARAH)
    assert sarah["status"] == "overload"
    assert any(s["from"]["id"] == SARAH and s["to"]["id"] == FAHAD for s in view["suggestions"])


def test_team_rebalance_rejects_discipline_mismatch(ctx):
    t = ctx.db.one("SELECT * FROM tasks WHERE discipline = 'architectural' AND is_milestone = 0 LIMIT 1")
    with pytest.raises(DomainError):
        ctx.agents["team"].op_rebalance(t["id"], NOURA)  # structural engineer


def test_team_hours_distribution_for_overdue_task():
    today = clock.today()
    t = {"status": "in_progress", "is_milestone": 0, "hours": 20, "progress": 50,
         "start": (today.replace(day=1)).isoformat(), "end": clock.subtract_working_days(today, 3).isoformat()}
    spread = task_week_hours(t, today)
    assert abs(sum(spread.values()) - 10) < 0.01 and list(spread) == [clock.week_start(today)]


# ------------------------------------------------------------------ documents
@pytest.mark.parametrize("name,disc,typ", [
    ("A-101 Ground Floor Plan.dwg", "architectural", "DR"),
    ("مخطط الأساسات rev3.pdf", "structural", "DR"),
    ("تقرير فحص التربة.pdf", "general", "RP"),
    ("BOQ - Villa.xlsx", "general", "SH"),
    ("Model.ifc", "general", "M3"),
    ("واجهة رئيسية منظور.jpg", "architectural", "VS"),
])
def test_documents_classification(name, disc, typ):
    c = classify(name)
    assert (c["discipline"], c["doc_type"]) == (disc, typ)


def test_documents_rejects_bad_extension_and_empty(ctx, pid):
    agent, user = ctx.agents["documents"], ctx.db.get("users", SARAH)
    with pytest.raises(DomainError):
        agent.op_register(pid["MST-2026-007"], "virus.exe", b"x", user)
    with pytest.raises(DomainError):
        agent.op_register(pid["MST-2026-007"], "plan.pdf", b"", user)


def test_documents_publish_creates_c01_and_transmittal(ctx, pid):
    db = ctx.db
    agent = ctx.agents["documents"]
    r = agent.op_register(pid["MST-2026-007"], "Landscape Plan.pdf", b"%PDF-1.4 landscape", db.get("users", SARAH))
    did = r.output["document_id"]
    assert CODE_RE.match(r.output["code"])
    agent.op_transition(did, "SHARED", db.get("users", SARAH))
    db.update("documents", did, {"qa_status": "signed_off"})
    out = agent.op_transition(did, "PUBLISHED", db.get("users", SARAH))
    doc = db.get("documents", did)
    assert doc["revision"] == "C01" and out.output["transmittal_id"]


# ------------------------------------------------------------------ compliance
def test_compliance_rules_violations():
    issues, total, passed = evaluate_rules("villa", {"coverage_ratio": 0.7, "setback_front_m": 2, "setback_side_m": 2,
                                                     "setback_rear_m": 2, "height_m": 14, "floors": 4, "parking_spaces": 0, "units": 1})
    ids = {i["rule_id"] for i in issues}
    assert {"Z-01", "Z-03", "Z-06", "Z-07", "Z-08"} <= ids and passed == total - len(issues)


def test_compliance_signoff_blocked_on_high_issue(ctx, pid):
    rep = ctx.agents["compliance"].op_check(pid["MST-2026-009"])  # seeded coverage 65% > 60%
    assert rep.output["high"] >= 1
    with pytest.raises(DomainError):
        ctx.agents["compliance"].op_signoff(rep.output["qa_report_id"], ctx.db.get("users", NOURA))


# ------------------------------------------------------------------ security
def test_security_matrix(ctx, pid):
    sec, db = ctx.agents["security"], ctx.db
    c1, c2 = db.get("users", CLIENT1), db.get("users", CLIENT2)
    assert sec.decide(c1, "proposal.approve", {"type": "office"})[0] == "deny"
    assert sec.decide(db.get("users", MANAGER), "proposal.approve", {"type": "office"})[0] == "allow"
    facts = sec.resolve(f"project:{pid['MST-2026-007']}")
    assert sec.decide(c1, "project.view", facts)[0] == "allow"
    assert sec.decide(c2, "project.view", facts)[1] == "other_client"
    assert sec.decide(None, "project.view", facts)[1] == "unauthenticated"


def test_security_repeated_denials_alert(ctx, pid):
    sec, db = ctx.agents["security"], ctx.db
    c2 = db.get("users", CLIENT2)
    last = None
    for _ in range(3):
        last = sec.evaluate(c2, "project.view", f"project:{pid['MST-2026-007']}")
    alert = db.get("alerts", last["alert_id"])
    assert alert and alert["type"] == "repeated_denials"


# ------------------------------------------------------------------ reporting
def test_reporting_intents_and_progress():
    assert detect_intent("متى ينتهي المشروع؟") == "schedule"
    assert detect_intent("ابي اشوف المخطط الأخير") == "files"
    assert detect_intent("Who is the engineer on my project?") == "team"
    assert progress_of([]) == 0


def test_reporting_payment_answer_is_honest(ctx, pid):
    ans = ctx.agents["reporting"].op_answer(pid["MST-2026-007"], "كم باقي من الدفعات؟")
    assert ans.output["intent"] == "payment" and ans.output["escalated"]
    assert "غير مربوطة" in ans.output["text_ar"]
