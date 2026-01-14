import os, httpx
from dotenv import load_dotenv

load_dotenv()

async def speak(text: str) -> bytes:
    model = os.getenv("VOICE_MODEL", "aura-2-odysseus-en")
    url = (
        f"https://api.deepgram.com/v1/speak?model={model}"
        "&encoding=mulaw&sample_rate=8000&container=none"
    )
    headers = {
        "Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, json={"text": text})
        r.raise_for_status()
        return r.content
