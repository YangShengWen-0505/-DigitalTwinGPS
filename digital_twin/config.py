import os
import json
import time
import googlemaps
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

if hasattr(time, 'tzset') and 'TZ' in os.environ:
    time.tzset()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip().strip('"')
PHONE_TAILSCALE_IP = os.getenv("PHONE_TAILSCALE_IP", "").strip().strip('"')
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "").strip().strip('"')
if not API_SECRET_KEY:
    raise RuntimeError("[FATAL] API_SECRET_KEY is not set in .env. Server cannot start safely.")
if len(API_SECRET_KEY) < 16:
    print("[WARNING] API_SECRET_KEY is too short (< 16 chars). Use a long random secret.")

if not GOOGLE_MAPS_API_KEY:
    print("[SYSTEM] Error: Missing GOOGLE_MAPS_API_KEY in .env file.")

gmaps_client = None
if GOOGLE_MAPS_API_KEY:
    try:
        gmaps_client = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    except Exception as e:
        print(f"[SYSTEM] Warning: Google Maps API initialization failed: {e}")

config_path = os.path.join(BASE_DIR, "digital_twin", "data", "settings.json")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"[SYSTEM] Error: failed to load {config_path}: {e}")
    CONFIG = {"settings": {"SPEED_MULTIPLIER": 1, "GUARD_INTERVAL": 1.5}, "mrt_station_groups": {}}

def _env_float(name: str, fallback: float) -> float:
    value = os.getenv(name, "").strip().strip('"')
    if not value:
        return fallback
    try:
        return float(value)
    except ValueError:
        print(f"[SYSTEM] Warning: {name} must be a number. Falling back to {fallback}.")
        return fallback


SPEED_MULTIPLIER = _env_float(
    "SPEED_MULTIPLIER",
    float(CONFIG.get("settings", {}).get("SPEED_MULTIPLIER", 1)),
)
GUARD_INTERVAL = _env_float(
    "GUARD_INTERVAL",
    float(CONFIG.get("settings", {}).get("GUARD_INTERVAL", 1.5)),
)
if SPEED_MULTIPLIER <= 0:
    print("[SYSTEM] Warning: SPEED_MULTIPLIER must be > 0. Falling back to 1.")
    SPEED_MULTIPLIER = 1
if GUARD_INTERVAL < 0.5:
    print("[SYSTEM] Warning: GUARD_INTERVAL is too low. Falling back to 1.5.")
    GUARD_INTERVAL = 1.5

def _flatten_station_groups(groups: dict) -> dict[str, list[float]]:
    stations: dict[str, list[float]] = {}
    if not isinstance(groups, dict):
        return stations
    for system_name, lines in groups.items():
        if not isinstance(lines, dict):
            continue
        for line_name, line_stations in lines.items():
            if not isinstance(line_stations, dict):
                continue
            for station_name, coords in line_stations.items():
                if not isinstance(coords, list) or len(coords) != 2:
                    continue
                key = f"{station_name} ({line_name})"
                stations[key] = [float(coords[0]), float(coords[1])]
    return stations


MRT_STATIONS_DB = {}
MRT_STATIONS_DB.update(_flatten_station_groups(CONFIG.get("mrt_station_groups", {})))
