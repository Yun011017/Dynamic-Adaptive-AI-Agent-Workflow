"""LangChain 工具呼叫練習：切換模型分析測試報名摘要。"""

import getpass
import os

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from google.genai.errors import APIError as GeminiAPIError
from openai import APIError as OpenAIAPIError


# 想切換模型時，先改這一區：
# MODEL_PROVIDER 可填 "gemini" 或 "openai"。
# 同一服務內要換型號，只需修改該服務的模型名稱。
MODEL_PROVIDER = "gemini"
GEMINI_MODEL = "gemini-3.5-flash-lite"
OPENAI_MODEL = "gpt-6-luna"


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
            reasoning_effort="none",
            timeout=20,
            max_retries=0,
        ), OPENAI_MODEL

    raise SystemExit('MODEL_PROVIDER 請設定為 "gemini" 或 "openai"。')


def main() -> None:
    model, model_name = build_model()
    agent = create_agent(
        model=model,
        tools=[get_form_summary],
        system_prompt=(
            "你是 NTUMaker 的行銷分析助理，請用繁體中文。"
            "回答前必須呼叫 get_form_summary 取得資料。"
            "只能根據工具回傳的資料提出建議；清楚標示這是虛構測試資料。"
            "本期平台範圍是 Instagram 與 Google Forms/Sheets；"
            "不要聲稱已連接真實表單、已發布貼文，或加入其他平台。"
        ),
    )

    print(
        f"\n已選擇 {MODEL_PROVIDER} / {model_name}，正在呼叫模型；回應可能需要數秒。",
        flush=True,
    )
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "請分析報名摘要，提出一項 Instagram 宣傳建議，並說明資料依據。"}]}
        )
    except GeminiAPIError as error:
        raise SystemExit(f"Gemini API 回報錯誤（{error.code}）：{error.message}") from None
    except OpenAIAPIError as error:
        raise SystemExit(f"OpenAI API 回報錯誤：{error}") from None

    print("\n工具呼叫紀錄：")
    for message in result["messages"]:
        if getattr(message, "tool_calls", None):
            for call in message.tool_calls:
                print(f"- Agent 呼叫工具：{call['name']}")
        if getattr(message, "type", None) == "tool":
            print(f"- 工具回傳資料：{message.content}")

    print("\nAgent 最終回答：\n")
    final_content = result["messages"][-1].content
    if isinstance(final_content, str):
        print(final_content)
    else:
        # 新版 LangChain 可能以多個內容區塊回傳文字與中繼資料；只印文字。
        text_parts = [
            block["text"]
            for block in final_content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        print("\n".join(text_parts) if text_parts else final_content)


if __name__ == "__main__":
    main()
