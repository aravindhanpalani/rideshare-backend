from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    driver = "driver"
    passenger = "passenger"
    admin = "admin"


class VehicleDetails(BaseModel):
    make: str
    model: str
    year: int
    color: str
    plate_number: str
    seats: int


class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15)
    password: str = Field(..., min_length=6)
    role: UserRole = UserRole.passenger
    vehicle: Optional[VehicleDetails] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    vehicle: Optional[VehicleDetails] = None


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    role: str
    profile_picture: Optional[str] = None
    vehicle: Optional[VehicleDetails] = None
    average_rating: float = 0.0
    total_rides: int = 0
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
