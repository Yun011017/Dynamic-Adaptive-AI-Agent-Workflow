"""Server-safe Agent Core adapter used only by the background worker."""
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import settings


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


def _run_local(*, goal: str, context: str, constraints: dict) -> dict:
    result = build_graph().invoke(
        {"goal": goal, "context": context, "constraints": constraints}
    )
    return result["recommendation"]


def _secret_for(provider: str) -> str:
    field = {
        "gemini": settings.google_api_key,
        "openai": settings.openai_api_key,
        "claude": settings.anthropic_api_key,
    }[provider]
    if field is None or not field.get_secret_value().strip():
        raise RuntimeError(f"{provider.upper()}_API_KEY is not configured for the worker")
    return field.get_secret_value()


def _model_for(provider: str, model_name: str):
    api_key = _secret_for(provider)
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name, google_api_key=api_key, request_timeout=30, retries=0
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name, api_key=api_key, use_responses_api=True,
            timeout=30, max_retries=0,
        )
    if provider == "claude":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, api_key=api_key, timeout=30, max_retries=0)
    raise RuntimeError(f"Unsupported Agent provider: {provider}")


def _text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return str(content)


def _run_model(*, goal: str, context: str, constraints: dict, provider: str, model_name: str) -> dict:
    """Use the same tool-calling shape as agent_lab without terminal interaction."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import tool
    from langgraph.graph import MessagesState
    from langgraph.prebuilt import ToolNode

    @tool
    def get_form_summary_tool() -> dict:
        """取得 NTUMaker 測試活動的彙整報名資料，不含個人資料。"""
        return get_form_summary()

    tools = [get_form_summary_tool]
    model = _model_for(provider, model_name).bind_tools(tools)

    def call_agent(state: MessagesState) -> dict:
        response = model.invoke([
            SystemMessage(
                content=(
                    "你是行銷分析助理，必須先呼叫 get_form_summary_tool，"
                    "再以繁體中文提出可追溯的行銷建議。"
                )
            ),
            *state["messages"],
        ])
        return {"messages": [response]}

    def route_after_agent(state: MessagesState) -> str:
        last_message = state["messages"][-1]
        return "tools" if getattr(last_message, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    result = graph.compile().invoke({
        "messages": [HumanMessage(content=json.dumps({
            "goal": goal, "context": context, "constraints": constraints,
        }, ensure_ascii=False))]
    })
    final_text = _text_content(result["messages"][-1].content)
    tool_called = any(getattr(message, "type", None) == "tool" for message in result["messages"])
    if not tool_called:
        raise RuntimeError("Agent completed without reading the required form-summary tool")
    return {
        "target_audience": "由模型依測試表單判斷",
        "content_direction": final_text,
        "reason": "模型已先讀取測試表單摘要，再產生建議。",
        "expected_metrics": ["reach", "clicks", "registrations"],
        "goal": goal,
        "context": context,
        "constraints": constraints,
        "data_source": "synthetic_form_summary",
        "tool_called": True,
    }


def run_agent(*, goal: str, context: str, constraints: dict, provider: str = "local", model_name: str = "deterministic-langgraph") -> dict:
    """Run a bounded Agent graph; model credentials stay in worker-only settings."""
    if provider == "local":
        return _run_local(goal=goal, context=context, constraints=constraints)
    return _run_model(
        goal=goal, context=context, constraints=constraints,
        provider=provider, model_name=model_name,
    )
