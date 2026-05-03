from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from app.schemas.user import UserCreate, UserLogin, UserUpdate, UserResponse, TokenResponse
from app.core.security import hash_password, verify_password, create_access_token, get_current_user
from app.core.database import get_db
from app.core.utils import serialize_doc
from app.core.config import settings
from bson import ObjectId
from datetime import datetime
import aiofiles
import os
import uuid

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(user_data: UserCreate):
    db = get_db()
    existing_email = await db.users.find_one({"email": user_data.email})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_phone = await db.users.find_one({"phone": user_data.phone})
    if existing_phone:
        raise HTTPException(status_code=400, detail="Phone number already registered. Please use a different number or login.")

    if user_data.vehicle and user_data.vehicle.plate_number:
        existing_plate = await db.users.find_one({"vehicle.plate_number": user_data.vehicle.plate_number})
        if existing_plate:
            raise HTTPException(status_code=400, detail="Vehicle number already registered. Please check and try again.")

    user_doc = {
        "name": user_data.name,
        "email": user_data.email,
        "phone": user_data.phone,
        "password": hash_password(user_data.password),
        "role": user_data.role,
        "profile_picture": None,
        "vehicle": user_data.vehicle.dict() if user_data.vehicle else None,
        "average_rating": 0.0,
        "total_rides": 0,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    result = await db.users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    user = serialize_doc(user_doc)

    token = create_access_token({"sub": user["id"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    db = get_db()
    user = await db.users.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account suspended")

    user = serialize_doc(user)
    token = create_access_token({"sub": user["id"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user=Depends(get_current_user)):
    return serialize_doc(current_user)


@router.put("/me", response_model=UserResponse)
async def update_profile(updates: UserUpdate, current_user=Depends(get_current_user)):
    db = get_db()
    update_data = {k: v for k, v in updates.dict().items() if v is not None}
    if "vehicle" in update_data and update_data["vehicle"]:
        update_data["vehicle"] = update_data["vehicle"].dict() if hasattr(update_data["vehicle"], 'dict') else update_data["vehicle"]
    
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": update_data}
    )
    updated = await db.users.find_one({"_id": ObjectId(current_user["_id"])})
    return serialize_doc(updated)


@router.post("/me/picture")
async def upload_picture(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(status_code=400, detail="Only JPEG/PNG/WEBP images allowed")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

    async with aiofiles.open(filepath, "wb") as f:
        content = await file.read()
        if len(content) > settings.MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large (max 5MB)")
        await f.write(content)

    db = get_db()
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {"profile_picture": f"/uploads/{filename}"}}
    )
    return {"profile_picture": f"/uploads/{filename}"}
