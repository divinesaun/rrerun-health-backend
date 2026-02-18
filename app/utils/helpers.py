import secrets
import string
import math
from typing import List, Dict, Optional


def generate_temp_password(length: int = 12) -> str:
    """Generate a secure random temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points."""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def sort_pharmacies_by_distance(
    pharmacies: List[Dict], latitude: float, longitude: float
) -> List[Dict]:
    """Sort a list of pharmacy dicts by distance from a given point."""
    for p in pharmacies:
        p_lat = p.get("latitude")
        p_lon = p.get("longitude")
        if p_lat and p_lon:
            p["distance_km"] = round(haversine_distance(latitude, longitude, p_lat, p_lon), 2)
        else:
            p["distance_km"] = None
    return sorted(pharmacies, key=lambda x: x.get("distance_km") or float("inf"))
