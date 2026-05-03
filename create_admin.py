"""
Run this ONCE to create admin user:
  python create_admin.py
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from datetime import datetime

MONGODB_URL = "mongodb://localhost:27017"
DATABASE_NAME = "rideshare_db"

# ✅ ADMIN CREDENTIALS — change these if you want
ADMIN_EMAIL    = "admin@rideshare.com"
ADMIN_PASSWORD = "Admin@1234"
ADMIN_NAME     = "Super Admin"
ADMIN_PHONE    = "9999999999"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_admin():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DATABASE_NAME]

    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if existing:
        print(f"✅ Admin already exists: {ADMIN_EMAIL}")
        client.close()
        return

    user = {
        "name": ADMIN_NAME,
        "email": ADMIN_EMAIL,
        "phone": ADMIN_PHONE,
        "password": pwd_context.hash(ADMIN_PASSWORD),
        "role": "admin",
        "profile_picture": None,
        "vehicle": None,
        "average_rating": 5.0,
        "total_rides": 0,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    await db.users.insert_one(user)
    client.close()

    print("=" * 40)
    print("✅ Admin user created!")
    print(f"   Email    : {ADMIN_EMAIL}")
    print(f"   Password : {ADMIN_PASSWORD}")
    print(f"   Role     : admin")
    print("=" * 40)
    print("Login at: http://localhost:5173/login")
    print("Dashboard: http://localhost:5173/admin")

asyncio.run(create_admin())
