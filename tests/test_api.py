"""API tests with FastAPI's TestClient: every route, by role, including error contracts."""
import time

import pytest

from conftest import CLIENT1, CLIENT2, CLIENT3, FAHAD, H, LAYAN, MANAGER, NOURA, SARAH


def test_public_endpoints(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["app"]["name_ar"] == "محور" and meta["timezone"] == "Asia/Riyadh"
    users = client.get("/api/demo/users").json()["items"]
    assert len(users) == 12 and {u["role"] for u in users} == {"manager", "engineer", "client"}
    office = client.get("/api/portal/office").json()
    assert len(office["services"]) == 9
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/js/app.js").status_code == 200


def test_auth_errors(client):
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthenticated"
    assert client.get("/api/me", headers={"X-Demo-User": "999"}).status_code == 401
    assert client.get("/api/me", headers=H(SARAH)).json()["name_ar"] == "م. سارة القحطاني"


@pytest.mark.parametrize("path,manager,engineer,client_", [
    ("/api/dashboard", 200, 200, 403),
    ("/api/activity", 200, 200, 403),
    ("/api/projects", 200, 200, 200),
    ("/api/team", 200, 200, 403),
    ("/api/files", 200, 200, 200),
    ("/api/transmittals", 200, 200, 200),
    ("/api/compliance", 200, 200, 403),
    ("/api/security/audit", 200, 403, 403),
    ("/api/security/alerts", 200, 403, 403),
    ("/api/security/roles", 200, 200, 403),
    ("/api/agents", 200, 200, 403),
    ("/api/agents/graph", 200, 200, 403),
    ("/api/proposals", 200, 403, 200),
    ("/api/portal/requests", 200, 403, 200),
    ("/api/portal/projects", 200, 403, 200),
])
def test_read_permissions_by_role(client, path, manager, engineer, client_):
    assert client.get(path, headers=H(MANAGER)).status_code == manager
    assert client.get(path, headers=H(SARAH)).status_code == engineer
    assert client.get(path, headers=H(CLIENT1)).status_code == client_


def test_403_contract_has_arabic_message(client, pid):
    r = client.get(f"/api/projects/{pid['MST-2026-009']}", headers=H(CLIENT1))
    d = r.json()["detail"]
    assert r.status_code == 403 and d["code"] == "forbidden" and "مرفوض" in d["message_ar"]


def test_engineer_sees_only_assigned_projects(client, ctx):
    items = client.get("/api/projects", headers=H(NOURA)).json()["items"]
    member_of = {r["project_id"] for r in ctx.db.all("SELECT project_id FROM project_members WHERE user_id = ?", (NOURA,))}
    assert {p["id"] for p in items} == member_of


def test_client_sees_only_published_own_files(client):
    items = client.get("/api/files", headers=H(CLIENT1)).json()["items"]
    assert items and all(d["state"] == "PUBLISHED" and d["project_code"] == "MST-2026-007" for d in items)


def test_portal_request_flow_incomplete_then_complete(client):
    r = client.post("/api/portal/requests", json={"text": "أبي أصمم استراحة"}, headers=H(CLIENT3))
    assert r.status_code == 200
    body = r.json()
    assert body["request"]["status"] == "needs_info" and body["proposal"] is None
    assert body["request"]["follow_up_questions_ar"]
    assert [s["agent"] for s in body["run"]["steps"]] == ["security", "intake"]
    rid = body["request"]["id"]
    r2 = client.post(f"/api/portal/requests/{rid}/messages", json={"text": "في الطائف، الأرض ١٠٠٠ م٢، تصميم معماري وإنشائي"}, headers=H(CLIENT3))
    b2 = r2.json()
    assert b2["request"]["complete"] and b2["proposal"]["status"] == "draft"
    # another client cannot reply to this request
    assert client.post(f"/api/portal/requests/{rid}/messages", json={"text": "x x x x x"}, headers=H(CLIENT2)).status_code == 403


def test_proposal_lifecycle_via_api(client):
    r = client.post("/api/portal/requests", json={"text": "فيلا في الرياض مساحة الأرض 700 م2 دورين مع تصميم معماري وإنشائي ورخصة"}, headers=H(CLIENT1))
    prop = r.json()["proposal"]
    # client cannot see the draft yet, engineer cannot approve
    assert client.get(f"/api/proposals/{prop['id']}", headers=H(CLIENT1)).status_code == 403
    assert client.post(f"/api/proposals/{prop['id']}/approve", headers=H(SARAH)).status_code == 403
    assert client.post(f"/api/proposals/{prop['id']}/accept", headers=H(CLIENT1)).status_code == 409
    ok = client.post(f"/api/proposals/{prop['id']}/approve", headers=H(MANAGER)).json()
    assert ok["proposal"]["status"] == "sent" and [h["status"] for h in ok["proposal"]["history"]][-2:] == ["approved", "sent"]
    acc = client.post(f"/api/proposals/{prop['id']}/accept", headers=H(CLIENT1)).json()
    assert acc["proposal"]["status"] == "accepted" and acc["project"]["code"].startswith("MST-")
    detail = client.get(f"/api/projects/{acc['project']['id']}", headers=H(MANAGER)).json()
    assert detail["tasks"] and detail["phases"] and all(t["assignee"] for t in detail["tasks"] if not t["is_milestone"])


def test_project_detail_hides_internal_data_from_client(client, pid):
    d = client.get(f"/api/projects/{pid['MST-2026-007']}", headers=H(CLIENT1)).json()
    assert d["qa_reports"] == [] and all(x["state"] == "PUBLISHED" for x in d["documents"])
    assert all(r["sent_to_client"] for r in d["reports"])


def test_params_change_triggers_compliance(client, pid):
    r = client.patch(f"/api/projects/{pid['MST-2026-009']}/params", json={"coverage_ratio": 0.58}, headers=H(MANAGER))
    assert r.status_code == 200
    body = r.json()
    assert not any(i["rule_id"] == "Z-01" for i in body["qa_report"]["issues"])
    assert [s["agent"] for s in body["run"]["steps"]] == ["security", "compliance"]
    bad = client.patch(f"/api/projects/{pid['MST-2026-009']}/params", json={"coverage_ratio": 3}, headers=H(MANAGER))
    assert bad.status_code == 422


def test_task_update_rules(client, ctx, pid):
    t = ctx.db.one("SELECT * FROM tasks WHERE project_id = ? AND assignee_id = ? AND is_milestone = 0 AND status != 'done' LIMIT 1",
                   (pid["MST-2026-009"], SARAH))
    assert client.patch(f"/api/tasks/{t['id']}", json={"progress": 40}, headers=H(FAHAD)).status_code == 403
    r = client.patch(f"/api/tasks/{t['id']}", json={"progress": 100}, headers=H(SARAH)).json()
    assert r["task"]["status"] == "done" and "engineers" in r["team"]
    assert client.patch(f"/api/tasks/{t['id']}", json={"progress": 140}, headers=H(SARAH)).status_code == 422


def test_rebalance_suggestion_applies(client):
    team = client.get("/api/team", headers=H(MANAGER)).json()
    s = team["suggestions"][0]
    r = client.post("/api/team/rebalance", json={"task_id": s["task_id"], "to_engineer_id": s["to"]["id"]}, headers=H(MANAGER))
    assert r.status_code == 200 and r.json()["task"]["assignee"]["id"] == s["to"]["id"]
    assert client.post("/api/team/rebalance", json={"task_id": s["task_id"], "to_engineer_id": s["from"]["id"]}, headers=H(SARAH)).status_code == 403


def test_upload_download_and_publish_gate(client, pid):
    project = pid["MST-2026-007"]
    files = {"file": ("Roof Plan.pdf", b"%PDF-1.4 roof plan test", "application/pdf")}
    r = client.post("/api/files", data={"project_id": str(project)}, files=files, headers=H(SARAH))
    assert r.status_code == 200, r.text
    up = r.json()
    doc = up["document"]
    assert up["classification"]["discipline"] == "architectural" and up["revision"]["value"] == "P01"
    assert len(up["naming"]["fields"]) == 7 and up["naming"]["fields"][3]["value"] == "RF"
    dup = client.post("/api/files", data={"project_id": str(project)}, files=files, headers=H(SARAH)).json()
    assert dup["duplicate_of"]["id"] == doc["id"]
    # unassigned engineer cannot upload; client cannot download a WIP file
    assert client.post("/api/files", data={"project_id": str(project)}, files={"file": ("x.pdf", b"%PDF x", "application/pdf")}, headers=H(LAYAN)).status_code in (200, 403)
    blocked = client.get(f"/api/files/{doc['id']}/download", headers=H(CLIENT1))
    assert blocked.status_code == 403 and blocked.json()["detail"]["alert_id"]
    assert client.get(f"/api/files/{doc['id']}/download", headers=H(SARAH)).content.startswith(b"%PDF")
    # gate: illegal jump, then share, then publish without QA -> 409, then QA + sign-off -> publish
    assert client.post(f"/api/files/{doc['id']}/state", json={"to_state": "PUBLISHED"}, headers=H(SARAH)).json()["detail"]["code"] == "invalid_state"
    assert client.post(f"/api/files/{doc['id']}/state", json={"to_state": "SHARED"}, headers=H(SARAH)).status_code == 200
    g = client.post(f"/api/files/{doc['id']}/state", json={"to_state": "PUBLISHED"}, headers=H(SARAH))
    assert g.status_code == 409 and g.json()["detail"]["code"] == "qa_signoff_required"
    qa = client.post(f"/api/projects/{project}/qa", json={"document_id": doc["id"]}, headers=H(SARAH)).json()["qa_report"]
    assert client.post(f"/api/qa/{qa['id']}/signoff", json={"note": "x"}, headers=H(FAHAD)).status_code == 403
    # project MST-2026-007 has a medium side-setback issue only, so a licensed engineer may sign
    s = client.post(f"/api/qa/{qa['id']}/signoff", json={"note": "ok"}, headers=H(SARAH))
    assert s.status_code == 200 and s.json()["qa_report"]["status"] == "signed_off"
    pub = client.post(f"/api/files/{doc['id']}/state", json={"to_state": "PUBLISHED"}, headers=H(SARAH)).json()
    assert pub["document"]["revision"] == "C01" and pub["transmittal"]["code"].startswith("TR-")
    assert client.get(f"/api/files/{doc['id']}/download", headers=H(CLIENT1)).status_code == 200


def test_reports_and_questions(client, pid):
    r = client.post(f"/api/projects/{pid['MST-2026-007']}/reports/weekly", json={"send_to_client": True}, headers=H(SARAH)).json()
    assert r["report"]["sent_to_client"] and set(r["report"]["sections"]) == {"done", "next", "milestones", "risks"}
    q = client.post("/api/portal/questions", json={"project_id": pid["MST-2026-007"], "text": "متى المعلم القادم؟"}, headers=H(CLIENT1)).json()
    assert q["answer"]["intent"] == "schedule"
    assert client.post("/api/portal/questions", json={"project_id": pid["MST-2026-009"], "text": "وين وصل؟"}, headers=H(CLIENT1)).status_code == 403


def test_security_endpoints(client):
    for kind in ("client_wip", "unassigned_access", "burst_download"):
        r = client.post("/api/security/simulate", json={"kind": kind}, headers=H(MANAGER)).json()
        assert r["alert"] is not None, kind
    alerts = client.get("/api/security/alerts?status=open", headers=H(MANAGER)).json()["items"]
    ack = client.post(f"/api/security/alerts/{alerts[0]['id']}/ack", headers=H(MANAGER)).json()
    assert ack["alert"]["status"] == "acknowledged"
    assert client.post("/api/security/simulate", json={"kind": "client_wip"}, headers=H(SARAH)).status_code == 403
    denies = client.get("/api/security/audit?decision=deny", headers=H(MANAGER)).json()
    assert denies["total"] > 0 and all(a["decision"] == "deny" for a in denies["items"])


def test_dashboard_and_activity(client):
    d = client.get("/api/dashboard", headers=H(MANAGER)).json()
    keys = {k["key"] for k in d["kpis"]}
    assert {"active_projects", "hours_saved_est", "security_alerts_open"} <= keys
    assert d["pending_approvals"] and d["recent_activity"]
    a = client.get("/api/activity?after_id=0&limit=5", headers=H(MANAGER)).json()
    assert len(a["items"]) == 5 and a["last_id"] >= a["items"][0]["id"]
    run = client.get(f"/api/runs/{a['items'][0]['run_id']}", headers=H(MANAGER)).json()
    assert run["steps"] and run["steps"][0]["input"] is not None


def test_agents_cards_and_self_tests(client):
    cards = client.get("/api/agents", headers=H(SARAH)).json()["items"]
    assert [c["key"] for c in cards][0] == "orchestrator" and len(cards) == 9
    one = client.post("/api/agents/intake/self-test", headers=H(SARAH)).json()
    assert one["passed"] and one["checks"]
    allr = client.post("/api/agents/self-test", headers=H(MANAGER)).json()
    assert allr["passed"] and len(allr["results"]) == 9
    cards = client.get("/api/agents", headers=H(MANAGER)).json()["items"]
    assert all(c["last_self_test"] and c["last_self_test"]["passed"] for c in cards)
    assert all(c["health"] == "healthy" for c in cards)


def test_scenario_endpoint_runs_to_completion(client):
    r = client.post("/api/scenario/run", headers=H(MANAGER))
    assert r.status_code == 202
    sid = r.json()["scenario_id"]
    for _ in range(120):
        sc = client.get(f"/api/scenario/{sid}", headers=H(MANAGER)).json()
        if sc["status"] != "running":
            break
        time.sleep(0.25)
    assert sc["status"] == "completed", sc.get("error_ar")
    assert all(s["status"] == "done" and s["steps"] for s in sc["stages"])
    assert client.post("/api/scenario/run", headers=H(CLIENT1)).status_code == 403
    assert client.get("/api/scenario/latest", headers=H(SARAH)).json()["scenario_id"] == sid


def test_demo_reset(client):
    client.post("/api/portal/requests", json={"text": "فيلا في جدة 400 م2 دورين تصميم معماري"}, headers=H(CLIENT1))
    assert client.post("/api/demo/reset", headers=H(SARAH)).status_code == 403
    assert client.post("/api/demo/reset", headers=H(MANAGER)).json()["ok"]
    assert len(client.get("/api/projects", headers=H(MANAGER)).json()["items"]) == 4
