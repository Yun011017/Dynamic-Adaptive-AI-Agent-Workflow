import unittest

from app.agent_runner import run_agent


class AgentRunnerTests(unittest.TestCase):
    def test_bounded_graph_uses_the_form_summary(self):
        result = run_agent(
            goal="Increase registrations",
            context="Student workshop",
            constraints={"channel": "instagram"},
        )
        self.assertEqual(result["data_source"], "synthetic_form_summary")
        self.assertEqual(result["goal"], "Increase registrations")
        self.assertIn("動手實作", result["content_direction"])
        self.assertEqual(result["expected_metrics"], ["reach", "clicks", "registrations"])
