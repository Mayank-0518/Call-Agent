import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL = os.getenv("LLM_MODEL")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)


async def generate_chat(messages, tools=None, temperature=0.2, max_tokens=400):
    try:
        res = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools or None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return res
    except Exception as e:
        status = getattr(e, "status_code", None)
        body = None
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.text
                status = status or getattr(e.response, "status_code", None)
            except Exception:
                body = repr(e.response)
        print(
            f"[llm] request failed model={MODEL} base_url={BASE_URL} status={status} body={body} err={e}"
        )
        raise
