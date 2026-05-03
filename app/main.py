from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.core.database import connect_db, disconnect_db
from app.core.config import settings
from app.routers import auth, rides, bookings, admin, chat
from app.websockets import routes as ws_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    yield
    await disconnect_db()


app = FastAPI(
    title="RideShare API",
    description="Full-featured ride-sharing platform API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS — allow all origins in production (Vercel URL set via env)
allowed_origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:5173",
]
# Allow any vercel.app subdomain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for uploads
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Routers
app.include_router(auth.router)
app.include_router(rides.router)
app.include_router(bookings.router)
app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(ws_routes.router)


@app.get("/")
async def root():
    return {"message": "RideShare API v1.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
