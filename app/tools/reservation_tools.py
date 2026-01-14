import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.data.dummy_dta import find_rooms, create_booking, ROOMS


def _parse_int(text: str) -> Optional[int]:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def update_context_from_text(text: str, ctx: Dict) -> None:
    lower = text.lower()

    if "availability" in lower or "available" in lower:
        ctx.setdefault("intent", "availability")
    if "book" in lower or "reserve" in lower or "confirm" in lower:
        ctx.setdefault("intent", "booking")
    if "price" in lower or "rate" in lower:
        ctx.setdefault("intent", "pricing")

    guests = _parse_int(lower) if "guest" in lower or "people" in lower or "person" in lower else None
    if guests:
        ctx["guests"] = guests

    beds = None
    if "single" in lower:
        beds = 1
    if "double" in lower or "two bed" in lower or "twin" in lower:
        beds = 2
    if beds:
        ctx["beds"] = beds

    if "lounge" in lower:
        ctx["lounge"] = True
    if "no lounge" in lower or "without lounge" in lower:
        ctx["lounge"] = False

    if "name is" in lower:
        parts = lower.split("name is", 1)[1].strip()
        ctx["guest_name"] = parts.split()[0].title() if parts else ctx.get("guest_name")

    if "date" in lower or re.search(r"\d{1,2}/\d{1,2}", lower):
        parsed = _parse_date(lower)
        if parsed:
            ctx["check_in"] = parsed

    nights = _parse_int(lower) if "night" in lower or "nights" in lower else None
    if nights:
        ctx["nights"] = nights

    for room in ROOMS:
        if room["id"] in lower or room["name"].lower() in lower:
            ctx["selected_room"] = room["id"]
            break


def compute_availability(ctx: Dict) -> List[Dict]:
    guests = ctx.get("guests") or 1
    beds = ctx.get("beds")
    lounge = ctx.get("lounge")
    rooms = find_rooms(guests=guests, beds=beds, lounge=lounge)
    for r in rooms:
        r["total_price"] = r["price"] * max(1, ctx.get("nights") or 1)
    return rooms


def select_room(ctx: Dict, room_id: str) -> Optional[Dict]:
    for room in ROOMS:
        if room["id"] == room_id:
            ctx["selected_room"] = room_id
            return room
    return None


def finalize_booking(ctx: Dict) -> Optional[Dict]:
    room_id = ctx.get("selected_room")
    guest_name = ctx.get("guest_name")
    if not room_id or not guest_name:
        return None
    room = next((r for r in ROOMS if r["id"] == room_id), None)
    if not room:
        return None
    booking_id = create_booking(guest_name, room)
    ctx["booking_id"] = booking_id
    
    # Return full booking details
    nights = ctx.get("nights", 1)
    total_price = room["price"] * nights
    return {
        "booking_id": booking_id,
        "guest_name": guest_name,
        "room_id": room["id"],
        "room_name": room["name"],
        "beds": room["beds"],
        "lounge": room["lounge"],
        "breakfast": room.get("breakfast", True),
        "price_per_night": room["price"],
        "nights": nights,
        "total_price": total_price,
        "check_in": ctx.get("check_in", "TBD"),
        "max_guests": room["max_guests"],
    }


def _parse_date(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
    if not m:
        return None
    month, day = m.groups()
    year = datetime.utcnow().year
    try:
        dt = datetime(year, int(month), int(day))
        if dt < datetime.utcnow():
            dt = dt.replace(year=year + 1)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None
