from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class BookingStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class BookingCreate(BaseModel):
    ride_id: str
    seats: int = Field(..., ge=1, le=4)


class BookingResponse(BaseModel):
    id: str
    ride_id: str
    passenger_id: str
    passenger_name: str
    driver_id: str
    seats: int
    total_price: float
    status: str
    pickup_point: Optional[str] = None
    created_at: datetime


class ReviewCreate(BaseModel):
    booking_id: str
    rating: float = Field(..., ge=1.0, le=5.0)
    comment: Optional[str] = None


class ReviewResponse(BaseModel):
    id: str
    reviewer_id: str
    reviewer_name: str
    reviewed_id: str
    booking_id: str
    rating: float
    comment: Optional[str] = None
    created_at: datetime


class NotificationResponse(BaseModel):
    id: str
    user_id: str
    title: str
    message: str
    type: str
    read: bool = False
    created_at: datetime
