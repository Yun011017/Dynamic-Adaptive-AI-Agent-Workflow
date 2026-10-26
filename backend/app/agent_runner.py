"""The first server-safe Agent Core adapter.

This deliberately uses a deterministic LangGraph graph until the team moves the
interactive, API-key-prompting agent_lab prototype into a background worker.
It gives FastAPI a stable request/response contract without exposing a model
key or making an external publication.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class RunState(TypedDict):
    goal: str
    context: str
    constraints: dict
    form_summary: dict
    recommendation: dict


def get_form_summary() -> dict:
    """Return a fixed, non-personal test summary shared with Agent Core."""
    return {
        "source": "synthetic_form_summary",
        "response_count": 30,
        "preferences": {"hands_on": 20, "project_sharing": 7, "club_intro": 3},
    }


def _read_summary(state: RunState) -> dict:
    return {"form_summary": get_form_summary()}


def _recommend(state: RunState) -> dict:
    summary = state["form_summary"]
    preference, count = max(summary["preferences"].items(), key=lambda item: item[1])
    labels = {
        "hands_on": "動手實作",
        "project_sharing": "專題分享",
        "club_intro": "社團介紹",
    }
    audience = f"偏好{labels[preference]}的潛在參與者"
    return {
        "recommendation": {
            "target_audience": audience,
            "content_direction": f"以{labels[preference]}作為內容主軸，回應 {count} 位測試受眾的偏好。",
            "reason": f"測試表單共有 {summary['response_count']} 份回覆，最高偏好是 {labels[preference]}。",
            "expected_metrics": ["reach", "clicks", "registrations"],
            "goal": state["goal"],
            "context": state["context"],
            "constraints": state["constraints"],
            "data_source": summary["source"],
        }
    }


def build_graph():
    graph = StateGraph(RunState)
    graph.add_node("read_form_summary", _read_summary)
    graph.add_node("generate_recommendation", _recommend)
    graph.add_edge(START, "read_form_summary")
    graph.add_edge("read_form_summary", "generate_recommendation")
    graph.add_edge("generate_recommendation", END)
    return graph.compile()


def run_agent(*, goal: str, context: str, constraints: dict) -> dict:
    """Run the bounded, no-side-effect graph and return its recommendation."""
    result = build_graph().invoke(
        {"goal": goal, "context": context, "constraints": constraints}
    )
    return result["recommendation"]
