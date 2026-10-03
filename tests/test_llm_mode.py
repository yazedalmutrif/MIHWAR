"""LLM-mode wiring with the Anthropic client mocked (no network, no API key)."""
import json
from types import SimpleNamespace

from conftest import CLIENT1


class FakeMessages:
    def __init__(self, reply=None, error=None, stop="end_turn"):
        self.reply, self.error, self.stop, self.calls = reply, error, stop, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=json.dumps(self.reply, ensure_ascii=False))])


class FakeClient:
    def __init__(self, messages):
        self.beta = SimpleNamespace(messages=messages)
        self.messages = messages


def use_llm(ctx, messages):
    ctx.llm.enabled = True
    ctx.llm._client = FakeClient(messages)


BRIEF = {"client_name": None, "project_type": "villa", "city": "الرياض", "district": "حطين", "land_area_m2": 800,
         "floors": 2, "has_annex": True, "services": ["arch_design", "struct_design"], "timeline_months": 5,
         "budget_sar": None, "notes": "يفضّل تصميمًا نجديًا حديثًا"}


def test_intake_uses_claude_and_merges(ctx):
    msgs = FakeMessages(reply=BRIEF)
    use_llm(ctx, msgs)
    brief, mode = ctx.agents["intake"].understand("ودي أسوي بيت لعيالي في حطين، تقريبًا ثمنمية متر، دورين وملحق، مخططات معمارية وإنشائية")
    assert mode == "llm"
    assert brief["land_area_m2"] == 800 and brief["district"] == "حطين" and brief["notes"]
    call = msgs.calls[0]
    assert call["model"] == ctx.settings.model
    assert call["output_config"]["format"]["type"] == "json_schema" and call["output_config"]["effort"] == "low"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]


def test_intake_falls_back_on_error(ctx):
    use_llm(ctx, FakeMessages(error=RuntimeError("network down")))
    brief, mode = ctx.agents["intake"].understand("فيلا في جدة على أرض 500 م2 دورين تصميم معماري")
    assert mode == "offline-fallback" and brief["city"] == "جدة" and brief["land_area_m2"] == 500


def test_intake_falls_back_on_refusal_and_bad_schema(ctx):
    use_llm(ctx, FakeMessages(reply=BRIEF, stop="refusal"))
    assert ctx.agents["intake"].understand("فيلا في جدة 500 م2")[1] == "offline-fallback"
    use_llm(ctx, FakeMessages(reply={**BRIEF, "project_type": "spaceship"}))
    assert ctx.agents["intake"].understand("فيلا في جدة 500 م2")[1] == "offline-fallback"


def test_trace_records_llm_mode(ctx):
    use_llm(ctx, FakeMessages(reply=BRIEF))
    run, _ = ctx.orchestrator.dispatch("client.request_submitted", {"text": "بيت في حطين ٨٠٠ متر دورين وملحق مخططات معمارية وإنشائية"},
                                       ctx.db.get("users", CLIENT1))
    modes = {s["agent"]: s["mode"] for s in ctx.db.all("SELECT agent, mode FROM steps WHERE run_id = ?", (run.run_id,))}
    assert modes["intake"] == "llm" and modes["security"] == "offline"


def test_reporting_answer_with_claude_and_fallback(ctx):
    project = ctx.db.one("SELECT id FROM projects WHERE client_id = 1")
    use_llm(ctx, FakeMessages(reply={"text_ar": "مشروعك يسير وفق الخطة."}))
    ans = ctx.agents["reporting"].op_answer(project["id"], "وين وصل مشروعي؟")
    assert ans.mode == "llm" and ans.output["text_ar"] == "مشروعك يسير وفق الخطة."
    use_llm(ctx, FakeMessages(error=TimeoutError()))
    ans2 = ctx.agents["reporting"].op_answer(project["id"], "وين وصل مشروعي؟")
    assert ans2.mode == "offline-fallback" and "نسبة الإنجاز" in ans2.output["text_ar"]


def test_weekly_polish_keeps_facts(ctx):
    project = ctx.db.one("SELECT id FROM projects WHERE client_id = 1")
    use_llm(ctx, FakeMessages(reply={"text_ar": "تقرير بلا أرقام"}))  # drops the progress figure -> rejected
    res = ctx.agents["reporting"].op_weekly(project["id"])
    assert res.mode == "offline-fallback"


def test_document_classification_uses_claude_only_when_unsure(ctx):
    msgs = FakeMessages(reply={"discipline": "structural", "doc_type": "CA", "reason_ar": "حسابات"})
    use_llm(ctx, msgs)
    c, mode = ctx.agents["documents"]._classify("scan_0042.pdf")
    assert mode == "llm" and c["discipline"] == "structural"
    c2, mode2 = ctx.agents["documents"]._classify("S-101 Foundation Plan.pdf")
    assert mode2 == "offline" and len(msgs.calls) == 1
