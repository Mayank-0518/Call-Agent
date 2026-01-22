import asyncio, json, base64, os
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState
from app.agent import HotelAgent
from app.stt import connect_stt
from app.tts import TTSConnection, speak_stream
from app.interruption_manager import InterruptionManager

router = APIRouter()
ECHO_BACK = os.getenv("ECHO_BACK", "false").lower() == "true"


@router.websocket("/ws/twilio")
async def twilio_ws(ws: WebSocket):
    await ws.accept()
    print("[twilio] websocket accepted")

    agent = HotelAgent()
    stream_sid: str | None = None
    bg_tasks: set[asyncio.Task] = set()
    interruption_mgr = InterruptionManager()

    greeted = False
    call_ended = False
    pending_marks = {}  
    
    tts_conn = TTSConnection()
    tts_ready = await tts_conn.start()
    if not tts_ready:
        print("[twilio] Failed to establish TTS connection")
        await ws.close()
        return
    
    async def on_speech_started():
        """Called when user starts speaking - interrupt agent"""
        nonlocal audio_buffer
        print(f"[twilio] SpeechStarted detected, is_agent_speaking={interruption_mgr.is_agent_speaking}")
        if interruption_mgr.is_agent_speaking:
            print("[twilio] 🔴 User interrupted agent!")
            interruption_mgr.interrupt()
            
            pending_marks.clear()
            
            # Clear audio buffer 
            audio_buffer.clear()
            print("[twilio] Cleared audio buffer")
            
            await tts_conn.handle_interruption()
            if stream_sid:
                try:
                    await ws.send_text(json.dumps({
                        "event": "clear",
                        "streamSid": stream_sid
                    }))
                    print("[twilio] Sent clear to Twilio")
                except Exception as e:
                    print(f"[twilio] Failed to send clear: {e}")
    
    async def on_final(text: str):
        nonlocal call_ended
        if call_ended:
            return
        
        # Start new response sequence
        sequence_id = interruption_mgr.start_response()
            
        print(f"[twilio] transcript: {text} (sequence_id={sequence_id})")
        try:
            async for llm_chunk in agent.handle_stream(
                text, 
                sequence_id=sequence_id, 
                is_valid_fn=interruption_mgr.is_valid
            ):
                # Check if interrupted
                if not interruption_mgr.is_valid(sequence_id):
                    print(f"[twilio] Sequence {sequence_id} stopped by interruption")
                    break
                    
                if call_ended:
                    break
                
                print(f"[twilio] LLM chunk: {llm_chunk}")
                
                async for audio_chunk in speak_stream(tts_conn, llm_chunk):
                    if not interruption_mgr.is_valid(sequence_id):
                        print(f"[twilio] Audio interrupted for sequence {sequence_id}")
                        break
                        
                    if call_ended:
                        break
                    await stream_audio_to_twilio(audio_chunk, sequence_id)
                
                if audio_buffer and stream_sid and interruption_mgr.is_valid(sequence_id):
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
                    
            if stream_sid and interruption_mgr.is_valid(sequence_id):
                mark_name = f"end-{sequence_id}"
                pending_marks[mark_name] = sequence_id
                try:
                    await ws.send_text(json.dumps({
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": mark_name}
                    }))
                    print(f"[twilio] Sent end mark for sequence {sequence_id}")
                except Exception:
                    interruption_mgr.finish_response(sequence_id)
            else:
                interruption_mgr.finish_response(sequence_id)
                print(f"[twilio] Response sequence {sequence_id} finished (interrupted or no stream)")
                
        except Exception as e:
            print(f"[twilio] error in on_final: {e}")
            import traceback
            traceback.print_exc()
            interruption_mgr.finish_response(sequence_id)

    send_q, close_stt = await connect_stt(on_final, on_speech_started)
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
    
    async def stream_audio_to_twilio(audio: bytes, sequence_id: int):
        nonlocal stream_sid
        if not stream_sid:
            return
        
        for frame in buffer_and_yield_frames(audio):
            if not interruption_mgr.is_valid(sequence_id):
                print(f"[twilio] Stopping frame send - sequence {sequence_id} invalidated")
                break
                
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
                    greeting_seq = interruption_mgr.start_response()
                    try:
                        async for audio_chunk in speak_stream(tts_conn, greeting):
                            if not interruption_mgr.is_valid(greeting_seq):
                                break
                            await stream_audio_to_twilio(audio_chunk, greeting_seq)
                        
                        # Send mark to know when audio finishes playing
                        mark_name = f"end-{greeting_seq}"
                        pending_marks[mark_name] = greeting_seq
                        await ws.send_text(json.dumps({
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": mark_name}
                        }))
                        print(f"[twilio] sent startup greeting + mark (streamed)")
                    except Exception as e:
                        print(f"[twilio] greeting TTS failed: {e}")
                        interruption_mgr.finish_response(greeting_seq)
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

            elif evt == "mark":
                mark_name = msg.get("mark", {}).get("name", "")
                if mark_name in pending_marks:
                    seq_id = pending_marks.pop(mark_name)
                    interruption_mgr.finish_response(seq_id)
                    print(f"[twilio] Mark received - audio playback complete for sequence {seq_id}")

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
