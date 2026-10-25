"""離線驗證 LangGraph 工具呼叫流程，不會呼叫付費模型 API。"""

import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from agent_lab.main import build_graph


class FakeModel:
    """模擬模型先呼叫工具，再根據工具結果產生回答。"""

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.last_messages = messages
        if messages[-1].type == "human":
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_form_summary",
                        "args": {},
                        "id": "test-call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="測試建議：主打動手實作。")


class AgentGraphTest(unittest.TestCase):
    def test_agent_calls_tool_and_returns_final_answer(self):
        model = FakeModel()
        graph = build_graph(model)
        config = {"configurable": {"thread_id": "agent-test-review"}}
        result = graph.invoke(
            {"messages": [HumanMessage(content="請分析報名摘要")]}, config=config
        )
        messages = result["messages"]

        self.assertEqual(
            [message.type for message in messages], ["human", "ai", "tool", "ai"]
        )
        tool_result = messages[2]
        self.assertEqual(tool_result.tool_call_id, "test-call-1")
        self.assertEqual(json.loads(tool_result.content)["回覆人數"], 30)
        self.assertEqual(model.last_messages[-1].content, tool_result.content)

        self.assertTrue(any(getattr(message, "tool_calls", None) for message in messages))
        self.assertTrue(any(message.type == "tool" for message in messages))
        self.assertEqual(messages[-1].content, "測試建議：主打動手實作。")
        self.assertIn("__interrupt__", result)
        self.assertEqual(result["__interrupt__"][0].value["draft"], messages[-1].content)

        resumed = graph.invoke(
            Command(resume={"action": "edit", "draft": "人工修改後的草稿。"}),
            config=config,
        )
        self.assertEqual(resumed["review_status"], "edited_and_approved")
        self.assertEqual(resumed["approved_draft"], "人工修改後的草稿。")

    def test_direct_answer_still_requires_review_and_can_be_rejected(self):
        class DirectAnswerModel(FakeModel):
            def invoke(self, messages):
                return AIMessage(content="直接回答")

        graph = build_graph(DirectAnswerModel())
        config = {"configurable": {"thread_id": "direct-answer-review"}}
        result = graph.invoke(
            {"messages": [HumanMessage(content="測試審核分支")]}, config=config
        )
        self.assertEqual([message.type for message in result["messages"]], ["human", "ai"])
        self.assertEqual(result["messages"][-1].content, "直接回答")
        resumed = graph.invoke(Command(resume={"action": "reject"}), config=config)
        self.assertEqual(resumed["review_status"], "rejected")
        self.assertNotIn("approved_draft", resumed)


if __name__ == "__main__":
    unittest.main()
