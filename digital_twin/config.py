import os
import json
import time
import googlemaps
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

if hasattr(time, 'tzset') and 'TZ' in os.environ:
    time.tzset()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
PHONE_TAILSCALE_IP = os.getenv("PHONE_TAILSCALE_IP")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
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
except FileNotFoundError:
    print(f"[SYSTEM] Error: {config_path} not found.")
    CONFIG = {"settings": {"SPEED_MULTIPLIER": 1, "GUARD_INTERVAL": 1.5}, "mrt_stations": {}}

SPEED_MULTIPLIER = CONFIG["settings"]["SPEED_MULTIPLIER"]
GUARD_INTERVAL = CONFIG["settings"]["GUARD_INTERVAL"]
MRT_STATIONS_DB = CONFIG.get("mrt_stations", {})