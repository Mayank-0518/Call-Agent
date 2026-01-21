import asyncio, json, base64, os
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState
from app.agent import HotelAgent
from app.stt import connect_stt
from app.tts import TTSConnection, speak_stream

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
    
    tts_conn = TTSConnection()
    tts_ready = await tts_conn.start()
    if not tts_ready:
        print("[twilio] Failed to establish TTS connection")
        await ws.close()
        return
    
    async def on_final(text: str):
        nonlocal call_ended
        if call_ended:
            return
            
        print(f"[twilio] transcript: {text}")
        try:
            async for llm_chunk in agent.handle_stream(text):
                if call_ended:
                    break
                
                print(f"[twilio] LLM chunk: {llm_chunk}")
                
                async for audio_chunk in speak_stream(tts_conn, llm_chunk):
                    if call_ended:
                        break
                    await stream_audio_to_twilio(audio_chunk)
                
                # Flush any remaining buffered audio after each LLM chunk
                if audio_buffer and stream_sid:
                    payload = base64.b64encode(bytes(audio_buffer)).decode()
                    try:
                        await ws.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": payload}
                        }))
                    except Exception:
                        pass
                    audio_buffer.clear()
                
                if agent.completed:
                    call_ended = True
                    print("[twilio] conversation complete; closing call")
                    await asyncio.sleep(0.5)
                    
                    try:
                        await ws.send_text(json.dumps({"event": "stop", "streamSid": stream_sid}))
                    except Exception as e:
                        print(f"[twilio] stop event failed: {e}")
                    
                    await close_stt()
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.close()
                    break
                    
        except Exception as e:
            print(f"[twilio] error in on_final: {e}")
            import traceback
            traceback.print_exc()

    send_q, close_stt = await connect_stt(on_final)
    print("[twilio] connected to Deepgram STT")

    audio_buffer = bytearray()
    
    def buffer_and_yield_frames(audio: bytes):
        """Buffer audio and yield aligned 160-byte frames for Twilio."""
        nonlocal audio_buffer
        audio_buffer.extend(audio)
        
        frames = []
        while len(audio_buffer) >= 160:
            frames.append(bytes(audio_buffer[:160]))
            audio_buffer = audio_buffer[160:]
        
        return frames
    
    async def stream_audio_to_twilio(audio: bytes):
        nonlocal stream_sid
        if not stream_sid:
            return
        
        for frame in buffer_and_yield_frames(audio):
            payload = base64.b64encode(frame).decode()
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
            except Exception as e:
                print(f"[twilio] send media failed: {e}")
                break

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
                        "Hi, I am Alisha, your hotel enquiry agent. "
                        "I can help with availability, rates, and reservations. "
                        "How may I assist you today?"
                    )
                    try:
                        # Use streaming TTS for greeting with persistent connection
                        async for audio_chunk in speak_stream(tts_conn, greeting):
                            await stream_audio_to_twilio(audio_chunk)
                        print(f"[twilio] sent startup greeting (streamed)")
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
        print("[twilio] closing STT, TTS and websocket")
        await close_stt()
        await tts_conn.cleanup()
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except Exception as e:
                print(f"[twilio] ws.close suppressed error: {e}")
