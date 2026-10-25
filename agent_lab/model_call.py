"""LangChain 第一次模型呼叫：輸入一個 Gemini API key，取得文字回覆。"""

import getpass
import os

from langchain_google_genai import ChatGoogleGenerativeAI


def main() -> None:
    api_key = getpass.getpass("請輸入 Google AI Studio API key（輸入時不會顯示）：")
    if not api_key.strip():
        raise SystemExit("沒有輸入 API key，程式已停止。")

    os.environ["GOOGLE_API_KEY"] = api_key.strip()

    model = ChatGoogleGenerativeAI(model="gemini-3.8-flash")
    response = model.invoke("請用繁體中文簡短說明，你可以如何協助 NTUMaker 規劃活動宣傳。")
    print("\n模型回覆：\n")
    print(response.content)


if __name__ == "__main__":
    main()
