import math
import queue
import random
import re
import sys
import threading
import time
from html import unescape
from datetime import datetime, timedelta

import polyline
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from digital_twin import config, logger, state


retry_strategy = Retry(total=3, backoff_factor=0.3)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("http://", adapter)
_phone_send_queue: queue.Queue[tuple[float, float]] = queue.Queue(maxsize=1)
_phone_worker_lock = threading.Lock()
_phone_worker_started = False


def fmt_time(seconds: float) -> str:
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


def get_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _clean_instruction(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(value or ""))).strip()


def _route_step_type(step: dict) -> str:
    travel_mode = str(step.get("travel_mode", "")).upper()
    if travel_mode == "WALKING":
        return "walk"
    if travel_mode == "TRANSIT":
        vehicle_type = step.get("transit_details", {}).get("line", {}).get("vehicle", {}).get("type", "")
        if vehicle_type == "SUBWAY":
            return "mrt"
        if vehicle_type == "BUS":
            return "bus"
        return "transit"
    return travel_mode.lower() or "move"


def _build_navigation_detail(
    selected_route: dict,
    leg: dict,
    start_loc: str,
    end_loc: str,
    api_mode: str,
    transit_type: str,
) -> dict:
    segments = []
    for index, step in enumerate(leg.get("steps", []), start=1):
        points = [
            {"lat": lat, "lng": lng}
            for lat, lng in polyline.decode(step.get("polyline", {}).get("points", ""))
        ]
        transit = step.get("transit_details", {}) or {}
        line = transit.get("line", {}) or {}
        vehicle = line.get("vehicle", {}) or {}
        segment = {
            "index": index,
            "type": _route_step_type(step),
            "travel_mode": step.get("travel_mode", ""),
            "instruction": _clean_instruction(step.get("html_instructions", "")),
            "distance_text": step.get("distance", {}).get("text", ""),
            "distance_meters": step.get("distance", {}).get("value", 0),
            "duration_text": step.get("duration", {}).get("text", ""),
            "duration_seconds": step.get("duration", {}).get("value", 0),
            "points": points,
            "points_count": len(points),
        }
        if transit:
            segment.update({
                "line_name": line.get("name", ""),
                "line_short_name": line.get("short_name", ""),
                "vehicle_type": vehicle.get("type", ""),
                "vehicle_name": vehicle.get("name", ""),
                "departure_stop": transit.get("departure_stop", {}).get("name", ""),
                "arrival_stop": transit.get("arrival_stop", {}).get("name", ""),
                "departure_time": transit.get("departure_time", {}).get("text", ""),
                "arrival_time": transit.get("arrival_time", {}).get("text", ""),
                "num_stops": transit.get("num_stops", 0),
            })
        segments.append(segment)

    return {
        "created_at": datetime.now().isoformat(timespec="milliseconds"),
        "origin": start_loc,
        "destination": end_loc,
        "mode": api_mode,
        "requested_transit_type": transit_type or "AUTO",
        "summary": selected_route.get("summary", ""),
        "distance_text": leg.get("distance", {}).get("text", ""),
        "distance_meters": leg.get("distance", {}).get("value", 0),
        "duration_text": leg.get("duration", {}).get("text", ""),
        "duration_seconds": leg.get("duration", {}).get("value", 0),
        "start_address": leg.get("start_address", ""),
        "end_address": leg.get("end_address", ""),
        "segments": segments,
    }


def _distance_from_last_sent(lat: float, lng: float) -> float | None:
    last_lat = state.last_sent_coords["lat"]
    last_lng = state.last_sent_coords["lng"]
    if last_lat is None or last_lng is None:
        return None
    return get_distance_meters(float(last_lat), float(last_lng), float(lat), float(lng))


def _send_phone_update(lat: float, lng: float) -> None:
    with state.api_lock:
        state.last_api_call_time = time.time()
        if not config.PHONE_TAILSCALE_IP:
            logger.log_sys("PHONE_TAILSCALE_IP is not configured; skipped phone update.", "warning")
            return
        params = {"lat": f"{float(lat):.7f}", "lng": f"{float(lng):.7f}"}
        try:
            # MacroDroid exposes a small HTTP server on the phone over Tailscale.
            # Query parameters are used because the phone-side macro maps them
            # directly into local variables.
            http_session.get(f"http://{config.PHONE_TAILSCALE_IP}:8080/gps", params=params, timeout=0.8)
        except requests.exceptions.Timeout:
            logger.log_sys("P2P timeout while sending GPS command.", "warning")
        except requests.exceptions.ConnectionError:
            logger.log_sys("P2P connection error while sending GPS command.", "warning")
        except requests.exceptions.RequestException as exc:
            logger.log_sys(f"P2P request failed: {exc}", "warning")


def _phone_send_worker() -> None:
    while True:
        lat, lng = _phone_send_queue.get()
        try:
            _send_phone_update(lat, lng)
        finally:
            _phone_send_queue.task_done()


def _ensure_phone_worker() -> None:
    global _phone_worker_started
    if _phone_worker_started:
        return
    with _phone_worker_lock:
        if _phone_worker_started:
            return
        threading.Thread(target=_phone_send_worker, daemon=True).start()
        _phone_worker_started = True


def _queue_phone_update(lat: float, lng: float) -> None:
    _ensure_phone_worker()
    item = (float(lat), float(lng))
    try:
        _phone_send_queue.put_nowait(item)
        return
    except queue.Full:
        pass

    try:
        _phone_send_queue.get_nowait()
        _phone_send_queue.task_done()
    except queue.Empty:
        pass

    try:
        _phone_send_queue.put_nowait(item)
    except queue.Full:
        # The worker took the replacement slot between get and put. Dropping
        # this phone update is intentional; CSV already recorded this second.
        pass


def apply_gps_noise(lat: float, lng: float) -> tuple[float, float]:
    inertia = 0.95
    state.drift_state["lat"] = state.drift_state["lat"] * inertia + random.gauss(0, 0.000003)
    state.drift_state["lng"] = state.drift_state["lng"] * inertia + random.gauss(0, 0.000003)
    max_drift = 0.000025
    state.drift_state["lat"] = max(min(state.drift_state["lat"], max_drift), -max_drift)
    state.drift_state["lng"] = max(min(state.drift_state["lng"], max_drift), -max_drift)
    return lat + state.drift_state["lat"], lng + state.drift_state["lng"]


def send_to_agent(lat: float, lng: float, action_name: str = "Unknown") -> None:
    while True:
        with state.send_lock:
            now = time.time()
            last_sent_second = int(state.last_sent_time) if state.last_sent_time else None
            current_second = int(now)
            if last_sent_second != current_second:
                delta_seconds = now - state.last_sent_time if state.last_sent_time else None
                state.last_sent_time = now
                sent_at = now
                break
            wait_seconds = (current_second + 1) - now
        if wait_seconds <= 0:
            break
        time.sleep(min(wait_seconds, 0.05))

    distance_meters = _distance_from_last_sent(lat, lng)
    with state.coord_lock:
        state.last_sent_coords.update({"lat": float(lat), "lng": float(lng)})
    logger.log_movement(
        float(lat),
        float(lng),
        action_name,
        sent_at=sent_at,
        delta_seconds=delta_seconds,
        distance_meters=distance_meters,
    )
    _queue_phone_update(float(lat), float(lng))


def active_wait(wait_seconds: float, action_name: str, display_msg: str, my_generation: int) -> None:
    logger.log_sys(f"Active wait started: {display_msg} for {fmt_time(wait_seconds)}", "debug")
    target_time = time.time() + max(0, wait_seconds)
    next_send_second = int(time.time())
    while my_generation == state.mission_generation:
        now = time.time()
        remaining = target_time - now
        if remaining <= 0:
            break
        if int(now) >= next_send_second:
            sys.stdout.write(f"\r   [{display_msg}] {fmt_time(remaining)}   ")
            sys.stdout.flush()
            if state.last_sent_coords["lat"] is not None and state.last_sent_coords["lng"] is not None:
                send_to_agent(state.last_sent_coords["lat"], state.last_sent_coords["lng"], action_name)
            next_send_second = int(time.time()) + 1
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()
    logger.log_sys(f"Active wait completed: {display_msg}", "debug")


def location_guardian_thread(my_generation: int) -> None:
    guard_backoff = 0.0
    last_guard_sent = 0.0
    while my_generation == state.mission_generation:
        time.sleep(0.1)
        now = time.time()
        if now - state.last_api_call_time <= config.GUARD_INTERVAL:
            guard_backoff = 0.0
            continue
        if now - last_guard_sent < max(config.GUARD_INTERVAL, guard_backoff):
            continue
        if state.last_sent_coords["lat"] is None or state.last_sent_coords["lng"] is None:
            continue
        # Some Android mock-location stacks stop updating when no fresh intent
        # arrives. Guardian resends the last known coordinate without changing
        # the route state.
        send_to_agent(state.last_sent_coords["lat"], state.last_sent_coords["lng"], "Guardian Auto-fix")
        last_guard_sent = time.time()
        guard_backoff = min(guard_backoff + 1.0, 10.0)


def _route_segments(points: list[tuple[float, float]]) -> tuple[list[float], float]:
    segment_dists, total_dist = [], 0.0
    for index in range(len(points) - 1):
        dist = get_distance_meters(points[index][0], points[index][1], points[index + 1][0], points[index + 1][1])
        segment_dists.append(dist)
        total_dist += dist
    return segment_dists, total_dist


def _maybe_wait_for_station(mode_name: str, lat: float, lng: float, visited_stations: set[str], my_generation: int) -> None:
    if "Taking MRT" not in mode_name:
        return
    # MRT station stops are simulated only for MRT movement; user-defined custom
    # station groups were removed because non-MRT modes should move continuously.
    detection_radius = max(50, 50 * config.SPEED_MULTIPLIER)
    for station_name, station_coord in config.MRT_STATIONS_DB.items():
        if station_name in visited_stations:
            continue
        if get_distance_meters(lat, lng, station_coord[0], station_coord[1]) < detection_radius:
            visited_stations.add(station_name)
            stop_time = random.randint(8, 12)
            logger.log_route(f"Arrived at [{station_name}], stopping for {stop_time}s.")
            active_wait(stop_time / config.SPEED_MULTIPLIER, "Station Stop", "Stopping", my_generation)


def smooth_move_v2(points: list[tuple[float, float]], total_duration_sec: float, mode_name: str, my_generation: int, use_noise: bool = True) -> None:
    if len(points) < 2 or my_generation != state.mission_generation:
        return

    # Every long-running movement loop is generation-gated so stop/restart can
    # interrupt it without forcefully killing Python threads.
    state.drift_state.update({"lat": 0.0, "lng": 0.0})
    real_duration = max(0.1, total_duration_sec / config.SPEED_MULTIPLIER)
    segment_dists, total_dist = _route_segments(points)
    if total_dist <= 0:
        return

    logger.log_route(f"Starting movement: {mode_name} ({int(total_dist)}m, ETA {fmt_time(real_duration)})")
    start_time = time.time()
    visited_stations: set[str] = set()
    next_light_check = start_time + random.randint(20, 60)

    while my_generation == state.mission_generation:
        loop_start = time.time()
        elapsed = loop_start - start_time
        if elapsed >= real_duration:
            break

        target_dist = total_dist * (elapsed / real_duration)
        current_dist = 0.0
        found_position = False

        for index, segment_dist in enumerate(segment_dists):
            if current_dist + segment_dist < target_dist:
                current_dist += segment_dist
                continue

            ratio = (target_dist - current_dist) / segment_dist if segment_dist > 0 else 0
            p1, p2 = points[index], points[index + 1]
            cur_lat = p1[0] + (p2[0] - p1[0]) * ratio
            cur_lng = p1[1] + (p2[1] - p1[1]) * ratio

            _maybe_wait_for_station(mode_name, cur_lat, cur_lng, visited_stations, my_generation)

            if ("Walk" in mode_name or "Bus" in mode_name) and time.time() > next_light_check:
                if random.random() < 0.25:
                    wait_sec = random.randint(10, 20)
                    logger.log_route(f"Traffic light red. Waiting for {wait_sec}s.")
                    active_wait(wait_sec / config.SPEED_MULTIPLIER, "Traffic Light", "Waiting RED", my_generation)
                    logger.log_route("Traffic light green. Moving.")
                next_light_check = time.time() + random.randint(60, 120)

            final_lat, final_lng = apply_gps_noise(cur_lat, cur_lng) if use_noise and "Walk" in mode_name else (cur_lat, cur_lng)
            send_to_agent(final_lat, final_lng, mode_name)

            percent = min(100, int(((time.time() - start_time) / real_duration) * 100))
            bar = "#" * int(20 * percent // 100) + "-" * (20 - int(20 * percent // 100))
            sys.stdout.write(f"\r   [{bar}] {percent}% | {fmt_time(time.time() - start_time)}/{fmt_time(real_duration)}")
            sys.stdout.flush()
            found_position = True
            break

        if not found_position:
            break

        sleep_time = 1.0 - (time.time() - loop_start)
        if sleep_time > 0:
            time.sleep(sleep_time)

    if my_generation == state.mission_generation:
        sys.stdout.write("\r   [####################] 100% | Completed.\n")
    else:
        sys.stdout.write("\r   [Movement aborted by stop request]\n")
        logger.log_route(f"Movement aborted: {mode_name}")
    sys.stdout.flush()


def perform_direct_walk(start_str: str, end_str: str, action_name: str, my_generation: int) -> None:
    if my_generation != state.mission_generation:
        return
    s_lat, s_lng = [float(part.strip()) for part in start_str.split(",", 1)]
    e_lat, e_lng = [float(part.strip()) for part in end_str.split(",", 1)]
    dist = get_distance_meters(s_lat, s_lng, e_lat, e_lng)
    smooth_move_v2([(s_lat, s_lng), (e_lat, e_lng)], max(5, dist / 1.4), action_name, my_generation, use_noise=True)


def perform_final_approach(target_coord_str: str, action_name: str, my_generation: int) -> None:
    if my_generation != state.mission_generation or not target_coord_str:
        return
    target_lat, target_lng = [float(part.strip()) for part in target_coord_str.split(",", 1)]
    start_lat, start_lng = state.last_sent_coords["lat"], state.last_sent_coords["lng"]
    if start_lat is None or start_lng is None:
        logger.log_sys("Final approach skipped: no previous coordinates available.", "warning")
        return
    dist = get_distance_meters(start_lat, start_lng, target_lat, target_lng)
    smooth_move_v2([(start_lat, start_lng), (target_lat, target_lng)], max(8, dist / 0.75), action_name, my_generation, use_noise=False)


def _select_transit_route(directions: list[dict]) -> dict:
    for route in directions:
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                vehicle_type = step.get("transit_details", {}).get("line", {}).get("vehicle", {}).get("type", "")
                if step.get("travel_mode") == "TRANSIT" and vehicle_type == "SUBWAY":
                    return route
    return directions[0]


def smart_navigate(start_loc: str, end_loc: str, force_mode: str, transit_type: str, my_generation: int, direct_final_walk: bool = False) -> None:
    if my_generation != state.mission_generation:
        return

    api_mode = "two_wheeler" if force_mode == "motorcycle" else force_mode
    api_transit_mode = None
    if api_mode == "transit":
        transit_type = (transit_type or "").strip().upper()
        if transit_type == "MRT":
            api_transit_mode = ["subway"]
        elif transit_type == "BUS":
            api_transit_mode = ["bus"]

    logger.log_route(f"Routing: {start_loc} -> {end_loc} [{api_mode}]")
    if not config.gmaps_client:
        logger.log_sys("Google Maps Client is not initialized.", "error")
        return

    try:
        directions = config.gmaps_client.directions(
            start_loc,
            end_loc,
            mode=api_mode,
            transit_mode=api_transit_mode,
            departure_time=datetime.now(),
            language="en-US",
            alternatives=True,
        )
        if not directions:
            logger.log_route("No route returned by Google Maps.")
            return

        selected_route = _select_transit_route(directions) if api_mode == "transit" else directions[0]
        leg = selected_route["legs"][0]
        navigation_detail = _build_navigation_detail(selected_route, leg, start_loc, end_loc, api_mode, transit_type)
        with state.route_lock:
            state.navigation_history.append(navigation_detail)

            state.planned_route.clear()
            for step in leg["steps"]:
                for lat, lng in polyline.decode(step["polyline"]["points"]):
                    state.planned_route.append({"lat": lat, "lng": lng})

        gmaps_link = f"https://www.google.com/maps/dir/?api=1&origin={start_loc}&destination={end_loc}&travelmode={api_mode}"
        if api_mode != "transit" and state.planned_route:
            midpoint = state.planned_route[len(state.planned_route) // 2]
            gmaps_link += f"&waypoints={midpoint['lat']},{midpoint['lng']}"
        logger.log_route(f"Maps Link: {gmaps_link}")

        total_duration = sum(step["duration"]["value"] for step in leg["steps"])
        eta_time = datetime.now() + timedelta(seconds=total_duration / config.SPEED_MULTIPLIER)
        logger.log_route(f"Expected ETA: {eta_time.strftime('%H:%M:%S')}")

        for index, step in enumerate(leg["steps"]):
            if my_generation != state.mission_generation:
                return
            points = polyline.decode(step["polyline"]["points"])
            if not points:
                continue

            if index == 0 and state.last_sent_coords["lat"] is not None:
                current_point = (state.last_sent_coords["lat"], state.last_sent_coords["lng"])
                if get_distance_meters(current_point[0], current_point[1], points[0][0], points[0][1]) > 1:
                    points.insert(0, current_point)

            mode_msg, use_noise = "Moving", False
            if step["travel_mode"] == "WALKING":
                if direct_final_walk and index == len(leg["steps"]) - 1:
                    perform_direct_walk(f"{state.last_sent_coords['lat']},{state.last_sent_coords['lng']}", end_loc, "Direct Transfer", my_generation)
                    continue
                mode_msg, use_noise = "Walking", True
            elif step["travel_mode"] == "TRANSIT":
                transit = step["transit_details"]
                line = transit["line"].get("short_name", "Transit")
                vehicle_type = transit["line"].get("vehicle", {}).get("type", "")
                # AUTO transit accepts Google's route choice, while MRT/BUS
                # requests bias selection before this step is interpreted.
                mode_msg = f"Taking MRT {line}" if vehicle_type == "SUBWAY" else f"Taking Bus {line}"
                departure = transit.get("departure_time", {}).get("value")
                if departure:
                    wait_sec = departure - datetime.now().timestamp()
                    if wait_sec > 30:
                        active_wait(wait_sec / config.SPEED_MULTIPLIER, "Transit Wait", "Waiting Station", my_generation)
                else:
                    active_wait(2, "Quick Boarding", "Boarding", my_generation)

            smooth_move_v2(points, step["duration"]["value"], mode_msg, my_generation, use_noise=use_noise)
    except Exception as exc:
        logger.log_sys(f"Navigation error: {exc}", "error")


def smart_wait(time_str: str, skip_if_late: bool, my_generation: int) -> None:
    if not time_str or my_generation != state.mission_generation:
        return
    try:
        now = datetime.now()
        clean_time = time_str.strip().replace("24:", "00:")
        target_time = datetime.strptime(clean_time, "%H:%M").time()
        target_dt = datetime.combine(now.date(), target_time)
        if target_dt <= now:
            if skip_if_late:
                logger.log_route(f"Scheduled wait skipped because target time passed: {clean_time}")
                return
            target_dt += timedelta(days=1)
        wait_seconds = (target_dt - now).total_seconds()
        logger.log_route(f"Scheduled wait target: {clean_time} ({int(wait_seconds)}s remaining)")
        active_wait(wait_seconds, "Scheduled Wait", "Standby", my_generation)
    except ValueError:
        logger.log_sys(f"Invalid wait_time ignored: {time_str}", "warning")


def mission_task(init_loc_str: str, stops: list[dict], my_generation: int) -> None:
    # The guardian shares the mission generation so it exits with the same
    # cooperative cancellation signal as the main route worker.
    threading.Thread(target=location_guardian_thread, args=(my_generation,), daemon=True).start()
    state.mission_stats.update({"total_stops": len(stops), "completed_stops": 0, "status": "running"})

    try:
        init_lat, init_lng = [float(part.strip()) for part in init_loc_str.split(",", 1)]
    except Exception as exc:
        logger.log_sys(f"Mission aborted: invalid init_loc '{init_loc_str}': {exc}", "error")
        state.stop_mission("failed")
        return

    current_loc = f"{init_lat},{init_lng}"
    with state.coord_lock:
        state.last_sent_coords.update({"lat": init_lat, "lng": init_lng})

    try:
        for index, stop in enumerate(stops):
            if my_generation != state.mission_generation:
                logger.log_route("Mission aborted before next stop.")
                return
            state.mission_stats.update({"current_target": stop.get("name", ""), "status": "running"})

            wait_time = stop.get("wait_time", "")
            if wait_time:
                logger.log_route(f"Current stop: {stop.get('name')} | planned wait: {wait_time}")
            smart_wait(wait_time, stop.get("skip_if_late", False), my_generation)
            if my_generation != state.mission_generation:
                logger.log_route("Mission aborted during scheduled wait.")
                return

            smart_navigate(current_loc, stop.get("name", ""), stop.get("mode", "walking"), stop.get("transit_type", ""), my_generation)
            if my_generation != state.mission_generation:
                logger.log_route("Mission aborted during navigation.")
                return
            if stop.get("coord") and my_generation == state.mission_generation:
                perform_final_approach(stop["coord"], f"Stop {index + 1} Alignment", my_generation)
                if my_generation != state.mission_generation:
                    logger.log_route("Mission aborted during final alignment.")
                    return

            current_loc = f"{state.last_sent_coords['lat']},{state.last_sent_coords['lng']}"
            state.mission_stats["completed_stops"] += 1

        state.planned_route.clear()
        state.mission_stats.update({"current_target": "Mission Complete (Holding Position)", "status": "holding"})
        logger.log_route("Mission complete. Holding final position.")
        active_wait(999999, "Holding Final Position", "Mission Complete", my_generation)
    except Exception as exc:
        logger.log_sys(f"Mission task crashed: {exc}", "error")
        state.stop_mission("failed")
