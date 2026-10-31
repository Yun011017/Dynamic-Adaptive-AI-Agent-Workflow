import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from app.agent_runner import run_agent
from app.form_summary import summarize_answers
from app.schemas import AgentRunCreate


def sample(values=(1, 3)):
    return summarize_answers([{"test": value, "temp": 10, "Email": "private@example.test"} for value in values], numeric_fields=["test", "temp"], source_id="test-source")


class AgentRunnerTests(unittest.TestCase):
    def test_bounded_graph_uses_neon_summary(self):
        with patch("app.agent_runner.get_form_summary", return_value=sample()) as reader:
            result = run_agent(goal="Analyze forms", context="Test", constraints={}, workspace_id=7)
        reader.assert_called_once_with(workspace_id=7)
        self.assertEqual(result["data_source"], "neon_form_summary")
        self.assertEqual(result["form_summary"]["response_count"], 2)
        self.assertIn("平均 2", result["content_direction"])
        self.assertNotIn("動手實作", result["content_direction"])

    def test_changed_data_changes_result(self):
        outputs = []
        for values in ((1, 3), (10, 20)):
            with patch("app.agent_runner.get_form_summary", return_value=sample(values)):
                outputs.append(run_agent(goal="test", context="", constraints={}))
        self.assertNotEqual(outputs[0]["content_direction"], outputs[1]["content_direction"])
        self.assertNotEqual(outputs[0]["summary_id"], outputs[1]["summary_id"])

    def test_aggregate_allowlist_and_invalid_values(self):
        result = summarize_answers([{"test": 1, "Email": "private@example.test"}, {"test": True}, {"test": "99"}, {"test": float("nan")}], numeric_fields=["test"], source_id="test-source")
        self.assertEqual(result["numeric_fields"]["test"], dict(count=1, missing_or_invalid=3, min=1, max=1, mean=1))
        self.assertNotIn("private@example.test", json.dumps(result))
        self.assertNotIn("Email", json.dumps(result))

    def test_empty_data_is_not_synthetic(self):
        with patch("app.agent_runner.get_form_summary", return_value=sample(())):
            result = run_agent(goal="test", context="", constraints={})
        self.assertIn("尚無", result["content_direction"])
        self.assertEqual(result["form_summary"]["response_count"], 0)

    def test_database_failure_does_not_fall_back(self):
        with patch("app.agent_runner.get_form_summary", side_effect=RuntimeError("DB unavailable")):
            with self.assertRaises(RuntimeError):
                run_agent(goal="test", context="", constraints={})

    def test_model_receives_only_the_scoped_summary(self):
        class FakeModel:
            def bind_tools(self, tools):
                return self
            def invoke(self, messages):
                if messages[-1].type == "human":
                    return AIMessage(content="", tool_calls=[dict(name="get_form_summary_tool", args={}, id="read-1", type="tool_call")])
                summary = json.loads(messages[-1].content)
                assert summary["response_count"] == 2
                assert "Email" not in messages[-1].content
                return AIMessage(content="2 筆回覆，test 平均為 2，尚無業務定義。")
        with patch("app.agent_runner.get_form_summary", return_value=sample()) as reader, patch("app.agent_runner._model_for", return_value=FakeModel()):
            result = run_agent(goal="test", context="", constraints={}, provider="gemini", workspace_id=7)
        reader.assert_called_once_with(workspace_id=7)
        self.assertTrue(result["tool_called"])
        self.assertEqual(result["form_summary"]["numeric_fields"]["test"]["mean"], 2)

    def test_api_source_is_neon(self):
        self.assertEqual(AgentRunCreate(goal="test").data_source, "neon_form_summary")
        with self.assertRaises(ValueError):
            AgentRunCreate(goal="test", data_source="arbitrary")
