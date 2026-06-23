import threading
import time
from typing import Optional


last_sent_coords: dict[str, Optional[float]] = {"lat": None, "lng": None}
drift_state: dict[str, float] = {"lat": 0.0, "lng": 0.0}

# Worker threads receive the generation they were created with. Bumping this
# value is the cooperative cancellation signal for older mission workers.
mission_generation: int = 0
mission_active: bool = False
mission_started_at: Optional[float] = None
mission_finished_at: Optional[float] = None
last_sent_time: float = 0.0
last_api_call_time: float = 0.0

api_lock = threading.Lock()
coord_lock = threading.Lock()
send_lock = threading.Lock()
route_lock = threading.Lock()
mission_lock = threading.Lock()

current_mission: dict = {"init_loc": "", "stops": []}
planned_route: list[dict[str, float]] = []
navigation_history: list[dict] = []
mission_stats: dict[str, int | float | str | None] = {
    "total_stops": 0,
    "completed_stops": 0,
    "current_target": "",
    "status": "idle",
    "started_at": None,
    "finished_at": None,
}


def reset_runtime_position() -> None:
    # Reset only runtime drift/position data; mission metadata is managed by
    # start_mission(), stop_mission(), and complete_mission().
    with coord_lock:
        last_sent_coords.update({"lat": None, "lng": None})
        drift_state.update({"lat": 0.0, "lng": 0.0})


def start_mission(init_loc: str, stops: list[dict], generation: int) -> None:
    global mission_active, mission_started_at, mission_finished_at, current_mission, last_sent_time, last_api_call_time
    now = time.time()
    with mission_lock:
        mission_active = True
        mission_started_at = now
        mission_finished_at = None
        current_mission = {"init_loc": init_loc, "stops": stops}
        mission_stats.update({
            "total_stops": len(stops),
            "completed_stops": 0,
            "current_target": "",
            "status": "running",
            "started_at": now,
            "finished_at": None,
        })
    with send_lock:
        last_sent_time = 0.0
        last_api_call_time = 0.0
    with route_lock:
        planned_route.clear()
        navigation_history.clear()


def stop_mission(status: str = "stopped") -> None:
    global mission_active, mission_finished_at, current_mission
    now = time.time()
    with mission_lock:
        mission_active = False
        mission_finished_at = now
        current_mission = {"init_loc": "", "stops": []}
        mission_stats.update({
            "current_target": "",
            "status": status,
            "finished_at": now,
        })
    with route_lock:
        planned_route.clear()


def complete_mission() -> None:
    global mission_active, mission_finished_at
    now = time.time()
    with mission_lock:
        mission_active = False
        mission_finished_at = now
        mission_stats.update({
            "current_target": "Mission Complete",
            "status": "completed",
            "finished_at": now,
        })
    with route_lock:
        planned_route.clear()
