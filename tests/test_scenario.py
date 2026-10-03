"""The end-to-end demo scenario, run synchronously."""
from mihwar.db import loads


def test_scenario_end_to_end(ctx):
    sc = ctx.scenarios.start(background=False)
    pub = ctx.scenarios.public(sc)
    assert pub["status"] == "completed", pub["error_ar"]
    assert [s["key"] for s in pub["stages"]] == ["intake", "proposal", "approval", "planner", "team", "documents",
                                                  "compliance", "security", "reporting"]
    for s in pub["stages"]:
        assert s["status"] == "done" and s["steps"], s["key"]
        assert s["highlight_ar"]
    agents_by_stage = {s["key"]: {st["agent"] for st in s["steps"]} for s in pub["stages"]}
    assert "intake" in agents_by_stage["intake"]
    assert agents_by_stage["proposal"] == {"proposal"}
    assert agents_by_stage["planner"] == {"planner"} and agents_by_stage["team"] == {"team"}
    assert "documents" in agents_by_stage["documents"]
    assert {"compliance", "documents"} <= agents_by_stage["compliance"]
    assert agents_by_stage["security"] == {"security"}

    db, res = ctx.db, pub["result"]
    req = db.get("requests", res["request_id"])
    brief = loads(req["brief_json"])
    assert brief["city"] == "الرياض" and brief["land_area_m2"] == 600 and brief["floors"] == 2 and brief["district"] == "الملقا"
    assert db.get("proposals", res["proposal_id"])["status"] == "accepted"
    doc = db.get("documents", res["document_id"])
    assert doc["state"] == "PUBLISHED" and doc["revision"] == "C01"
    assert db.get("qa_reports", res["qa_report_id"])["status"] == "signed_off"
    alert = db.get("alerts", res["alert_id"])
    assert alert and alert["type"] == "client_wip_request"
    rep = db.get("reports", res["report_id"])
    assert rep["sent_to_client"] == 1 and rep["kind"] == "client_update"
    assert pub["duration_ms"] < 60_000
