from fastapi import APIRouter, HTTPException, Depends
from app.core.security import get_current_user
from app.core.database import get_db
from app.core.utils import serialize_doc
from app.websockets.manager import manager
from bson import ObjectId
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/chat", tags=["Chat"])


class MessageCreate(BaseModel):
    booking_id: str
    message: str


@router.post("/send")
async def send_message(data: MessageCreate, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(data.booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    user_id = str(current_user["_id"])
    if user_id not in [booking["passenger_id"], booking["driver_id"]]:
        raise HTTPException(status_code=403, detail="Not part of this booking")

    # Determine receiver
    receiver_id = booking["driver_id"] if user_id == booking["passenger_id"] else booking["passenger_id"]

    msg_doc = {
        "booking_id": data.booking_id,
        "ride_id": booking["ride_id"],
        "sender_id": user_id,
        "sender_name": current_user["name"],
        "sender_role": current_user["role"],
        "receiver_id": receiver_id,
        "message": data.message.strip(),
        "read": False,
        "created_at": datetime.utcnow(),
    }
    result = await db.messages.insert_one(msg_doc)
    msg_doc["_id"] = result.inserted_id
    msg_doc = serialize_doc(msg_doc)

    # Realtime push to receiver
    await manager.broadcast_to_ride(f"chat_{data.booking_id}", {
        "type": "new_message",
        "booking_id": data.booking_id,
        **msg_doc
    })

    # Notification to receiver
    await db.notifications.insert_one({
        "user_id": receiver_id,
        "title": f"Message from {current_user['name']}",
        "message": data.message[:60] + ("..." if len(data.message) > 60 else ""),
        "type": "chat_message",
        "booking_id": data.booking_id,
        "read": False,
        "created_at": datetime.utcnow()
    })

    return msg_doc


@router.get("/{booking_id}")
async def get_messages(booking_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    user_id = str(current_user["_id"])
    if user_id not in [booking["passenger_id"], booking["driver_id"]]:
        raise HTTPException(status_code=403, detail="Not authorized")

    messages = await db.messages.find(
        {"booking_id": booking_id}
    ).sort("created_at", 1).to_list(200)

    # Mark received messages as read
    await db.messages.update_many(
        {"booking_id": booking_id, "receiver_id": user_id, "read": False},
        {"$set": {"read": True}}
    )

    return [serialize_doc(m) for m in messages]


@router.get("/unread/count")
async def get_unread_count(current_user=Depends(get_current_user)):
    db = get_db()
    count = await db.messages.count_documents({
        "receiver_id": str(current_user["_id"]),
        "read": False
    })
    return {"unread": count}
