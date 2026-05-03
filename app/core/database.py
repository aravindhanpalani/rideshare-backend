from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

client: AsyncIOMotorClient = None
db = None


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]
    # Create indexes
    await db.users.create_index("email", unique=True)
    indexes = await db.users.index_information()
    if "phone_1" not in indexes:
         await db.users.create_index("phone", unique=True, name="phone_1")
    await db.rides.create_index([("source_coords", "2dsphere")])
    await db.rides.create_index([("destination_coords", "2dsphere")])
    await db.rides.create_index("driver_id")
    await db.rides.create_index("status")
    await db.bookings.create_index("passenger_id")
    await db.bookings.create_index("ride_id")
    print("Connected to MongoDB")


async def disconnect_db():
    global client
    if client:
        client.close()
        print("Disconnected from MongoDB")


def get_db():
    return db
