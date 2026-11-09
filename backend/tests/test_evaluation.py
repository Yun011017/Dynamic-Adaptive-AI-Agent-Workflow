import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.evaluation import build_evaluation_graph


class EvaluationTest(unittest.TestCase):
    def test_llm_enhances_recommendation_without_changing_kpi_result(self):
        model = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="保留原本的曝光做法。"))
        with (
            patch("app.evaluation.settings", SimpleNamespace(agent_provider="gemini", agent_model="test")),
            patch("app.evaluation._model_for", return_value=model) as model_factory,
        ):
            result = build_evaluation_graph().invoke({
                "targets": {"reach": 1000},
                "observations": [{
                    "id": 1, "metric": "reach", "value": 1200, "external_event_id": 2,
                    "observed_at": "2026-11-09T12:00:00+08:00", "attribution_status": "unattributed",
                }],
                "strategy_context": {"content": "以 Instagram 輪播曝光"},
            })["evaluation"]
        model_factory.assert_called_once_with("gemini", "test")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["recommendations"], ["保留原本的曝光做法。"])
        self.assertEqual(result["recommendation_source"], "llm")

    def test_replay_outcomes(self):
        graph = build_evaluation_graph()
        targets = {"reach": 1000, "registrations": 15}
        cases = [
            ((1000, 15), "SUCCESS"),
            ((1200, 11), "PARTIAL_SUCCESS"),
            ((0, 14), "FAILURE"),
            ((1200,), "UNABLE_TO_EVALUATE"),
        ]
        for values, expected in cases:
            with self.subTest(expected=expected):
                observations = [
                    {
                        "id": index,
                        "metric": metric,
                        "value": value,
                        "external_event_id": 1,
                        "observed_at": "2026-11-09T12:00:00+00:00",
                        "attribution_status": "unattributed",
                    }
                    for index, (metric, value) in enumerate(
                        zip(("reach", "registrations"), values), start=1
                    )
                ]
                result = graph.invoke({"targets": targets, "observations": observations})["evaluation"]
                self.assertEqual(result["status"], expected)
                self.assertTrue(result["recommendations"])
                if expected == "PARTIAL_SUCCESS":
                    self.assertTrue(any("報名入口" in item for item in result["recommendations"]))
                self.assertEqual(result["metrics"]["reach"]["difference"], values[0] - 1000)
                self.assertEqual(result["metrics"]["reach"]["external_event_id"], 1)
