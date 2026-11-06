import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from langchain_core.messages import AIMessage
from app.agent_runner import run_agent
from app.form_summary import summarize_responses
from app.schemas import AgentRunCreate


def sample(values=(True, False)):
    return summarize_responses([
        {"is_member": value, "will_attend": value, "school": "臺大", "department_grade": "資工二", "activity_name": "物聯網工作坊",
         "submitted_at": datetime(2026, 10, 31, tzinfo=timezone.utc), "normalization_errors": [],
         "Email": "private@example.test", "test": 99} for value in values
    ], source_id="test-source")


class AgentRunnerTests(unittest.TestCase):
    def test_bounded_graph_uses_form_responses(self):
        with patch("app.agent_runner.get_form_summary", return_value=sample()) as reader:
            result = run_agent(goal="Analyze forms", context="Test", constraints={}, workspace_id=7)
        reader.assert_called_once_with(workspace_id=7)
        self.assertEqual(result["data_source"], "neon_form_summary")
        self.assertEqual(result["form_summary"]["storage_table"], "form_responses")
        self.assertIn("社員 1 筆", result["content_direction"])
        self.assertIn("願意參加 1 筆", result["content_direction"])
        self.assertNotIn("動手實作", result["content_direction"])

    def test_changed_data_changes_result(self):
        outputs = []
        for values in ((True, False), (False, False)):
            with patch("app.agent_runner.get_form_summary", return_value=sample(values)):
                outputs.append(run_agent(goal="test", context="", constraints={}))
        self.assertNotEqual(outputs[0]["content_direction"], outputs[1]["content_direction"])
        self.assertNotEqual(outputs[0]["summary_id"], outputs[1]["summary_id"])

    def test_aggregate_allowlist_and_unknown(self):
        result = sample((True, False, None))
        self.assertEqual(result["membership"], dict(yes=1, no=1, unknown=1))
        self.assertEqual(result["attendance"], dict(yes=1, no=1, unknown=1))
        self.assertEqual(result["schools"], {"臺大": 3})
        self.assertEqual(result["department_grades"], {"資工二": 3})
        self.assertEqual(result["activities"], {"物聯網工作坊": 3})
        self.assertNotIn("private@example.test", json.dumps(result))
        self.assertNotIn("Email", json.dumps(result))
        self.assertNotIn("numeric_fields", result)
        self.assertEqual(result["submission_period"]["known_count"], 3)

    def test_empty_data_is_not_synthetic(self):
        with patch("app.agent_runner.get_form_summary", return_value=sample(())):
            result = run_agent(goal="test", context="", constraints={})
        self.assertIn("尚無", result["content_direction"])
        self.assertEqual(result["form_summary"]["response_count"], 0)

    def test_all_unknown_does_not_mean_no(self):
        summary = summarize_responses([dict(is_member=None, will_attend=None, school=None, department_grade=None, activity_name=None, submitted_at=None,
                                            normalization_errors=["is_member:unknown_value"])], source_id="test-source")
        self.assertEqual(summary["attendance"], dict(yes=0, no=0, unknown=1))
        self.assertEqual(summary["activity_unknown_count"], 1)
        self.assertIsNone(summary["submission_period"]["first"])
        self.assertEqual(summary["normalization_error_count"], 1)
        with patch("app.agent_runner.get_form_summary", return_value=summary):
            result = run_agent(goal="test", context="", constraints={})
        self.assertIn("未知 1 筆", result["content_direction"])
        self.assertIn("不參加 0 筆", result["content_direction"])

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
                assert summary["storage_table"] == "form_responses"
                assert summary["attendance"]["yes"] == 1
                assert "Email" not in messages[-1].content
                return AIMessage(content="2 筆回覆，其中 1 筆願意參加。")
        with patch("app.agent_runner.get_form_summary", return_value=sample()) as reader, patch("app.agent_runner._model_for", return_value=FakeModel()):
            result = run_agent(goal="test", context="", constraints={}, provider="gemini", workspace_id=7)
        reader.assert_called_once_with(workspace_id=7)
        self.assertTrue(result["tool_called"])
        self.assertEqual(result["form_summary"]["attendance"]["yes"], 1)

    def test_api_source_is_neon(self):
        self.assertEqual(AgentRunCreate(goal_id=1, goal="test").data_source, "neon_form_summary")
        with self.assertRaises(ValueError):
            AgentRunCreate(goal_id=1, goal="test", data_source="arbitrary")

    def test_audience_data_changes_summary_and_recommendation(self):
        rows = [dict(is_member=True, will_attend=True, school='臺大', department_grade='資工二', activity_name='物聯網'),
                dict(is_member=None, will_attend=False, school='臺科大', department_grade='電機三', activity_name='3D列印'),
                dict(is_member=False, will_attend=None, school=None, department_grade=None, activity_name=None)]
        summary = summarize_responses(rows, source_id='test-source')
        self.assertEqual(summary['schools'], {'臺大': 1, '臺科大': 1})
        self.assertEqual(summary['school_unknown_count'], 1)
        self.assertEqual(summary['department_grade_unknown_count'], 1)
        self.assertEqual(summary['activity_unknown_count'], 1)
        with patch('app.agent_runner.get_form_summary', return_value=summary):
            result = run_agent(goal='分析客群', context='', constraints={})
        self.assertIn('資工二', result['content_direction'])
        self.assertIn('物聯網', result['content_direction'])
        self.assertNotIn('event_dates', summary)
