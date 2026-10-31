"""Server-safe Agent Core adapter used only by the background worker."""
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import settings
from .form_summary import get_form_summary


class RunState(TypedDict):
    workspace_id: int | None
    goal: str
    context: str
    constraints: dict
    form_summary: dict
    recommendation: dict


def _read_summary(state: RunState) -> dict:
    return {"form_summary": get_form_summary(workspace_id=state.get("workspace_id"))}


def _recommend(state: RunState) -> dict:
    summary = state["form_summary"]
    count = summary["response_count"]
    stats = "；".join(
        f"{name}：有效 {value['count']} 筆，平均 {value['mean']}，最小 {value['min']}，最大 {value['max']}"
        for name, value in summary["numeric_fields"].items() if value["count"]
    )
    direction = (f"已讀取 Neon 的 {count} 筆表單回覆。{stats}。請先定義題目意義，再制定活動宣傳建議。"
                 if count else "Neon 尚無此來源的表單回覆，請先執行表單同步。")
    return {"recommendation": {
        "target_audience": "目前資料不足以判斷受眾偏好",
        "content_direction": direction,
        "reason": f"依據 Neon 已匯入的 {count} 筆回覆；僅使用允許欄位的聚合數值。",
        "expected_metrics": ["response_count"],
        "goal": state["goal"], "context": state["context"], "constraints": state["constraints"],
        "data_source": summary["source"], "form_summary": summary,
        "summary_id": summary["summary_id"],
        "evidence": {"response_count": count, "numeric_fields": summary["numeric_fields"]},
    }}


def build_graph():
    graph = StateGraph(RunState)
    graph.add_node("read_form_summary", _read_summary)
    graph.add_node("generate_recommendation", _recommend)
    graph.add_edge(START, "read_form_summary")
    graph.add_edge("read_form_summary", "generate_recommendation")
    graph.add_edge("generate_recommendation", END)
    return graph.compile()


def _run_local(*, goal: str, context: str, constraints: dict, workspace_id: int | None) -> dict:
    result = build_graph().invoke(
        {"goal": goal, "context": context, "constraints": constraints, "workspace_id": workspace_id}
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


def _run_model(*, goal: str, context: str, constraints: dict, provider: str, model_name: str, workspace_id: int | None) -> dict:
    """Use the same tool-calling shape as agent_lab without terminal interaction."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.tools import tool
    from langgraph.graph import MessagesState
    from langgraph.prebuilt import ToolNode

    summary = get_form_summary(workspace_id=workspace_id)

    @tool
    def get_form_summary_tool() -> dict:
        """取得 Neon 已匯入表單的筆數與允許數值欄位統計，不含逐筆資料。"""
        return summary

    tools = [get_form_summary_tool]
    model = _model_for(provider, model_name).bind_tools(tools)

    def call_agent(state: MessagesState) -> dict:
        response = model.invoke([
            SystemMessage(
                content=(
                    "你是行銷分析助理，必須先呼叫 get_form_summary_tool，"
                    "再以繁體中文說明資料。只引用工具摘要，不編造數字。"
                    "test、temp 尚無業務定義，不可猜成偏好。資料不足時明確說明。"
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
        "target_audience": "目前欄位未定義受眾偏好",
        "content_direction": final_text,
        "reason": f"模型已讀取 Neon 的 {summary['response_count']} 筆回覆摘要。",
        "expected_metrics": ["response_count"],
        "goal": goal,
        "context": context,
        "constraints": constraints,
        "data_source": summary["source"],
        "form_summary": summary,
        "summary_id": summary["summary_id"],
        "tool_called": True,
    }


def run_agent(*, goal: str, context: str, constraints: dict, provider: str = "local", model_name: str = "deterministic-langgraph", workspace_id: int | None = None) -> dict:
    """Run a bounded Agent graph; model credentials stay in worker-only settings."""
    if provider == "local":
        return _run_local(goal=goal, context=context, constraints=constraints, workspace_id=workspace_id)
    return _run_model(
        goal=goal, context=context, constraints=constraints,
        provider=provider, model_name=model_name, workspace_id=workspace_id,
    )
