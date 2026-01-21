import asyncio
import json
import os
import websockets
from dotenv import load_dotenv


load_dotenv()

DG_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&encoding=mulaw"
    "&sample_rate=8000"
    "&channels=1"
    "&vad_events=true"
    "&endpointing=100"
    "&utterance_end_ms=1000"
    "&punctuate=true"
    "&interim_results=true"
)

HEADERS = {"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}


async def connect_stt(on_final):
    """Open a Deepgram streaming connection and return feed + closer."""
    ws = await websockets.connect(DG_URL, extra_headers=HEADERS, ping_interval=None)
    print("[stt] connected to Deepgram")
    send_q: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def sender():
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(send_q.get(), timeout=5)
                except asyncio.TimeoutError:
                    chunk = bytes([0xFF]) * 160
                if chunk is None:
                    await ws.close(code=1000)
                    break
                await ws.send(chunk)
        except websockets.ConnectionClosed as e:
            print(f"[stt] sender closed code={e.code} reason={e.reason}")
            return
        
        #Deepgram return format
        #     {
        #   "is_final": false,
        #   "channel": {
        #     "alternatives": [
        #       {"transcript": "text", "confidence": 0.85}
        #     ]
        #   }
        # }
    async def receiver():
        try:
            async for msg in ws:
                if not msg:
                    continue
                data = json.loads(msg)
                if data.get("type")=="SpeechStarted":
                    await on_speech_started()
                if data.get("is_final"):
                    text = data["channel"]["alternatives"][0].get("transcript", "")
                    if text:
                        print(f"[stt] final transcript: {text}")
                        await on_final(text)
                else:
                    msg_type = data.get("type")
                    if msg_type:
                        print(f"[stt] recv type={msg_type} msg={data}")
        except websockets.ConnectionClosed as e:
            print(f"[stt] Deepgram connection closed code={e.code} reason={e.reason}")
            return

    send_task = asyncio.create_task(sender(), name="deepgram-sender")
    recv_task = asyncio.create_task(receiver(), name="deepgram-receiver")

    async def close():
        await send_q.put(None)
        await asyncio.gather(send_task, recv_task, return_exceptions=True)
        if not ws.closed:
            await ws.close(code=1000)
        print("[stt] closed")

    return send_q, close
