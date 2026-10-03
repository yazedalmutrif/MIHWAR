"""Orchestrator: routing graph, chaining, denials, failures, trace recording."""
import pytest

from mihwar import labels
from mihwar.agents.base import DomainError
from mihwar.orchestrator import ROUTES, AgentFailure, Denied

from conftest import CLIENT1, CLIENT2, FAHAD, MANAGER, SARAH


def test_routes_cover_every_event(ctx):
    events = {r["event"] for r in ROUTES}
    assert events == set(labels.EVENTS)
    assert events == set(ctx.orchestrator.handlers)
    for r in ROUTES:
        assert all(a in ctx.agents for a in r["agents"])


def test_human_actions_always_pass_security_first(ctx):
    for r in ROUTES:
        if r["event"] in ("brief.ready", "plan.created"):
            continue  # internal chained events
        assert r["agents"][0] == "security", r["event"]


def test_full_chain_records_every_step(ctx):
    db, orch = ctx.db, ctx.orchestrator
    client = db.get("users", CLIENT1)
    run, res = orch.dispatch("client.request_submitted", {"text": "فيلا في جدة على أرض 500 م2 دورين، تصميم معماري وإنشائي"}, client)
    steps = db.all("SELECT * FROM steps WHERE run_id = ? ORDER BY seq", (run.run_id,))
    assert [s["agent"] for s in steps] == ["security", "intake", "proposal"]
    assert steps[2]["event"] == "brief.ready"
    assert db.get("runs", run.run_id, key="run_id")["status"] == "ok"
    run2, res2 = orch.dispatch("proposal.approved", {"proposal_id": res["proposal_id"]}, db.get("users", MANAGER))
    run3, res3 = orch.dispatch("proposal.accepted", {"proposal_id": res["proposal_id"]}, client)
    agents = [s["agent"] for s in db.all("SELECT agent FROM steps WHERE run_id = ? ORDER BY seq", (run3.run_id,))]
    assert agents == ["security", "proposal", "planner", "team"]
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE project_id = ? AND assignee_id IS NULL AND is_milestone = 0", (res3["project_id"],)) == 0


def test_denial_marks_run_and_audits(ctx):
    db, orch = ctx.db, ctx.orchestrator
    prop = db.one("SELECT id FROM proposals WHERE status = 'draft' LIMIT 1")
    with pytest.raises(Denied) as e:
        orch.dispatch("proposal.approved", {"proposal_id": prop["id"]}, db.get("users", FAHAD))
    assert db.get("runs", e.value.run_id, key="run_id")["status"] == "denied"
    assert db.scalar("SELECT COUNT(*) FROM audit WHERE run_id = ? AND decision = 'deny'", (e.value.run_id,)) == 1


def test_domain_error_marks_run_error(ctx):
    db, orch = ctx.db, ctx.orchestrator
    doc = db.one("SELECT * FROM documents WHERE state = 'WIP' LIMIT 1")
    member = db.one("SELECT user_id FROM project_members m JOIN users u ON u.id = m.user_id WHERE m.project_id = ? AND u.role = 'engineer' LIMIT 1",
                    (doc["project_id"],))
    with pytest.raises(DomainError) as e:
        orch.dispatch("file.status_changed", {"document_id": doc["id"], "to_state": "PUBLISHED"}, db.get("users", member["user_id"]))
    assert e.value.code == "invalid_state"
    assert db.get("runs", e.value.extra["run_id"], key="run_id")["status"] == "error"


def test_unexpected_agent_crash_is_contained(ctx, monkeypatch):
    db, orch = ctx.db, ctx.orchestrator

    def boom(**kw):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(ctx.agents["reporting"], "op_answer", boom)
    project = db.one("SELECT id FROM projects WHERE client_id = 1")
    with pytest.raises(AgentFailure) as e:
        orch.dispatch("client.question", {"project_id": project["id"], "text": "وين وصل؟"}, db.get("users", CLIENT1))
    step = db.one("SELECT * FROM steps WHERE run_id = ? AND agent = 'reporting'", (e.value.run_id,))
    assert step["status"] == "error"
    # the platform keeps working afterwards
    run, _ = orch.dispatch("report.weekly", {"project_id": project["id"]}, db.get("users", MANAGER))
    assert db.get("runs", run.run_id, key="run_id")["status"] == "ok"


def test_on_step_callback_receives_steps_live(ctx):
    seen = []
    ctx.orchestrator.dispatch("security.simulate", {"kind": "client_wip"}, ctx.db.get("users", MANAGER), on_step=seen.append)
    assert [s["agent"] for s in seen] == ["security", "security"]
    assert seen[1]["status"] == "denied"
