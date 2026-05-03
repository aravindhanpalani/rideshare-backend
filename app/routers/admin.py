from fastapi import APIRouter, Depends, Query
from app.core.security import get_current_admin
from app.core.database import get_db
from app.core.utils import serialize_doc
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats")
async def get_stats(current_admin=Depends(get_current_admin)):
    db = get_db()
    total_users = await db.users.count_documents({})
    total_drivers = await db.users.count_documents({"role": "driver"})
    total_passengers = await db.users.count_documents({"role": "passenger"})
    total_rides = await db.rides.count_documents({})
    active_rides = await db.rides.count_documents({"status": {"$in": ["created", "booked", "ongoing"]}})
    completed_rides = await db.rides.count_documents({"status": "completed"})
    total_bookings = await db.bookings.count_documents({})

    # Revenue estimation
    pipeline = [
        {"$match": {"status": "completed"}},
        {"$group": {"_id": None, "total": {"$sum": "$total_price"}}}
    ]
    rev_result = await db.bookings.aggregate(pipeline).to_list(1)
    revenue = rev_result[0]["total"] if rev_result else 0

    # Last 7 days rides
    week_ago = datetime.utcnow() - timedelta(days=7)
    daily_rides = []
    for i in range(7):
        day = week_ago + timedelta(days=i)
        next_day = day + timedelta(days=1)
        count = await db.rides.count_documents({"created_at": {"$gte": day, "$lt": next_day}})
        daily_rides.append({"date": day.strftime("%b %d"), "rides": count})

    return {
        "total_users": total_users,
        "total_drivers": total_drivers,
        "total_passengers": total_passengers,
        "total_rides": total_rides,
        "active_rides": active_rides,
        "completed_rides": completed_rides,
        "total_bookings": total_bookings,
        "estimated_revenue": round(revenue, 2),
        "daily_rides": daily_rides
    }


@router.get("/users")
async def list_users(
    page: int = 1,
    limit: int = 20,
    role: Optional[str] = None,
    current_admin=Depends(get_current_admin)
):
    db = get_db()
    query = {}
    if role:
        query["role"] = role
    skip = (page - 1) * limit
    users = await db.users.find(query).skip(skip).limit(limit).sort("created_at", -1).to_list(limit)
    total = await db.users.count_documents(query)
    result = []
    for u in users:
        u = serialize_doc(u)
        u.pop("password", None)
        result.append(u)
    return {"users": result, "total": total, "page": page, "pages": (total + limit - 1) // limit}


@router.get("/rides")
async def list_rides(
    page: int = 1,
    limit: int = 100,
    status: Optional[str] = None,
    current_admin=Depends(get_current_admin)
):
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    skip = (page - 1) * limit
    rides = await db.rides.find(query).skip(skip).limit(limit).sort("created_at", -1).to_list(limit)
    total = await db.rides.count_documents(query)

    # Attach driver name to each ride
    result = []
    for ride in rides:
        ride = serialize_doc(ride)
        try:
            from bson import ObjectId
            driver = await db.users.find_one({"_id": ObjectId(ride.get("driver_id", ""))})
            ride["driver_name"] = driver.get("name", "Unknown") if driver else "Unknown"
        except Exception:
            ride["driver_name"] = "Unknown"
        result.append(ride)

    return {"rides": result, "total": total, "page": page}


@router.get("/bookings")
async def list_bookings(
    page: int = 1,
    limit: int = 20,
    current_admin=Depends(get_current_admin)
):
    db = get_db()
    skip = (page - 1) * limit
    bookings = await db.bookings.find({}).skip(skip).limit(limit).sort("created_at", -1).to_list(limit)
    total = await db.bookings.count_documents({})
    return {"bookings": [serialize_doc(b) for b in bookings], "total": total}


@router.put("/users/{user_id}/suspend")
async def suspend_user(user_id: str, current_admin=Depends(get_current_admin)):
    db = get_db()
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": False}})
    return {"message": "User suspended"}


@router.put("/users/{user_id}/activate")
async def activate_user(user_id: str, current_admin=Depends(get_current_admin)):
    db = get_db()
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": True}})
    return {"message": "User activated"}


# ── Driver Dashboard Stats ──
@router.get("/driver-stats")
async def get_driver_stats(current_user=Depends(get_current_admin)):
    """Get all driver stats for admin overview"""
    db = get_db()
    drivers = await db.users.find({"role": "driver"}).to_list(200)
    result = []
    for d in drivers:
        driver_id = str(d["_id"])
        total_rides = await db.rides.count_documents({"driver_id": driver_id})
        completed = await db.rides.count_documents({"driver_id": driver_id, "status": "completed"})
        ongoing = await db.rides.count_documents({"driver_id": driver_id, "status": "ongoing"})
        bookings = await db.bookings.find({"driver_id": driver_id, "status": "completed"}).to_list(1000)
        revenue = sum(b.get("total_price", 0) for b in bookings)
        d = serialize_doc(d)
        d.pop("password", None)
        d["total_rides"] = total_rides
        d["completed_rides"] = completed
        d["ongoing_rides"] = ongoing
        d["revenue"] = round(revenue, 2)
        result.append(d)
    return result


# ── Passenger Dashboard Stats ──
@router.get("/passenger-stats")
async def get_passenger_stats(current_user=Depends(get_current_admin)):
    """Get all passenger stats for admin overview"""
    db = get_db()
    passengers = await db.users.find({"role": "passenger"}).to_list(200)
    result = []
    for p in passengers:
        passenger_id = str(p["_id"])
        total_bookings = await db.bookings.count_documents({"passenger_id": passenger_id})
        completed = await db.bookings.count_documents({"passenger_id": passenger_id, "status": "completed"})
        pending = await db.bookings.count_documents({"passenger_id": passenger_id, "status": "pending_approval"})
        spent_data = await db.bookings.find({"passenger_id": passenger_id, "status": "completed"}).to_list(1000)
        total_spent = sum(b.get("total_price", 0) for b in spent_data)
        p = serialize_doc(p)
        p.pop("password", None)
        p["total_bookings"] = total_bookings
        p["completed_trips"] = completed
        p["pending_bookings"] = pending
        p["total_spent"] = round(total_spent, 2)
        result.append(p)
    return result
