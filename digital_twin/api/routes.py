import hmac
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from digital_twin import config, logger, state
from digital_twin.api.middleware import has_valid_api_key, require_api_key
from digital_twin.core.navigation import mission_task

api_bp = Blueprint("api", __name__)

ALLOWED_MODES = {"walking", "transit", "motorcycle"}
ALLOWED_TRANSIT_TYPES = {"", "AUTO", "MRT", "BUS"}


def _parse_coord(value: str, field_name: str) -> tuple[float, float]:
    if not isinstance(value, str) or "," not in value:
        raise ValueError(f"{field_name} must be 'lat,lng'")
    lat_raw, lng_raw = value.split(",", 1)
    lat, lng = float(lat_raw.strip()), float(lng_raw.strip())
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError(f"{field_name} is out of range")
    return lat, lng


def _validate_stop(stop: dict, index: int) -> dict:
    if not isinstance(stop, dict):
        raise ValueError(f"stops[{index}] must be an object")

    name = str(stop.get("name", "")).strip()
    mode = str(stop.get("mode", "")).strip()
    transit_type = str(stop.get("transit_type", "")).strip().upper()
    wait_time = str(stop.get("wait_time", "")).strip()
    coord = str(stop.get("coord", "")).strip()
    skip_if_late = bool(stop.get("skip_if_late", False))

    if not name:
        raise ValueError(f"stops[{index}].name is required")
    if mode not in ALLOWED_MODES:
        raise ValueError(f"stops[{index}].mode must be one of {sorted(ALLOWED_MODES)}")
    if transit_type not in ALLOWED_TRANSIT_TYPES:
        raise ValueError(f"stops[{index}].transit_type must be AUTO, MRT, BUS, or empty")
    if transit_type == "AUTO":
        transit_type = ""
    if mode != "transit":
        transit_type = ""
    if wait_time:
        datetime.strptime(wait_time.replace("24:", "00:"), "%H:%M")
    if coord:
        _parse_coord(coord, f"stops[{index}].coord")

    return {
        "name": name,
        "mode": mode,
        "transit_type": transit_type,
        "wait_time": wait_time,
        "skip_if_late": skip_if_late,
        "coord": coord,
    }


def _validate_mission_payload(data: dict) -> tuple[str, list[dict]]:
    if not isinstance(data, dict):
        raise ValueError("JSON body is required")
    init_loc = str(data.get("init_loc", "")).strip()
    stops = data.get("stops", [])
    _parse_coord(init_loc, "init_loc")
    if not isinstance(stops, list) or not stops:
        raise ValueError("stops must be a non-empty array")
    if len(stops) > 50:
        raise ValueError("stops cannot exceed 50")
    return init_loc, [_validate_stop(stop, index) for index, stop in enumerate(stops)]


def _format_ts(value):
    if not value:
        return None
    return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")


@api_bp.route("/", methods=["GET"])
def index():
    return redirect(url_for("api.show_map"))


@api_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        key = request.form.get("api_key", "")
        if key and hmac.compare_digest(key, config.API_SECRET_KEY):
            session["authenticated"] = True
            logger.log_security(f"Dashboard login succeeded from {request.remote_addr}")
            return redirect(url_for("api.show_map"))
        logger.log_security(f"Dashboard login failed from {request.remote_addr}", "warning")
        return render_template("login.html", error="Invalid API key."), 401
    return render_template("login.html", error="")


@api_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("api.login"))


@api_bp.route("/stop_task", methods=["GET", "POST"])
@require_api_key(allow_session=False)
def stop_task_route():
    # Increment first so active worker threads observe cancellation quickly.
    state.mission_generation += 1
    logger.log_sys("Mission abort command received. Cleaning up.", "warning")
    state.stop_mission("aborted")
    return jsonify({"status": "Mission Aborted", "generation": state.mission_generation}), 200


@api_bp.route("/start_task", methods=["POST"])
@require_api_key(allow_session=False)
def start_task():
    try:
        init_loc, stops = _validate_mission_payload(request.get_json(silent=True))
    except ValueError as exc:
        logger.log_sys(f"Task startup failed: {exc}", "error")
        return jsonify({"error": str(exc)}), 400

    previous_was_active = state.mission_active
    # A new start request intentionally supersedes any active mission. The
    # generation bump asks older workers to exit before the new log session is
    # created, which keeps session boundaries readable.
    state.mission_generation += 1
    current_gen = state.mission_generation
    if previous_was_active:
        logger.log_sys("Active mission superseded by a new start request.", "info")
        logger.log_route("Mission superseded by a new start request.")
        state.stop_mission("restarted")
        time.sleep(0.5)
    else:
        time.sleep(0.2)

    logger.init_task_logs()
    state.start_mission(init_loc, stops, current_gen)
    logger.write_mission_snapshot(state.current_mission)

    logger.log_route("Digital Twin mission started.")
    if previous_was_active:
        logger.log_route("Previous active mission was replaced by this mission.")
    logger.log_route(f"Start: {init_loc}, Stops: {len(stops)}")

    threading.Thread(target=mission_task, args=(init_loc, stops, current_gen), daemon=True).start()
    return jsonify({"status": "Mission Started", "generation": current_gen}), 200


@api_bp.route("/api/system_status", methods=["GET"])
@require_api_key()
def get_system_status():
    elapsed = None
    if state.mission_started_at and state.mission_active:
        elapsed = int(time.time() - state.mission_started_at)

    return jsonify({
        "mission_active": state.mission_active,
        "mission_generation": state.mission_generation,
        "mission_stats": state.mission_stats,
        "started_at": _format_ts(state.mission_started_at),
        "finished_at": _format_ts(state.mission_finished_at),
        "elapsed_seconds": elapsed,
        "last_position": state.last_sent_coords,
        "planned_route_points": len(state.planned_route),
        "p2p_target": config.PHONE_TAILSCALE_IP,
        "speed_multiplier": config.SPEED_MULTIPLIER,
        "guard_interval": config.GUARD_INTERVAL,
        "log_session": logger.get_log_status(),
    })


@api_bp.route("/api/planned_route", methods=["GET"])
@require_api_key()
def get_planned_route():
    with state.route_lock:
        return jsonify(list(state.planned_route))


@api_bp.route("/api/navigation_history", methods=["GET"])
@require_api_key()
def get_navigation_history():
    with state.route_lock:
        return jsonify(list(state.navigation_history))


@api_bp.route("/api/csv", methods=["GET"])
@require_api_key()
def get_csv_data():
    try:
        start_line = request.args.get("start_line", type=int, default=0)
        return logger.read_current_csv(start_line), 200, {"Content-Type": "text/plain; charset=utf-8"}
    except FileNotFoundError:
        return "No Data", 404
    except Exception as exc:
        logger.log_sys(f"Error reading CSV: {exc}", "error")
        return f"Error: {exc}", 500


@api_bp.route("/api/log/<log_name>", methods=["GET"])
@require_api_key()
def get_log_data(log_name):
    try:
        return logger.read_current_log(log_name), 200, {"Content-Type": "text/plain; charset=utf-8"}
    except ValueError:
        return "Unsupported log name", 400
    except FileNotFoundError as exc:
        return str(exc), 404
    except Exception as exc:
        logger.log_sys(f"Error reading log {log_name}: {exc}", "error")
        return f"Error: {exc}", 500


@api_bp.route("/api/mission", methods=["GET"])
@require_api_key()
def get_mission_data():
    return jsonify(state.current_mission)


@api_bp.route("/api/history", methods=["GET"])
@require_api_key()
def get_history_sessions():
    limit = request.args.get("limit", type=int, default=100)
    limit = min(max(limit, 1), 500)
    return jsonify(logger.list_history_sessions(limit))


@api_bp.route("/api/history/<date_value>/<session_value>/csv", methods=["GET"])
@require_api_key()
def get_history_csv(date_value, session_value):
    try:
        start_line = request.args.get("start_line", type=int, default=0)
        return logger.read_history_csv(date_value, session_value, start_line), 200, {"Content-Type": "text/plain; charset=utf-8"}
    except FileNotFoundError as exc:
        return str(exc), 404
    except Exception as exc:
        logger.log_sys(f"Error reading history CSV: {exc}", "error")
        return f"Error: {exc}", 500


@api_bp.route("/api/history/<date_value>/<session_value>/log/<log_name>", methods=["GET"])
@require_api_key()
def get_history_log(date_value, session_value, log_name):
    try:
        return logger.read_history_log(date_value, session_value, log_name), 200, {"Content-Type": "text/plain; charset=utf-8"}
    except ValueError:
        return "Unsupported log name", 400
    except FileNotFoundError as exc:
        return str(exc), 404
    except Exception as exc:
        logger.log_sys(f"Error reading history log: {exc}", "error")
        return f"Error: {exc}", 500


@api_bp.route("/map", methods=["GET"])
def show_map():
    key = request.args.get("key", "")
    if key and hmac.compare_digest(key, config.API_SECRET_KEY):
        session["authenticated"] = True
        return redirect(url_for("api.show_map"))
    if not session.get("authenticated") and not has_valid_api_key():
        return redirect(url_for("api.login"))
    return render_template("map.html")
