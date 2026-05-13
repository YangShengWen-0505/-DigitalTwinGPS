import time, threading, requests, polyline, math, urllib.parse, sys, random
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from digital_twin import config, state, logger

# 解決不穩網路環境下的 Timeout 丟失問題
retry_strategy = Retry(total=3, backoff_factor=0.3)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("http://", adapter)

def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

def get_distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def apply_gps_noise(lat, lng):
    inertia = 0.95
    new_noise_lat = random.gauss(0, 0.000003)
    new_noise_lng = random.gauss(0, 0.000003)
    state.drift_state["lat"] = state.drift_state["lat"] * inertia + new_noise_lat
    state.drift_state["lng"] = state.drift_state["lng"] * inertia + new_noise_lng
    max_drift = 0.000025
    state.drift_state["lat"] = max(min(state.drift_state["lat"], max_drift), -max_drift)
    state.drift_state["lng"] = max(min(state.drift_state["lng"], max_drift), -max_drift)
    return lat + state.drift_state["lat"], lng + state.drift_state["lng"]

def send_to_agent(cmd, lat=None, lng=None, action_name="Unknown"):
    if cmd == "move":
        now = time.time()
        if now - state.last_sent_time < 0.5:
            return
        state.last_sent_time = now

    params = {"cmd": cmd}
    if lat is not None and lng is not None:  # P7: 修正零值座標判斷 (lat=0.0 為赤道，為合法座標)
        params["lat"], params["lng"] = str(lat), str(lng)
        with state.coord_lock:
            state.last_sent_coords["lat"] = float(lat)
            state.last_sent_coords["lng"] = float(lng)
        logger.log_movement(lat, lng, action_name)
    
    with state.api_lock:
        state.last_api_call_time = time.time()
        if config.PHONE_TAILSCALE_IP:
            try:
                url = f"http://{config.PHONE_TAILSCALE_IP}:8080/gps"
                http_session.get(url, params=params, timeout=2.0)
            except requests.exceptions.Timeout:
                logger.log_sys("P2P Timeout: Phone might have bad network or screen is off.", "warning")
            except requests.exceptions.ConnectionError:
                logger.log_sys("P2P Connection Error: Cannot reach Tailscale IP.", "warning")
            except requests.exceptions.RequestException as e:
                pass

def active_wait(wait_seconds, action_name, display_msg, my_generation):
    """主動每秒發送座標的等待迴圈。M-2: 開始/結束皆寫入日誌以確保可觀測性。"""
    logger.log_sys(f"Active wait started: [{display_msg}] for {fmt_time(wait_seconds)}", "debug")
    target_time = time.time() + wait_seconds
    last_send_time = 0
    while True:
        if my_generation != state.mission_generation: return
        now = time.time()
        remaining = target_time - now
        if remaining <= 0: break

        if now - last_send_time >= 1.0:
            sys.stdout.write(f"\r   [{display_msg}]... {fmt_time(remaining)}   ")
            sys.stdout.flush()
            if state.last_sent_coords["lat"] is not None and state.last_sent_coords["lng"] is not None:  # P8: 修正零值判斷
                send_to_agent("move", state.last_sent_coords["lat"], state.last_sent_coords["lng"], action_name=action_name)
            last_send_time = time.time()

        time.sleep(0.1)
    sys.stdout.write("\r" + " "*50 + "\r")
    logger.log_sys(f"Active wait completed: [{display_msg}]", "debug")

def location_guardian_thread(my_generation):
    """最後的防線：只在 Google Maps API 卡死時幫忙補發座標。
    A-3: 若 P2P 連線持續中斷，以指數退避限制補發頻率，避免與主執行緒競爭 api_lock。
    """
    guard_backoff = 0.0
    last_guard_sent = 0.0
    while my_generation == state.mission_generation:
        time.sleep(0.1)
        now = time.time()
        if now - state.last_api_call_time > config.GUARD_INTERVAL:
            # 主流程卡死：檢查退避時間是否已到
            if now - last_guard_sent >= max(config.GUARD_INTERVAL, guard_backoff):
                if state.last_sent_coords["lat"] is not None and state.last_sent_coords["lng"] is not None:
                    send_to_agent("move", state.last_sent_coords["lat"], state.last_sent_coords["lng"], action_name="Guardian Auto-fix")
                    last_guard_sent = time.time()
                    # 每次觸發後退避時間加倍，上限 10 秒
                    guard_backoff = min(guard_backoff + 1.0, 10.0)
        else:
            # 主流程恢復正常，重置退避計數
            guard_backoff = 0.0

def smooth_move_v2(points, total_duration_sec, mode_name, my_generation, use_noise=True):
    if not points or my_generation != state.mission_generation: return
    state.drift_state["lat"], state.drift_state["lng"] = 0, 0
    real_duration = total_duration_sec / config.SPEED_MULTIPLIER
    segment_dists, total_dist = [], 0
    
    for i in range(len(points) - 1):
        d = get_distance_meters(points[i][0], points[i][1], points[i+1][0], points[i+1][1])
        segment_dists.append(d)
        total_dist += d

    if total_dist == 0 or real_duration == 0: return
    logger.log_route(f"Starting movement: {mode_name} ({int(total_dist)}m, ETA {fmt_time(real_duration)})")
    
    start_time = time.time()
    visited_stations = set() 
    next_light_check = start_time + random.randint(20, 60)
    
    while True:
        if my_generation != state.mission_generation: return
        loop_start = time.time() 
        elapsed = loop_start - start_time
        if elapsed >= real_duration: break
            
        target_dist = total_dist * (elapsed / real_duration)
        current_cumulative, found_pos = 0, False
        
        for i in range(len(segment_dists)):
            this_segment = segment_dists[i]
            if current_cumulative + this_segment >= target_dist:
                ratio = (target_dist - current_cumulative) / this_segment if this_segment > 0 else 0
                p1, p2 = points[i], points[i+1]
                cur_lat = p1[0] + (p2[0] - p1[0]) * ratio
                cur_lng = p1[1] + (p2[1] - p1[1]) * ratio
                
                if "Taking MRT" in mode_name:
                    # M-5: 高速模式下模擬位移跨度大，擴大偵測半徑避免跳過站點
                    detection_radius = max(50, 50 * config.SPEED_MULTIPLIER)
                    for st_name, st_coord in config.MRT_STATIONS_DB.items():
                        if st_name not in visited_stations and get_distance_meters(cur_lat, cur_lng, st_coord[0], st_coord[1]) < detection_radius:
                            visited_stations.add(st_name)
                            stop_time = random.randint(8, 12)
                            logger.log_route(f"Arrived at [{st_name}], stopping for {stop_time}s...")
                            active_wait(stop_time / config.SPEED_MULTIPLIER, "Station Stop", "Stopping", my_generation)

                if ("Walk" in mode_name or "Bus" in mode_name) and time.time() > next_light_check:
                    if random.random() < 0.25:
                        wait_sec = random.randint(10, 20)
                        logger.log_route(f"Traffic light RED. Waiting for {wait_sec}s...")
                        active_wait(wait_sec / config.SPEED_MULTIPLIER, "Traffic Light", "Waiting RED", my_generation)
                        logger.log_route("Traffic light GREEN. Moving!")
                    next_light_check = time.time() + random.randint(60, 120)

                final_lat, final_lng = apply_gps_noise(cur_lat, cur_lng) if use_noise and "Walk" in mode_name else (cur_lat, cur_lng)
                send_to_agent("move", lat=final_lat, lng=final_lng, action_name=mode_name)
                
                current_elapsed = time.time() - start_time
                percent = min(100, int((current_elapsed / real_duration) * 100))
                bar = '█' * int(20 * percent // 100) + '-' * (20 - int(20 * percent // 100))
                sys.stdout.write(f"\r   [{bar}] {percent}% | {fmt_time(current_elapsed)}/{fmt_time(real_duration)}")
                sys.stdout.flush()
                found_pos = True
                break
            current_cumulative += this_segment
            
        if not found_pos: break
        sleep_time = 1.0 - (time.time() - loop_start)
        if sleep_time > 0:
            for _ in range(int(sleep_time * 10)):
                if my_generation != state.mission_generation: return
                time.sleep(0.1)
            
    sys.stdout.write(f"\r   [████████████████████] 100% | Completed." + " " * 30 + "\n")
    sys.stdout.flush()

def perform_direct_walk(start_str, end_str, action_name, my_generation):
    if my_generation != state.mission_generation: return
    s_parts, e_parts = start_str.split(","), end_str.split(",")
    s_lat, s_lng, e_lat, e_lng = float(s_parts[0]), float(s_parts[1]), float(e_parts[0]), float(e_parts[1])
    dist = get_distance_meters(s_lat, s_lng, e_lat, e_lng)
    smooth_move_v2([(s_lat, s_lng), (e_lat, e_lng)], max(5, dist / 1.4), action_name, my_generation, use_noise=True)

def perform_final_approach(target_coord_str, action_name, my_generation):
    if my_generation != state.mission_generation or not target_coord_str or "," not in target_coord_str: return
    parts = target_coord_str.split(",")
    target_lat, target_lng = float(parts[0].strip()), float(parts[1].strip())
    start_lat, start_lng = state.last_sent_coords["lat"], state.last_sent_coords["lng"]
    # H-4: 防衛 last_sent_coords 尚未初始化的邊界情況，避免 TypeError
    if start_lat is None or start_lng is None:
        logger.log_sys("Final approach skipped: no previous coordinates available yet.", "warning")
        return
    dist = get_distance_meters(start_lat, start_lng, target_lat, target_lng)
    # 將速度從 1.5 降至 0.75 (約為慢步)，並增加最小等待時間至 8 秒，讓對齊過程更自然
    smooth_move_v2([(start_lat, start_lng), (target_lat, target_lng)], max(8, dist / 0.75), action_name, my_generation, use_noise=False)

def _select_transit_route(directions: list) -> dict:
    """M-4: 從 Google Directions 回應中選出含有 SUBWAY 步驟的路線，找不到則回退到第一條。"""
    for route in directions:
        for leg in route['legs']:
            for step in leg['steps']:
                td = step.get('transit_details', {}).get('line', {}).get('vehicle', {}).get('type', '')
                if step['travel_mode'] == 'TRANSIT' and td == 'SUBWAY':
                    return route
    return directions[0]


def smart_navigate(start_loc, end_loc, force_mode, transit_type, my_generation, direct_final_walk=False):
    if my_generation != state.mission_generation: return
    api_mode = "two_wheeler" if force_mode == "motorcycle" else force_mode
    api_transit_mode = None

    if api_mode == "transit":
        t_type = str(transit_type).strip().upper() if transit_type else ""
        if t_type == "MRT": api_transit_mode = ["subway"]
        elif t_type == "BUS": api_transit_mode = ["bus"]

    logger.log_route(f"Routing: {start_loc} -> {end_loc} [{api_mode}]")

    if not config.gmaps_client:
        logger.log_sys("Google Maps Client is not initialized.", "error")
        return

    try:
        directions = config.gmaps_client.directions(
            start_loc, end_loc, mode=api_mode, transit_mode=api_transit_mode,
            departure_time=datetime.now(), language="en-US", alternatives=True
        )
        if not directions: return

        selected_route = directions[0]
        if api_mode == "transit":
            selected_route = _select_transit_route(directions)
                            
        leg = selected_route['legs'][0]
        
        state.planned_route.clear()
        for step in leg['steps']:
            for p in polyline.decode(step['polyline']['points']):
                state.planned_route.append({"lat": p[0], "lng": p[1]})
                
        # Anchor the Google Maps Link using a midpoint to prevent it from recalculating a different route later
        gmaps_link = f"https://www.google.com/maps/dir/?api=1&origin={start_loc}&destination={end_loc}&travelmode={api_mode}"
        if api_mode != "transit" and len(state.planned_route) > 0:
            midpoint = state.planned_route[len(state.planned_route) // 2]
            gmaps_link += f"&waypoints={midpoint['lat']},{midpoint['lng']}"
            
        logger.log_route(f"Maps Link: {gmaps_link}")
        
        total_duration_val = sum(step['duration']['value'] for step in leg['steps'])
        real_duration = total_duration_val / config.SPEED_MULTIPLIER
        eta_time = datetime.now() + timedelta(seconds=real_duration)
        logger.log_route(f"Expected ETA: {eta_time.strftime('%H:%M:%S')}")
        

        for i, step in enumerate(leg['steps']):
            if my_generation != state.mission_generation: return
            travel_mode = step['travel_mode']
            points = polyline.decode(step['polyline']['points'])
            
            # P-2: 銜接優化 — 如果是導航的第一個步驟，將當前精準座標插入起點，防止「閃現」到路邊
            if i == 0 and state.last_sent_coords["lat"] is not None:
                curr_p = (state.last_sent_coords["lat"], state.last_sent_coords["lng"])
                if get_distance_meters(curr_p[0], curr_p[1], points[0][0], points[0][1]) > 1:
                    points.insert(0, curr_p)

            duration_val = step['duration']['value']
            mode_msg, use_noise = "Moving", False 

            if travel_mode == 'WALKING':
                if direct_final_walk and i == len(leg['steps']) - 1:
                    perform_direct_walk(f"{state.last_sent_coords['lat']},{state.last_sent_coords['lng']}", end_loc, "Direct Transfer", my_generation)
                    continue
                mode_msg, use_noise = "Walking", True 
            elif travel_mode == 'TRANSIT':
                transit = step['transit_details']
                line = transit['line'].get('short_name', 'Transit')
                mode_msg = f"Taking MRT {line}" if transit['line']['vehicle'].get('type', '') == 'SUBWAY' else f"Taking Bus {line}"
                if 'departure_time' in transit:
                    wait_sec = transit['departure_time']['value'] - datetime.now().timestamp()
                    if wait_sec > 30: active_wait(wait_sec / config.SPEED_MULTIPLIER, "Transit Wait", "Waiting Station", my_generation)
                else: active_wait(2, "Quick Boarding", "Boarding", my_generation)

            smooth_move_v2(points, duration_val, mode_msg, my_generation, use_noise=use_noise)
            
    except Exception as e: logger.log_sys(f"Navigation error: {e}", "error")

def smart_wait(time_str, skip_if_late, my_generation):
    if not time_str or time_str.strip() == "" or my_generation != state.mission_generation: return
    now = datetime.now()
    clean_time_str = time_str.strip().replace("24:", "00:")
    try:
        target_t = datetime.strptime(clean_time_str, "%H:%M").time()
        target_dt = datetime.combine(now.date(), target_t)
        if target_dt <= now:
            if skip_if_late: return
            target_dt += timedelta(days=1)

        wait_seconds = (target_dt - now).total_seconds()
        logger.log_route(f"Scheduled Wait Time target: {clean_time_str} ({int(wait_seconds)} seconds remaining)")
        active_wait(wait_seconds, "Scheduled Wait", "Standby", my_generation)
    except ValueError: pass

def mission_task(init_loc_str, stops, my_generation):
    threading.Thread(target=location_guardian_thread, args=(my_generation,), daemon=True).start()
    
    state.mission_stats.update({"total_stops": len(stops), "completed_stops": 0})
    try:
        lat_str, lng_str = init_loc_str.split(',')
        init_lat, init_lng = float(lat_str.strip()), float(lng_str.strip())
    except Exception as e:
        # H-2: 靜默失敗會讓使用者完全不知道任務為何沒有啟動
        logger.log_sys(f"Mission aborted: Invalid init_loc format '{init_loc_str}': {e}", "error")
        return
    
    current_loc_str = f"{init_lat},{init_lng}"
    with state.coord_lock:
        state.last_sent_coords.update({"lat": init_lat, "lng": init_lng})

    try:
        for idx, stop in enumerate(stops):
            if my_generation != state.mission_generation: return
            state.mission_stats["current_target"] = stop.get('name')
            
            w_time = stop.get('wait_time', '')
            if w_time:
                logger.log_route(f"Current Stop: {stop.get('name')} | Planned Wait Time: {w_time}")
            smart_wait(w_time, stop.get('skip_if_late'), my_generation)
            if my_generation != state.mission_generation: return

            smart_navigate(current_loc_str, stop.get('name'), stop.get('mode'), stop.get('transit_type', ''), my_generation)
            if stop.get('coord') and my_generation == state.mission_generation:
                perform_final_approach(stop.get('coord'), f"Stop {idx+1} Alignment", my_generation)
                
            current_loc_str = f"{state.last_sent_coords['lat']},{state.last_sent_coords['lng']}"
            state.mission_stats["completed_stops"] += 1

        state.planned_route.clear()
        state.mission_stats["current_target"] = "Mission Complete (Holding Position)"
        logger.log_route("Mission Complete! Entering Final Position Holding Mode...")
        
        # 抵達終點後，使用 active_wait 進行無限期的原地停留，每秒發送座標
        active_wait(999999, "Holding Final Position", "Mission Complete", my_generation)
        
    except Exception as e:
        logger.log_sys(f"Mission task crashed: {e}", "error")