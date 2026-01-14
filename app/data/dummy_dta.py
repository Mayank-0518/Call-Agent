import uuid
from datetime import datetime, timedelta

ROOMS = [
    {
        "id": "deluxe-two-bed",
        "name": "Deluxe Two Bed",
        "beds": 2,
        "lounge": False,
        "price": 5600,
        "breakfast": True,
        "max_guests": 3,
        "inventory": 5,
    },
    {
        "id": "deluxe-lounge",
        "name": "Deluxe Lounge",
        "beds": 2,
        "lounge": True,
        "price": 8200,
        "breakfast": True,
        "max_guests": 4,
        "inventory": 4,
    },
    {
        "id": "family-suite",
        "name": "Family Suite",
        "beds": 3,
        "lounge": True,
        "price": 9800,
        "breakfast": True,
        "max_guests": 6,
        "inventory": 2,
    },
]

BOOKINGS = {}

def find_rooms(guests, beds=None, lounge=None):
    results = []
    for r in ROOMS:
        if r["max_guests"] < guests:
            continue
        if beds and r["beds"] != beds:
            continue
        if lounge is not None and r["lounge"] != lounge:
            continue
        if r.get("inventory", 0) <= 0:
            continue
        results.append(r)
    return results

def create_booking(name, room):
    booking_id = f"RP-{uuid.uuid4().hex[:6].upper()}"
    BOOKINGS[booking_id] = {
        "name": name,
        "room": room,
        "expires_at": datetime.utcnow() + timedelta(hours=2),
    }
    return booking_id
