import os, threading, time, itertools, requests, psutil
from flask import Blueprint, request, jsonify, render_template

from digital_twin import state, logger, config
from digital_twin.core.navigation import mission_task, send_to_agent
from digital_twin.api.middleware import require_api_key

api_bp = Blueprint('api', __name__)

# M-1: stop_task 支援 GET/POST，增加手機端相容性
@api_bp.route('/stop_task', methods=['GET', 'POST'])
@require_api_key
def stop_task_route():
    state.mission_generation += 1
    logger.log_sys("Mission abort command received. Cleaning up...", "critical")
    try:
        send_to_agent("stop")
    except Exception as e:
        logger.log_sys(f"Warning: Could not notify phone of stop: {e}", "warning")
    
    state.active_mission_uuid = None
    state.current_mission = {"init_loc": "", "stops": []}
    state.planned_route.clear()
    
    return jsonify({"status": "Mission Aborted", "generation": state.mission_generation}), 200


@api_bp.route('/start_task', methods=['POST'])
@require_api_key
def start_task():
    data = request.json
    if not data:
        logger.log_sys("Task startup failed: Invalid or missing JSON data. Check Content-Type header and JSON format.", "error")
        return jsonify({"error": "No JSON Data"}), 400

    uuid     = data.get('uuid', 'Agent')
    init_loc = data.get('init_loc')
    stops    = data.get('stops', [])

    # L-1: 驗證 stops 每個元素皆包含必要欄位
    required_keys = {'name', 'mode'}
    invalid_indices = [
        i for i, s in enumerate(stops)
        if not isinstance(s, dict) or not required_keys.issubset(s.keys())
    ]
    if invalid_indices:
        logger.log_sys(f"Task startup failed: Stops at indices {invalid_indices} missing 'name'/'mode'.", "error")
        return jsonify({"error": f"Each stop requires 'name' and 'mode'. Invalid indices: {invalid_indices}"}), 400

    if stops and init_loc:
        # P5: 先遞增世代計數器搶佔舊任務，給舊執行緒 200ms 感知並退出
        state.mission_generation += 1
        current_gen = state.mission_generation
        time.sleep(0.2)

        state.active_mission_uuid = uuid
        logger.init_logs()
        state.current_mission = {"init_loc": init_loc, "stops": stops}

        logger.log_route(f"Digital Twin Mission Started! Executing P2P Device...")
        logger.log_route(f"Start: {init_loc}, Stops: {len(stops)}")

        threading.Thread(target=mission_task, args=(init_loc, stops, current_gen), daemon=True).start()
        return jsonify({"status": "Mission Started"}), 200

    logger.log_sys(f"Task startup failed: Missing required arguments. init_loc: '{init_loc}', stops: {stops}", "error")
    return jsonify({"error": "Missing Args"}), 400

@api_bp.route('/api/system_status', methods=['GET'])
def get_system_status():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "devices": 1 if state.active_mission_uuid else 0,
        "active_device": state.active_mission_uuid,
        "mission_stats": state.mission_stats,
        "p2p_target": config.PHONE_TAILSCALE_IP
    })

@api_bp.route('/api/planned_route', methods=['GET'])
def get_planned_route():
    return jsonify(state.planned_route)

@api_bp.route('/api/csv', methods=['GET'])
def get_csv_data():
    try:
        if logger.current_csv_file and os.path.exists(logger.current_csv_file):
            start_line = request.args.get('start_line', type=int, default=0)
            with logger._csv_lock:
                with open(logger.current_csv_file, 'r', encoding='utf-8') as f:
                    lines = list(itertools.islice(f, start_line, None))
            return "".join(lines), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        return "No Data", 404
    except Exception as e:
        logger.log_sys(f"Error reading CSV: {e}", "error")
        return f"Error: {e}", 500

@api_bp.route('/api/log/<log_name>', methods=['GET'])
def get_log_data(log_name):
    try:
        if not logger.current_csv_file: return "Task not started", 404
        task_folder = os.path.dirname(logger.current_csv_file)
        target_file = {"all": "all.log", "route": "route.log", "error": "error.log"}.get(log_name)
        if target_file and os.path.exists(os.path.join(task_folder, target_file)):
            with open(os.path.join(task_folder, target_file), 'r', encoding='utf-8') as f:
                return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        return "Log file not found", 404
    except Exception as e:
        logger.log_sys(f"Error reading log {log_name}: {e}", "error")
        return f"Error: {e}", 500

@api_bp.route('/api/mission', methods=['GET'])
def get_mission_data():
    return jsonify(state.current_mission)

@api_bp.route('/map', methods=['GET'])
def show_map():
    return render_template('map.html')