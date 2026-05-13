import threading
from typing import Optional

# ── 座標狀態 ───────────────────────────────────────────────────────────
last_sent_coords: dict[str, Optional[float]] = {"lat": None, "lng": None}
drift_state: dict[str, float] = {"lat": 0.0, "lng": 0.0}

# ── 任務控制 ───────────────────────────────────────────────────────────
mission_generation: int = 0
last_sent_time: float = 0.0
last_api_call_time: float = 0.0

api_lock: threading.Lock = threading.Lock()
coord_lock: threading.Lock = threading.Lock()

# ── 任務資訊 ───────────────────────────────────────────────────────────
active_mission_uuid: Optional[str] = None
current_mission: dict = {"init_loc": "", "stops": []}
planned_route: list[dict[str, float]] = []
mission_stats: dict[str, int | str] = {"total_stops": 0, "completed_stops": 0, "current_target": ""}