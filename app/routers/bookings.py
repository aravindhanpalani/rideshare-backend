from fastapi import APIRouter, HTTPException, Depends
from app.schemas.booking import BookingCreate, BookingResponse, ReviewCreate, ReviewResponse
from app.core.security import get_current_user
from app.core.database import get_db
from app.core.utils import serialize_doc
from app.websockets.manager import manager
from bson import ObjectId
from datetime import datetime
from typing import List

router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.post("/", response_model=BookingResponse, status_code=201)
async def create_booking(booking_data: BookingCreate, current_user=Depends(get_current_user)):
    db = get_db()
    try:
        ride = await db.rides.find_one({"_id": ObjectId(booking_data.ride_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ride ID")

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    # ✅ Fix 2: ongoing ride-லயும் book பண்ணலாம் — seats இருந்தா
    if ride["status"] not in ["created", "booked", "ongoing"]:
        raise HTTPException(status_code=400, detail="Ride is not available for booking")

    if ride["driver_id"] == str(current_user["_id"]):
        raise HTTPException(status_code=400, detail="Driver cannot book their own ride")

    if ride["available_seats"] < booking_data.seats:
        raise HTTPException(status_code=400, detail=f"Only {ride['available_seats']} seats available")

    existing = await db.bookings.find_one({
        "ride_id": booking_data.ride_id,
        "passenger_id": str(current_user["_id"]),
        "status": {"$in": ["pending", "confirmed", "pending_approval"]}
    })
    if existing:
        raise HTTPException(status_code=400, detail="You already have a booking for this ride")

    total_price = ride["price_per_seat"] * booking_data.seats

    # ✅ Fix 4: booking status = "pending_approval" — driver accept பண்ணணும்
    booking_doc = {
        "ride_id": booking_data.ride_id,
        "passenger_id": str(current_user["_id"]),
        "passenger_name": current_user["name"],
        "driver_id": ride["driver_id"],
        "seats": booking_data.seats,
        "total_price": total_price,
        "price_per_seat": ride["price_per_seat"],
        "status": "pending_approval",
        "created_at": datetime.utcnow(),
    }
    result = await db.bookings.insert_one(booking_doc)
    booking_doc["_id"] = result.inserted_id
    booking_id = str(result.inserted_id)

    # ✅ Fix 4: Driver-க்கு notification + realtime push
    notif = {
        "user_id": ride["driver_id"],
        "title": "New Booking Request!",
        "message": f"{current_user['name']} wants {booking_data.seats} seat(s) on your ride. Tap to accept or reject.",
        "type": "booking_request",
        "booking_id": booking_id,
        "ride_id": booking_data.ride_id,
        "passenger_name": current_user["name"],
        "seats": booking_data.seats,
        "read": False,
        "created_at": datetime.utcnow()
    }
    await db.notifications.insert_one(notif)

    # Realtime WebSocket notification to driver
    await manager.broadcast_to_ride(f"notif_{ride['driver_id']}", {
        "type": "booking_request",
        "booking_id": booking_id,
        "passenger_name": current_user["name"],
        "seats": booking_data.seats,
        "message": f"{current_user['name']} wants to book {booking_data.seats} seat(s)!"
    })

    return serialize_doc(booking_doc)


# ✅ Fix 4: Driver accept booking
@router.post("/{booking_id}/accept")
async def accept_booking(booking_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["driver_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Only the driver can accept bookings")
    if booking["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Booking is not pending approval")

    ride = await db.rides.find_one({"_id": ObjectId(booking["ride_id"])})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["available_seats"] < booking["seats"]:
        raise HTTPException(status_code=400, detail="Not enough seats available anymore")

    # Confirm booking + reduce seats
    await db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {"status": "confirmed"}}
    )
    new_seats = ride["available_seats"] - booking["seats"]
    new_status = "booked" if new_seats == 0 else ride["status"]
    await db.rides.update_one(
        {"_id": ObjectId(booking["ride_id"])},
        {"$set": {"available_seats": new_seats, "status": new_status}}
    )

    # Notify passenger
    await db.notifications.insert_one({
        "user_id": booking["passenger_id"],
        "title": "Booking Confirmed! 🎉",
        "message": f"Your booking has been accepted by the driver. Have a great ride!",
        "type": "booking_confirmed",
        "booking_id": booking_id,
        "ride_id": booking["ride_id"],
        "read": False,
        "created_at": datetime.utcnow()
    })
    # Realtime push to passenger
    await manager.broadcast_to_ride(f"notif_{booking['passenger_id']}", {
        "type": "booking_confirmed",
        "booking_id": booking_id,
        "ride_id": booking["ride_id"],
        "message": "✅ Driver accepted your booking! Have a great ride!"
    })
    # Also push to the ride channel (passenger might be on ride details page)
    await manager.broadcast_to_ride(booking["ride_id"], {
        "type": "booking_confirmed",
        "booking_id": booking_id,
        "message": "Your booking has been confirmed by the driver! 🎉"
    })

    return {"message": "Booking accepted"}


# ✅ Fix 4: Driver reject booking
@router.post("/{booking_id}/reject")
async def reject_booking(booking_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["driver_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Only the driver can reject bookings")
    if booking["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Booking is not pending")

    await db.bookings.update_one(
        {"_id": ObjectId(booking_id)},
        {"$set": {"status": "rejected"}}
    )

    # Notify passenger
    await db.notifications.insert_one({
        "user_id": booking["passenger_id"],
        "title": "Booking Rejected",
        "message": "Sorry, the driver could not accept your booking request.",
        "type": "booking_rejected",
        "booking_id": booking_id,
        "ride_id": booking["ride_id"],
        "read": False,
        "created_at": datetime.utcnow()
    })
    # Realtime push to passenger
    await manager.broadcast_to_ride(f"notif_{booking['passenger_id']}", {
        "type": "booking_rejected",
        "booking_id": booking_id,
        "ride_id": booking["ride_id"],
        "message": "❌ Driver could not accept your booking request."
    })
    await manager.broadcast_to_ride(booking["ride_id"], {
        "type": "booking_rejected",
        "booking_id": booking_id,
        "message": "Driver rejected your booking request."
    })

    return {"message": "Booking rejected"}


# Driver's pending booking requests
@router.get("/pending-requests")
async def get_pending_requests(current_user=Depends(get_current_user)):
    db = get_db()
    bookings = await db.bookings.find({
        "driver_id": str(current_user["_id"]),
        "status": "pending_approval"
    }).sort("created_at", -1).to_list(50)
    return [serialize_doc(b) for b in bookings]


@router.get("/my-bookings", response_model=List[BookingResponse])
async def get_my_bookings(current_user=Depends(get_current_user)):
    db = get_db()
    bookings = await db.bookings.find(
        {"passenger_id": str(current_user["_id"])}
    ).sort("created_at", -1).to_list(50)
    return [serialize_doc(b) for b in bookings]


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["passenger_id"] != str(current_user["_id"]) and booking["driver_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
    return serialize_doc(booking)


@router.delete("/{booking_id}")
async def cancel_booking(booking_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["passenger_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
    if booking["status"] not in ["pending_approval", "confirmed"]:
        raise HTTPException(status_code=400, detail="Cannot cancel this booking")

    await db.bookings.update_one(
        {"_id": ObjectId(booking_id)}, {"$set": {"status": "cancelled"}}
    )

    # Restore seats only if booking was confirmed
    if booking["status"] == "confirmed":
        ride = await db.rides.find_one({"_id": ObjectId(booking["ride_id"])})
        if ride and ride["status"] != "cancelled":
            new_seats = ride["available_seats"] + booking["seats"]
            new_status = "created" if new_seats > 0 else ride["status"]
            await db.rides.update_one(
                {"_id": ObjectId(booking["ride_id"])},
                {"$set": {"available_seats": new_seats, "status": new_status}}
            )

    await db.notifications.insert_one({
        "user_id": booking["driver_id"],
        "title": "Booking Cancelled",
        "message": f"{current_user['name']} cancelled their booking.",
        "type": "booking_cancelled",
        "read": False,
        "created_at": datetime.utcnow()
    })

    return {"message": "Booking cancelled"}


@router.post("/reviews/", response_model=ReviewResponse, status_code=201)
async def create_review(review_data: ReviewCreate, current_user=Depends(get_current_user)):
    db = get_db()
    booking = await db.bookings.find_one({"_id": ObjectId(review_data.booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["passenger_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Only passengers can review")
    if booking["status"] != "completed":
        raise HTTPException(status_code=400, detail="Can only review completed rides")

    existing = await db.reviews.find_one({"booking_id": review_data.booking_id})
    if existing:
        raise HTTPException(status_code=400, detail="Review already submitted")

    review_doc = {
        "reviewer_id": str(current_user["_id"]),
        "reviewer_name": current_user["name"],
        "reviewed_id": booking["driver_id"],
        "booking_id": review_data.booking_id,
        "rating": review_data.rating,
        "comment": review_data.comment,
        "created_at": datetime.utcnow()
    }
    await db.reviews.insert_one(review_doc)

    all_reviews = await db.reviews.find({"reviewed_id": booking["driver_id"]}).to_list(1000)
    avg = sum(r["rating"] for r in all_reviews) / len(all_reviews)
    await db.users.update_one(
        {"_id": ObjectId(booking["driver_id"])},
        {"$set": {"average_rating": round(avg, 2)}}
    )

    return serialize_doc(review_doc)


@router.get("/notifications/me")
async def get_notifications(current_user=Depends(get_current_user)):
    db = get_db()
    notes = await db.notifications.find(
        {"user_id": str(current_user["_id"])}
    ).sort("created_at", -1).limit(50).to_list(50)
    for n in notes:
        n["id"] = str(n.pop("_id"))
    return notes


@router.put("/notifications/{notif_id}/read")
async def mark_read(notif_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    await db.notifications.update_one(
        {"_id": ObjectId(notif_id), "user_id": str(current_user["_id"])},
        {"$set": {"read": True}}
    )
    return {"message": "Marked as read"}
