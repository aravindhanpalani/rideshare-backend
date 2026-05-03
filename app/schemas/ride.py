from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
from datetime import datetime
from enum import Enum


class RideStatus(str, Enum):
    created = "created"
    booked = "booked"
    ongoing = "ongoing"
    completed = "completed"
    cancelled = "cancelled"


class Coordinates(BaseModel):
    lat: float
    lng: float


class RideCreate(BaseModel):
    source: str
    source_coords: Coordinates
    destination: str
    destination_coords: Coordinates
    departure_time: datetime
    available_seats: int = Field(..., ge=1, le=8)
    price_per_seat: float = Field(..., ge=0)
    notes: Optional[str] = None
    route_coords: Optional[List[Coordinates]] = []


class RideUpdate(BaseModel):
    available_seats: Optional[int] = None
    price_per_seat: Optional[float] = None
    notes: Optional[str] = None
    status: Optional[RideStatus] = None


class RideSearch(BaseModel):
    source_lat: float
    source_lng: float
    dest_lat: float
    dest_lng: float
    date: Optional[str] = None
    seats_needed: int = 1
    radius_km: float = 10.0


class RideResponse(BaseModel):
    id: str
    driver_id: str
    driver_name: str
    driver_rating: float
    driver_picture: Optional[str] = None
    source: str
    source_coords: Coordinates
    destination: str
    destination_coords: Coordinates
    departure_time: datetime
    available_seats: int
    total_seats: int
    price_per_seat: float
    distance_km: Optional[float] = None
    estimated_duration_mins: Optional[int] = None
    status: str
    notes: Optional[str] = None
    route_coords: Optional[List[Coordinates]] = []
    created_at: datetime


class LiveLocation(BaseModel):
    ride_id: str
    lat: float
    lng: float
    heading: Optional[float] = None
    speed: Optional[float] = None
