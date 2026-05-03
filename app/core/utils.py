import math
from typing import Tuple
import copy


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two coordinates in kilometers."""
    R = 6371
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def calculate_price(distance_km: float, demand_factor: float = 1.0) -> float:
    BASE_FARE = 20.0
    PER_KM_RATE = 8.0
    FUEL_SURCHARGE = 0.05
    price = (BASE_FARE + PER_KM_RATE * distance_km) * demand_factor
    price += price * FUEL_SURCHARGE
    return round(price, 2)


def estimate_duration(distance_km: float, avg_speed_kmh: float = 40.0) -> int:
    return int((distance_km / avg_speed_kmh) * 60)


def is_within_radius(point_lat, point_lng, center_lat, center_lng, radius_km):
    return haversine_distance(point_lat, point_lng, center_lat, center_lng) <= radius_km


def route_similarity_score(
    search_src_lat, search_src_lng,
    search_dst_lat, search_dst_lng,
    ride_src_lat, ride_src_lng,
    ride_dst_lat, ride_dst_lng,
    radius_km=10.0
) -> float:
    src_dist = haversine_distance(search_src_lat, search_src_lng, ride_src_lat, ride_src_lng)
    dst_dist = haversine_distance(search_dst_lat, search_dst_lng, ride_dst_lat, ride_dst_lng)
    if src_dist > radius_km or dst_dist > radius_km:
        return 0.0
    src_score = max(0, 1 - (src_dist / radius_km))
    dst_score = max(0, 1 - (dst_dist / radius_km))
    return (src_score + dst_score) / 2


def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict."""
    if doc is None:
        return None
    doc = copy.deepcopy(doc)
    # Already serialized — has 'id' but no '_id'
    if "id" in doc and "_id" not in doc:
        return doc
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    # Convert any remaining ObjectId fields
    for key, value in list(doc.items()):
        if type(value).__name__ == 'ObjectId':
            doc[key] = str(value)
    return doc
