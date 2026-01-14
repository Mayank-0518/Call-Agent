import asyncio, json, base64, os
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState
from app.agent import HotelAgent
from app.stt import connect_stt
from app.tts import speak

router = APIRouter()
ECHO_BACK = os.getenv("ECHO_BACK", "false").lower() == "true"


@router.websocket("/ws/twilio")
async def twilio_ws(ws: WebSocket):
    await ws.accept()
    print("[twilio] websocket accepted")

    agent = HotelAgent()
    stream_sid: str | None = None
    bg_tasks: set[asyncio.Task] = set()

    greeted = False
    call_ended = False
    
    async def on_final(text: str):
        nonlocal call_ended
        if call_ended:
            return
            
        print(f"[twilio] transcript: {text}")
        try:
            reply = await agent.handle(text)
            safe_reply = reply or "I didn't catch that. Could you please repeat?"
            print(f"[twilio] llm reply: {safe_reply}")
            audio = await speak(safe_reply)
            
            if agent.completed:
                call_ended = True
                await stream_audio_to_twilio(audio)
                print("[twilio] goodbye message sent; waiting for audio to complete")
                await asyncio.sleep(len(audio) / 8000 + 2)
                print("[twilio] sending stop event to end call")
                
                try:
                    await ws.send_text(json.dumps({"event": "stop", "streamSid": stream_sid}))
                except Exception as e:
                    print(f"[twilio] stop event failed: {e}")
                
                await close_stt()
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close()
                return

            bg_tasks.add(asyncio.create_task(stream_audio_to_twilio(audio)))
        except Exception as e:
            print(f"[twilio] error in on_final: {e}")

    send_q, close_stt = await connect_stt(on_final)
    print("[twilio] connected to Deepgram STT")

    async def stream_audio_to_twilio(audio: bytes):
        nonlocal stream_sid
        if not stream_sid:
            print("[twilio] stream_audio_to_twilio called before streamSid; skipping")
            return
        payload = base64.b64encode(audio).decode()
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload},
                    }
                )
            )
            await ws.send_text(
                json.dumps(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": "audio-complete"},
                    }
                )
            )
        except Exception as e:
            print(f"[twilio] send media failed: {e}")

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                print("[twilio] websocket disconnect")
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[twilio] non-json frame: {raw[:50]}")
                continue

            evt = msg.get("event")
            if evt == "start":
                stream_sid = msg.get("start", {}).get("streamSid")
                print(f"[twilio] start streamSid={stream_sid}")
                await send_q.put(bytes([0xFF]) * 160)
                if not greeted:
                    greeted = True
                    greeting = (
                        "Hi, I am Ashish, your hotel enquiry agent. "
                        "I can help with availability, rates, and reservations. "
                        "How may I assist you today?"
                    )
                    try:
                        audio = await speak(greeting)
                        print(f"[twilio] sent startup greeting bytes={len(audio)}")
                        bg_tasks.add(asyncio.create_task(stream_audio_to_twilio(audio)))
                    except Exception as e:
                        print(f"[twilio] greeting TTS failed: {e}")
            elif evt == "media":
                m = msg.get("media", {})
                track = m.get("track", "inbound")
                if track != "inbound":
                    continue 
                payload = m.get("payload")
                if not payload:
                    continue
                audio = base64.b64decode(payload)
                await send_q.put(audio)
                if ECHO_BACK:
                    bg_tasks.add(asyncio.create_task(stream_audio_to_twilio(audio)))

            elif evt == "stop":
                print("[twilio] stop event")
                break

    finally:
        print("[twilio] closing STT and websocket")
        await close_stt()
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except Exception as e:
                print(f"[twilio] ws.close suppressed error: {e}")
