import json
from pathlib import Path
from app.llm_client import  generate_chat_stream,generate_chat
from app.tools.reservation_tools import (update_context_from_text,compute_availability,select_room,finalize_booking)

FLOW = json.loads(Path("app/flow.json").read_text())
SYSTEM_PROMPT = Path("app/system_prompt.txt").read_text()


def tool_spec():
    return [
        {
            "type": "function",
            "function": {
                "name": "get_availability",
                "description": "List available rooms given guest count, beds, and lounge preference.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "guests": {"type": "integer", "description": "Number of guests."},
                        "beds": {
                            "type": "integer",
                            "description": "Beds requested (1 for single, 2 for double/twin).",
                            "nullable": True,
                        },
                        "lounge": {
                            "type": "boolean",
                            "description": "Whether lounge access is requested.",
                            "nullable": True,
                        },
                        "nights": {
                            "type": "integer",
                            "description": "Number of nights.",
                            "nullable": True,
                        },
                    },
                    "required": ["guests"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "choose_room",
                "description": "Select a room by id after presenting options.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room_id": {"type": "string", "description": "Room id to select."},
                    },
                    "required": ["room_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finalize_booking",
                "description": "Confirm booking with guest name and selected room id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "guest_name": {"type": "string", "description": "Guest full name."},
                        "room_id": {"type": "string", "description": "Selected room id."},
                    },
                    "required": ["guest_name", "room_id"],
                },
            },
        },
    ]


class ToolRuntime:
    def __init__(self, context: dict):
        self.context = context

    def get_availability(self, guests: int, beds=None, lounge=None, nights=None):
        self.context["guests"] = guests
        if beds is not None:
            self.context["beds"] = beds
        if lounge is not None:
            self.context["lounge"] = lounge
        if nights is not None:
            self.context["nights"] = nights
        rooms = compute_availability(self.context)
        self.context["available_rooms"] = rooms
        return {
            "available_rooms": rooms,
            "context": self.context,
        }

    def choose_room(self, room_id: str):
        picked = select_room(self.context, room_id)
        return {
            "selected_room": picked,
            "context": self.context,
        }

    def finalize_booking(self, guest_name: str, room_id: str):
        self.context["guest_name"] = guest_name
        self.context["selected_room"] = room_id
        booking_details = finalize_booking(self.context)
        if booking_details:
            return booking_details
        return {
            "error": "Failed to create booking",
            "context": self.context,
        }


class HotelAgent:
    def __init__(self):
        self.context = {
            "intent": None,
            "check_in": None,
            "nights": None,
            "date": None,
            "guests": None,
            "beds": None,
            "lounge": None,
            "available_rooms": [],
            "selected_room": None,
            "guest_name": None,
            "booking_id": None,
        }
        self.booking_confirmed = False
        self.asked_anything_else = False
        self.completed = False
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Use the provided tools to fetch availability, choose a room, and finalize bookings. Always keep responses concise, spoken style.",
            },
        ]
        self.tools = tool_spec()
        self.tool_runtime = ToolRuntime(self.context)

    # async def handle(self, user_text: str) -> str:
    #     update_context_from_text(user_text, self.context)

    #     self.messages.append({"role": "user", "content": user_text})

    #     while True:
    #         res = await generate_chat(self.messages, tools=self.tools)
    #         msg = res.choices[0].message

    #         tool_calls = getattr(msg, "tool_calls", None)
    #         if tool_calls:
    #             def _tool_call_dict(tc):
    #                 return {
    #                     "id": tc.id,
    #                     "type": tc.type,
    #                     "function": {
    #                         "name": tc.function.name,
    #                         "arguments": tc.function.arguments,
    #                     },
    #                 }

    #             self.messages.append(
    #                 {
    #                     "role": "assistant",
    #                     "content": msg.content or "",
    #                     "tool_calls": [_tool_call_dict(tc) for tc in tool_calls],
    #                 }
    #             )

    #             for tc in tool_calls:
    #                 name = tc.function.name
    #                 args = json.loads(tc.function.arguments or "{}")
    #                 func = getattr(self.tool_runtime, name, None)
    #                 if not func:
    #                     result = {"error": f"Unknown tool {name}"}
    #                 else:
    #                     try:
    #                         result = func(**args)
    #                     except Exception as e:
    #                         result = {"error": str(e)}

    #                 self.messages.append(
    #                     {
    #                         "role": "tool",
    #                         "tool_call_id": tc.id,
    #                         "name": name,
    #                         "content": json.dumps(result),
    #                     }
    #                 )
    #                 if isinstance(result, dict) and result.get("booking_id"):
    #                     self.booking_confirmed = True
    #             continue

    #         reply = msg.content or ""
    #         self.messages.append({"role": "assistant", "content": reply})
            
    #         if self.context.get("booking_id") and not self.booking_confirmed:
    #             self.booking_confirmed = True
            
    #         lower_reply = reply.lower()
    #         if self.booking_confirmed and ("anything else" in lower_reply or "help you with" in lower_reply):
    #             self.asked_anything_else = True
            
    #         lower_text = user_text.lower()
    #         decline_keywords = ["no", "nope", "nah", "nothing", "that's all", "that is all", "no thanks", "i'm good", "im good", "all set", "that'll be all"]
    #         if self.asked_anything_else and any(kw in lower_text for kw in decline_keywords):
    #             self.completed = True
    #             print("[agent] User declined further help; marking conversation complete")
            
    #         return reply

    async def handle_stream(self, user_text: str, sequence_id: int = 0, is_valid_fn=None):
        """Stream LLM responses in chunks for low-latency output with interruption support"""
        update_context_from_text(user_text, self.context)
        self.messages.append({"role": "user", "content": user_text})

        while True:
            res = await generate_chat(self.messages, tools=self.tools, max_tokens=800)
            msg = res.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            
            if tool_calls:
                def _tool_call_dict(tc):
                    return {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }

                self.messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [_tool_call_dict(tc) for tc in tool_calls],
                    }
                )

                for tc in tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    func = getattr(self.tool_runtime, name, None)
                    if not func:
                        result = {"error": f"Unknown tool {name}"}
                    else:
                        try:
                            result = func(**args)
                        except Exception as e:
                            result = {"error": str(e)}

                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": name,
                            "content": json.dumps(result),
                        }
                    )
                    if isinstance(result, dict) and result.get("booking_id"):
                        self.booking_confirmed = True
                continue 

            buffer = ""
            full_response = ""
            
            async for chunk in generate_chat_stream(self.messages, tools=None):
                # Check if interrupted
                if is_valid_fn and not is_valid_fn(sequence_id):
                    print(f"[agent] Sequence {sequence_id} interrupted - stopping LLM stream")
                    break
                
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                
                if content:
                    buffer += content
                    full_response += content
                    
                    if buffer.endswith((".", "?", "!", "\n")) and len(buffer.strip()) > 5:
                        # Check again before yielding
                        if is_valid_fn and not is_valid_fn(sequence_id):
                            print(f"[agent] Sequence {sequence_id} interrupted before yield")
                            break
                        yield buffer.strip()
                        buffer = ""
            
            # Check if interrupted before final yield
            if is_valid_fn and not is_valid_fn(sequence_id):
                print(f"[agent] Sequence {sequence_id} interrupted - discarding final buffer")
                break
            
            if buffer.strip():
                yield buffer.strip()
            
            self.messages.append({"role": "assistant", "content": full_response})
            
            if self.context.get("booking_id") and not self.booking_confirmed:
                self.booking_confirmed = True
            
            lower_reply = full_response.lower()
            if self.booking_confirmed and ("anything else" in lower_reply or "help you with" in lower_reply):
                self.asked_anything_else = True
            
            lower_text = user_text.lower()
            decline_keywords = ["no", "nope", "nah", "nothing", "that's all", "that is all", "no thanks", "i'm good", "im good", "all set", "that'll be all"]
            if self.asked_anything_else and any(kw in lower_text for kw in decline_keywords):
                self.completed = True
                print("[agent] User declined further help; marking conversation complete")
            
            break  
