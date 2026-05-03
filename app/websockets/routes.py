from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.websockets.manager import manager
from app.core.security import decode_token
from app.core.database import get_db
from bson import ObjectId
import json

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/track/{ride_id}")
async def track_ride(websocket: WebSocket, ride_id: str, token: str = Query(None)):
    """
    WebSocket for live tracking.
    - Driver sends: {"type": "location", "lat": ..., "lng": ...}
    - Passenger sends: {"type": "passenger_location", "lat": ..., "lng": ..., "name": ...}
    - Everyone receives broadcasts
    """
    user = None
    user_role = None
    user_name = "Unknown"

    if token:
        payload = decode_token(token)
        if payload:
            db = get_db()
            try:
                user = await db.users.find_one({"_id": ObjectId(payload.get("sub"))})
                if user:
                    user_role = user.get("role")
                    user_name = user.get("name", "Unknown")
            except Exception:
                pass

    await manager.connect(websocket, ride_id)

    try:
        await manager.send_personal(websocket, {
            "type": "connected",
            "ride_id": ride_id,
            "user_role": user_role,
            "message": "Connected to live tracking"
        })

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            # ── Driver location → broadcast to all ──
            if msg_type == "location":
                location_update = {
                    "type": "location_update",
                    "ride_id": ride_id,
                    "lat": msg.get("lat"),
                    "lng": msg.get("lng"),
                    "heading": msg.get("heading"),
                    "speed": msg.get("speed"),
                    "timestamp": msg.get("timestamp"),
                }
                db = get_db()
                await db.rides.update_one(
                    {"_id": ObjectId(ride_id)},
                    {"$set": {"live_location": {"lat": msg.get("lat"), "lng": msg.get("lng")}}}
                )
                await manager.broadcast_to_ride(ride_id, location_update)

            # ── Passenger location → broadcast to all (driver sees it) ──
            elif msg_type == "passenger_location":
                passenger_id = str(user["_id"]) if user else msg.get("passenger_id", "unknown")
                passenger_update = {
                    "type": "passenger_location_update",
                    "ride_id": ride_id,
                    "passenger_id": passenger_id,
                    "passenger_name": user_name,
                    "lat": msg.get("lat"),
                    "lng": msg.get("lng"),
                    "timestamp": msg.get("timestamp"),
                }
                # Save to DB
                db = get_db()
                await db.rides.update_one(
                    {"_id": ObjectId(ride_id)},
                    {"$set": {
                        f"passenger_locations.{passenger_id}": {
                            "name": user_name,
                            "lat": msg.get("lat"),
                            "lng": msg.get("lng"),
                        }
                    }}
                )
                await manager.broadcast_to_ride(ride_id, passenger_update)

            elif msg_type == "sos":
                sos_alert = {
                    "type": "sos",
                    "ride_id": ride_id,
                    "lat": msg.get("lat"),
                    "lng": msg.get("lng"),
                    "user": user_name,
                    "user_role": user_role,
                    "message": f"🆘 SOS from {user_name}! Needs help!"
                }
                await manager.broadcast_to_ride(ride_id, sos_alert)

            elif msg_type == "ping":
                await manager.send_personal(websocket, {"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket, ride_id)
        await manager.broadcast_to_ride(ride_id, {
            "type": "user_left",
            "ride_id": ride_id,
            "user_name": user_name,
            "user_role": user_role,
        })


@router.websocket("/ws/notifications/{user_id}")
async def user_notifications(websocket: WebSocket, user_id: str, token: str = Query(None)):
    await manager.connect(websocket, f"notif_{user_id}")
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await manager.send_personal(websocket, {"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, f"notif_{user_id}")


@router.websocket("/ws/chat/{booking_id}")
async def chat_websocket(websocket: WebSocket, booking_id: str, token: str = Query(None)):
    """WebSocket for real-time chat between driver and passenger."""
    await manager.connect(websocket, f"chat_{booking_id}")
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await manager.send_personal(websocket, {"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, f"chat_{booking_id}")
