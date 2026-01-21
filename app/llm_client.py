import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL") or "https://integrate.api.nvidia.com/v1"
MODEL = os.getenv("LLM_MODEL") or "openai/gpt-oss-120b"

if not API_KEY:
    print("WARNING: OPENAI_API_KEY is not set. LLM calls will fail.")
    client = None
else:
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)


async def generate_chat(messages, tools=None, temperature=0.2, max_tokens=400):
    """Non-streaming chat completion (for tool calls)"""
    if not client:
        raise RuntimeError("OPENAI_API_KEY is not configured")
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


async def generate_chat_stream(messages, tools=None, temperature=0.2, max_tokens=400):
    """Stream LLM response chunks as they arrive"""
    if not client:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    try:
        stream = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools or None,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            yield chunk
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
            f"[llm] stream failed model={MODEL} base_url={BASE_URL} status={status} body={body} err={e}"
        )
        raise
