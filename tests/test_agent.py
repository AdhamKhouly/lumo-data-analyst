"""The tool loop, driven by a fake Claude client so no API key or network is needed."""
from types import SimpleNamespace

from src.agent import TOOLS, Conversation, Lumo, run_tool
from tests.conftest import requires_data

pytestmark = requires_data


class FakeClient:
    """Answers the first request with a tool call and the second with text."""

    def __init__(self):
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            block = SimpleNamespace(type="tool_use", id="call_1", name="compare_metric",
                                    input={"metric": "revenue", "start_week": 3, "end_week": 8})
            return SimpleNamespace(content=[block], stop_reason="tool_use")
        tool_result = self.requests[-1]["messages"][-1]["content"][0]
        assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "call_1"
        assert "15741.42" in tool_result["content"]
        text = SimpleNamespace(type="text", text="Revenue rose from $13,048.00 to $28,789.42 (+120.6%).")
        return SimpleNamespace(content=[text], stop_reason="end_turn")


def test_every_tool_name_is_dispatchable(db):
    for tool in TOOLS:
        result = run_tool(db, tool["name"], {})
        assert "unknown tool" not in result.get("message", ""), tool["name"]
    assert run_tool(db, "delete_everything", {})["status"] == "error"


def test_ask_runs_the_tool_and_keeps_the_history(db):
    client = FakeClient()
    lumo = Lumo(db, model="fake-model", client=client)
    conversation = Conversation()
    answer = lumo.ask("How much did revenue increase from week 3 to week 8?", conversation)
    assert answer.error is None and "120.6%" in answer.text
    assert [c.name for c in answer.tool_calls] == ["compare_metric"]
    assert answer.tool_calls[0].status == "ok"
    assert conversation.turns == 1 and len(conversation.messages) == 4  # question, tool call, result, answer
    assert client.requests[0]["tools"] is TOOLS and "Cafe A" in client.requests[0]["system"]
