import os, websockets, json, asyncio
from dotenv import load_dotenv

load_dotenv()

TTS_WS_URL = (
    f"wss://api.deepgram.com/v1/speak"
    f"?model={os.getenv('VOICE_MODEL')}"
    f"&encoding=mulaw"
    f"&sample_rate=8000"
)

HEADERS = {"Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}"}


class TTSConnection:    
    def __init__(self):
        self.ws = None
        self.monitor_task = None
        self.connection_closed = False
        
    async def establish_connection(self):
        try:
            ws = await asyncio.wait_for(
                websockets.connect(TTS_WS_URL, extra_headers=HEADERS),
                timeout=10.0
            )
            print("[tts] Connected to Deepgram TTS WebSocket")
            return ws
        except asyncio.TimeoutError:
            print("[tts] Timeout connecting to Deepgram TTS")
            return None
        except Exception as e:
            print(f"[tts] Failed to connect: {e}")
            return None
    
    async def monitor_connection(self):
        consecutive_failures = 0
        max_failures = 3
        
        while consecutive_failures < max_failures and not self.connection_closed:
            if self.ws is None or self.ws.state is websockets.protocol.State.CLOSED:
                print("[tts] Re-establishing connection...")
                result = await self.establish_connection()
                if result is None:
                    consecutive_failures += 1
                    print(f"[tts] Connection failed (attempt {consecutive_failures}/{max_failures})")
                    if consecutive_failures >= max_failures:
                        print("[tts] Max failures reached - stopping reconnection")
                        break
                else:
                    self.ws = result
                    consecutive_failures = 0
            await asyncio.sleep(1)
    
    async def start(self):
        self.ws = await self.establish_connection()
        if self.ws:
            self.monitor_task = asyncio.create_task(self.monitor_connection())
        return self.ws is not None
    
    async def cleanup(self):
        self.connection_closed = True
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.ws:
            try:
                await self.ws.send(json.dumps({"type": "Close"}))
                print("[tts] Sent Close message")
            except Exception as e:
                print(f"[tts] Error sending Close: {e}")
            
            try:
                await self.ws.close()
                print("[tts] WebSocket closed")
            except Exception as e:
                print(f"[tts] Error closing WebSocket: {e}")
            
            self.ws = None
    
    async def handle_interruption(self):
        """Handle user interruption - clear TTS buffer"""
        if self.ws and self.ws.state is websockets.protocol.State.OPEN:
            try:
                await self.ws.send(json.dumps({"type": "Clear"}))
                print("[tts] Sent Clear message - discarding buffered audio")
            except Exception as e:
                print(f"[tts] Error sending Clear: {e}")


async def speak_stream(tts_conn: TTSConnection, text: str):
    if not tts_conn or not tts_conn.ws:
        print("[tts] No active connection")
        return
    
    try:
        wait_start = asyncio.get_event_loop().time()
        while tts_conn.ws is None or tts_conn.ws.state is websockets.protocol.State.CLOSED:
            await asyncio.sleep(0.1)
            if asyncio.get_event_loop().time() - wait_start > 5:
                print("[tts] Timeout waiting for connection")
                return
        
        await tts_conn.ws.send(json.dumps({
            "type": "Speak",
            "text": text
        }))
        
        await tts_conn.ws.send(json.dumps({
            "type": "Flush"
        }))
        
        async for msg in tts_conn.ws:
            if isinstance(msg, bytes):
                yield msg
            else:
                data = json.loads(msg)
                msg_type = data.get("type")
                
                if msg_type == "Flushed":
                    break
                elif msg_type == "Metadata":
                    print(f"[tts] Metadata: {data.get('model_name')}")
                elif msg_type == "Warning":
                    print(f"[tts] Warning: {data.get('description')}")
                    
    except Exception as e:
        print(f"[tts] Stream error: {e}")
        raise
