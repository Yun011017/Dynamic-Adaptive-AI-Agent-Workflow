"""LangChain 工具呼叫練習：切換模型分析測試報名摘要。"""

import getpass
import os
from typing import Annotated, NotRequired, TypedDict
from uuid import uuid4

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain.tools import tool
from google.genai.errors import APIError as GeminiAPIError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from openai import APIError as OpenAIAPIError
from anthropic import APIError as AnthropicAPIError


# 想切換模型時，先改這一區：
# MODEL_PROVIDER 可填 "gemini"、"openai" 或 "claude"。
# 也可以在啟動程式時設定環境變數 MODEL_PROVIDER；預設使用 Gemini。
# 同一服務內要換型號，只需修改該服務的模型名稱。
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "gemini").strip().lower()
GEMINI_MODEL = "gemini-3.5-flash-lite"
OPENAI_MODEL = "gpt-5-nano"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
QUESTION = "請分析報名摘要，提出一項 Instagram 宣傳建議，並說明資料依據。"
SYSTEM_PROMPT = (
    "你是 NTUMaker 的行銷分析助理，請用繁體中文。"
    "回答前必須呼叫 get_form_summary 取得資料。"
    "只能根據工具回傳的資料提出建議；清楚標示這是虛構測試資料。"
    "本期平台範圍是 Instagram 與 Google Forms/Sheets；"
    "不要聲稱已連接真實表單、已發布貼文，或加入其他平台。"
)


class AgentState(TypedDict):
    """LangGraph 在每個節點間傳遞的共享狀態，目前保存完整訊息歷程。"""

    messages: Annotated[list[AnyMessage], add_messages]
    review_status: NotRequired[str]
    approved_draft: NotRequired[str]


@tool
def get_form_summary() -> dict:
    """取得 NTUMaker 測試活動的彙整報名資料，不含個人資料。"""
    return {
        "資料來源": "虛構測試資料，並非真實 Google 表單",
        "活動": "新手創客工作坊",
        "回覆人數": 30,
        "報名者類型": {"第一次參加": 18, "曾參加過": 12},
        "內容偏好": {"動手實作": 20, "專題分享": 7, "社團介紹": 3},
    }


def build_model():
    """依照上方設定選擇服務、讀取對應金鑰並建立模型。"""
    if MODEL_PROVIDER == "gemini":
        api_key = getpass.getpass(
            "請輸入 Google AI Studio API key（輸入時不會顯示）："
        )
        if not api_key.strip():
            raise SystemExit("沒有輸入 API key，程式已停止。")
        os.environ["GOOGLE_API_KEY"] = api_key.strip()
        return ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            request_timeout=20,
            retries=0,
        ), GEMINI_MODEL

    if MODEL_PROVIDER == "openai":
        api_key = getpass.getpass(
            "請輸入 OpenAI API key（輸入時不會顯示；API 呼叫可能會收費）："
        )
        if not api_key.strip():
            raise SystemExit("沒有輸入 API key，程式已停止。")
        os.environ["OPENAI_API_KEY"] = api_key.strip()
        return ChatOpenAI(
            model=OPENAI_MODEL,
            use_responses_api=True,
            timeout=20,
            max_retries=0,
        ), OPENAI_MODEL

    if MODEL_PROVIDER == "claude":
        api_key = getpass.getpass(
            "請輸入 Anthropic Claude API key（輸入時不會顯示；API 呼叫可能會收費）："
        )
        if not api_key.strip():
            raise SystemExit("沒有輸入 API key，程式已停止。")
        os.environ["ANTHROPIC_API_KEY"] = api_key.strip()
        return ChatAnthropic(
            model=CLAUDE_MODEL,
            timeout=20,
            max_retries=0,
        ), CLAUDE_MODEL

    raise SystemExit(
        'MODEL_PROVIDER 請設定為 "gemini"、"openai" 或 "claude"。'
    )


def build_graph(model):
    """建立 Agent、工具與草稿人工審核流程，並以記憶體保存暫停狀態。"""
    tools = [get_form_summary]
    model_with_tools = model.bind_tools(tools)

    def call_agent(state: AgentState) -> dict:
        response = model_with_tools.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
        )
        return {"messages": [response]}

    def route_after_agent(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return "human_review"

    def human_review(state: AgentState) -> dict:
        draft = state["messages"][-1].content
        if not isinstance(draft, str):
            draft = "\n".join(
                block["text"]
                for block in draft
                if isinstance(block, dict) and block.get("type") == "text"
            )

        decision = interrupt(
            {
                "draft": draft,
                "choices": ["approve", "edit", "reject"],
                "message": "請核准、修改或拒絕這份草稿。",
            }
        )
        if decision["action"] == "approve":
            return {"review_status": "approved", "approved_draft": draft}
        if decision["action"] == "edit":
            return {
                "review_status": "edited_and_approved",
                "approved_draft": decision["draft"],
            }
        return {"review_status": "rejected"}

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_agent)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("human_review", human_review)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "human_review": "human_review"},
    )
    workflow.add_edge("tools", "agent")
    workflow.add_edge("human_review", END)
    return workflow.compile(checkpointer=InMemorySaver())


def collect_review_decision(draft: str) -> dict:
    """在終端機收集草稿審核結果；修改內容以空白行結束。"""
    print("\n待審核草稿：\n")
    print(draft)
    print("\n請選擇：a 核准、e 修改後核准、r 拒絕")
    while True:
        choice = input("你的選擇 [a/e/r]：").strip().lower()
        if choice == "a":
            return {"action": "approve"}
        if choice == "r":
            return {"action": "reject"}
        if choice == "e":
            print("請輸入修改後的完整草稿；輸入空白行即可結束：")
            lines = []
            while line := input():
                lines.append(line)
            edited_draft = "\n".join(lines).strip()
            if edited_draft:
                return {"action": "edit", "draft": edited_draft}
            print("修改內容不可空白，請重新選擇。")
            continue
        print("請輸入 a、e 或 r。")


def main() -> None:
    model, model_name = build_model()
    graph = build_graph(model)
    config = {"configurable": {"thread_id": f"local-review-{uuid4()}"}}

    print(
        f"\n已選擇 {MODEL_PROVIDER} / {model_name}，正在呼叫模型；回應可能需要數秒。",
        flush=True,
    )
    try:
        result = graph.invoke(
            {"messages": [HumanMessage(content=QUESTION)]}, config=config
        )
        pending = result.get("__interrupt__", ())
        if pending:
            decision = collect_review_decision(pending[0].value["draft"])
            result = graph.invoke(Command(resume=decision), config=config)
    except GeminiAPIError as error:
        raise SystemExit(f"Gemini API 回報錯誤（{error.code}）：{error.message}") from None
    except OpenAIAPIError as error:
        raise SystemExit(f"OpenAI API 回報錯誤：{error}") from None
    except AnthropicAPIError as error:
        raise SystemExit(f"Anthropic Claude API 回報錯誤：{error}") from None

    print("\n工具呼叫紀錄：")
    for message in result["messages"]:
        if getattr(message, "tool_calls", None):
            for call in message.tool_calls:
                print(f"- Agent 呼叫工具：{call['name']}")
        if getattr(message, "type", None) == "tool":
            print(f"- 工具回傳資料：{message.content}")

    if result.get("review_status") == "rejected":
        print("\n草稿已拒絕，流程結束；沒有發布任何內容。")
        return

    print("\n人工審核後的草稿：\n")
    print("審核結果：", result["review_status"])
    print(result["approved_draft"])


if __name__ == "__main__":
    main()
