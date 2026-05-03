from fastapi import APIRouter, HTTPException, Depends, Query
from app.schemas.ride import RideCreate, RideUpdate, RideResponse
from app.core.security import get_current_user
from app.core.database import get_db
from app.core.utils import serialize_doc, haversine_distance, route_similarity_score, estimate_duration
from bson import ObjectId
from datetime import datetime
from typing import List, Optional
import copy

router = APIRouter(prefix="/rides", tags=["Rides"])


def build_ride_response(ride: dict, driver: dict) -> dict:
    ride = serialize_doc(copy.deepcopy(ride))
    driver = serialize_doc(copy.deepcopy(driver)) if driver else {}
    ride["driver_name"] = driver.get("name", "Unknown")
    ride["driver_rating"] = driver.get("average_rating", 0.0)
    ride["driver_picture"] = driver.get("profile_picture")
    ride["total_seats"] = ride.get("total_seats", ride.get("available_seats", 0))
    return ride


@router.post("/", response_model=RideResponse, status_code=201)
async def create_ride(ride_data: RideCreate, current_user=Depends(get_current_user)):
    if current_user.get("role") not in ["driver", "admin"]:
        raise HTTPException(status_code=403, detail="Only drivers can create rides")

    db = get_db()
    src = ride_data.source_coords
    dst = ride_data.destination_coords
    distance = haversine_distance(src.lat, src.lng, dst.lat, dst.lng)
    duration = estimate_duration(distance)

    ride_doc = {
        "driver_id": str(current_user["_id"]),
        "source": ride_data.source,
        "source_coords": {"lat": src.lat, "lng": src.lng},
        "destination": ride_data.destination,
        "destination_coords": {"lat": dst.lat, "lng": dst.lng},
        "departure_time": ride_data.departure_time,
        "available_seats": ride_data.available_seats,
        "total_seats": ride_data.available_seats,
        "price_per_seat": ride_data.price_per_seat,
        "distance_km": round(distance, 2),
        "estimated_duration_mins": duration,
        "status": "created",
        "notes": ride_data.notes,
        "route_coords": [c.dict() for c in ride_data.route_coords],
        "created_at": datetime.utcnow(),
    }
    result = await db.rides.insert_one(ride_doc)
    ride_doc["_id"] = result.inserted_id
    return build_ride_response(ride_doc, current_user)


@router.get("/search", response_model=List[RideResponse])
async def search_rides(
    source_lat: float,
    source_lng: float,
    dest_lat: float,
    dest_lng: float,
    date: Optional[str] = None,
    seats_needed: int = 1,
    radius_km: float = 50.0,
):
    db = get_db()
    query = {
        "status": {"$in": ["created", "booked", "ongoing"]},
        "available_seats": {"$gte": seats_needed},
    }

    all_rides = await db.rides.find(query).to_list(200)

    scored = []
    for ride in all_rides:
        if not ride.get("source_coords") or not ride.get("destination_coords"):
            continue
        src = ride["source_coords"]
        dst = ride["destination_coords"]
        score = route_similarity_score(
            source_lat, source_lng, dest_lat, dest_lng,
            src["lat"], src["lng"], dst["lat"], dst["lng"],
            radius_km
        )
        if score > 0:
            scored.append((score, ride))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, ride in scored[:20]:
        driver = await db.users.find_one({"_id": ObjectId(ride["driver_id"])})
        if driver:
            results.append(build_ride_response(ride, driver))

    return results


@router.get("/my-rides", response_model=List[RideResponse])
async def get_my_rides(current_user=Depends(get_current_user)):
    db = get_db()
    driver_id = str(current_user["_id"])
    rides = await db.rides.find({"driver_id": driver_id}).sort("created_at", -1).to_list(50)
    # Fetch fresh driver from DB to avoid serialize issues
    driver = await db.users.find_one({"_id": ObjectId(driver_id)})
    results = []
    for ride in rides:
        results.append(build_ride_response(ride, driver))
    return results


@router.get("/{ride_id}", response_model=RideResponse)
async def get_ride(ride_id: str):
    db = get_db()
    try:
        ride = await db.rides.find_one({"_id": ObjectId(ride_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ride ID")
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    driver = await db.users.find_one({"_id": ObjectId(ride["driver_id"])})
    return build_ride_response(ride, driver)


@router.put("/{ride_id}", response_model=RideResponse)
async def update_ride(ride_id: str, updates: RideUpdate, current_user=Depends(get_current_user)):
    db = get_db()
    ride = await db.rides.find_one({"_id": ObjectId(ride_id)})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["driver_id"] != str(current_user["_id"]) and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = {k: v for k, v in updates.dict().items() if v is not None}
    await db.rides.update_one({"_id": ObjectId(ride_id)}, {"$set": update_data})
    updated = await db.rides.find_one({"_id": ObjectId(ride_id)})
    driver = await db.users.find_one({"_id": ObjectId(updated["driver_id"])})
    return build_ride_response(updated, driver)


@router.post("/{ride_id}/start")
async def start_ride(ride_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    ride = await db.rides.find_one({"_id": ObjectId(ride_id)})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["driver_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
    if ride["status"] not in ["created", "booked"]:
        raise HTTPException(status_code=400, detail="Ride cannot be started")

    await db.rides.update_one(
        {"_id": ObjectId(ride_id)},
        {"$set": {"status": "ongoing", "started_at": datetime.utcnow()}}
    )

    bookings = await db.bookings.find({"ride_id": ride_id, "status": "confirmed"}).to_list(20)
    notifications = [{
        "user_id": b["passenger_id"],
        "title": "Ride Started!",
        "message": f"Your ride from {ride['source'].split(',')[0]} has started.",
        "type": "ride_started",
        "ride_id": ride_id,
        "read": False,
        "created_at": datetime.utcnow()
    } for b in bookings]
    if notifications:
        await db.notifications.insert_many(notifications)

    return {"message": "Ride started"}


@router.post("/{ride_id}/complete")
async def complete_ride(ride_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    ride = await db.rides.find_one({"_id": ObjectId(ride_id)})
    if not ride or ride["driver_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.rides.update_one(
        {"_id": ObjectId(ride_id)},
        {"$set": {"status": "completed", "completed_at": datetime.utcnow()}}
    )
    await db.bookings.update_many(
        {"ride_id": ride_id, "status": "confirmed"},
        {"$set": {"status": "completed"}}
    )
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$inc": {"total_rides": 1}}
    )
    return {"message": "Ride completed"}


@router.delete("/{ride_id}")
async def cancel_ride(ride_id: str, current_user=Depends(get_current_user)):
    db = get_db()
    ride = await db.rides.find_one({"_id": ObjectId(ride_id)})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["driver_id"] != str(current_user["_id"]) and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.rides.update_one({"_id": ObjectId(ride_id)}, {"$set": {"status": "cancelled"}})
    await db.bookings.update_many(
        {"ride_id": ride_id, "status": {"$in": ["pending_approval", "confirmed"]}},
        {"$set": {"status": "cancelled"}}
    )
    return {"message": "Ride cancelled"}


@router.get("/driver/earnings")
async def get_driver_earnings(current_user=Depends(get_current_user)):
    """Driver's own earnings dashboard data"""
    if current_user.get("role") not in ["driver", "admin"]:
        raise HTTPException(status_code=403, detail="Drivers only")

    db = get_db()
    import copy
    from datetime import timedelta

    driver_id = str(current_user["_id"])

    total_rides = await db.rides.count_documents({"driver_id": driver_id})
    completed_rides = await db.rides.count_documents({"driver_id": driver_id, "status": "completed"})
    ongoing_rides = await db.rides.count_documents({"driver_id": driver_id, "status": "ongoing"})
    cancelled_rides = await db.rides.count_documents({"driver_id": driver_id, "status": "cancelled"})

    # Total earnings from completed bookings
    bookings = await db.bookings.find({
        "driver_id": driver_id,
        "status": "completed"
    }).to_list(1000)
    total_earned = sum(b.get("total_price", 0) for b in bookings)
    total_passengers = sum(b.get("seats", 0) for b in bookings)

    # Last 7 days earnings
    week_ago = datetime.utcnow() - timedelta(days=7)
    daily = []
    for i in range(7):
        day = week_ago + timedelta(days=i)
        next_day = day + timedelta(days=1)
        day_bookings = [b for b in bookings if day <= b.get("created_at", datetime.utcnow()) < next_day]
        earned = sum(b.get("total_price", 0) for b in day_bookings)
        rides_count = await db.rides.count_documents({
            "driver_id": driver_id,
            "status": "completed",
            "created_at": {"$gte": day, "$lt": next_day}
        })
        daily.append({
            "date": day.strftime("%b %d"),
            "earned": round(earned, 2),
            "rides": rides_count
        })

    # Recent completed rides
    recent_rides = await db.rides.find({
        "driver_id": driver_id,
        "status": "completed"
    }).sort("created_at", -1).limit(5).to_list(5)

    return {
        "total_rides": total_rides,
        "completed_rides": completed_rides,
        "ongoing_rides": ongoing_rides,
        "cancelled_rides": cancelled_rides,
        "total_earned": round(total_earned, 2),
        "total_passengers": total_passengers,
        "average_rating": current_user.get("average_rating", 0.0),
        "daily": daily,
        "recent_rides": [serialize_doc(copy.deepcopy(r)) for r in recent_rides],
    }
