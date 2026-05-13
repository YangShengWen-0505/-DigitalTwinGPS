import os, csv, sys, logging, threading
from datetime import datetime

current_csv_file = None
_csv_file_handle = None   # P11: 持久化檔案 Handle
_csv_writer      = None   # P11: 持久化 csv.writer
_csv_lock        = threading.Lock()  # P11: 寫入互斥鎖
sys_logger  = None
route_logger = None

class TerminalFilter(logging.Filter):
    def filter(self, record):
        if record.levelno >= logging.CRITICAL: return True
        if record.name == "RouteLogger": return True
        return False

# ── M-3: 私有工廠輔助函式，消除 init_logs / init_server_logs 之間的重複邏輯 ──

def _make_file_handler(filepath: str, level: int, formatter: logging.Formatter) -> logging.FileHandler:
    """建立並回傳一個檔案 Handler。"""
    h = logging.FileHandler(filepath, encoding='utf-8')
    h.setLevel(level)
    h.setFormatter(formatter)
    return h

def _make_term_handler(formatter: logging.Formatter) -> logging.StreamHandler:
    """建立並回傳一個套用 TerminalFilter 的 stdout Handler。"""
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.INFO)
    h.setFormatter(formatter)
    h.addFilter(TerminalFilter())
    return h

def _attach_handlers(logger_obj: logging.Logger, handlers: list, level: int = logging.DEBUG) -> None:
    """清除舊 Handler 並將新 Handler 列表掛載到 logger。"""
    for old_h in logger_obj.handlers[:]:
        old_h.close()
        logger_obj.removeHandler(old_h)
    logger_obj.setLevel(level)
    logger_obj.propagate = False
    for h in handlers:
        logger_obj.addHandler(h)

# ─────────────────────────────────────────────────────────────────────────────

def init_logs():
    global current_csv_file, sys_logger, route_logger

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(base_dir, "logs")
        today_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H-%M-%S")

        task_folder = os.path.join(log_dir, today_str, time_str)
        os.makedirs(task_folder, exist_ok=True)

        all_log_file   = os.path.join(task_folder, "all.log")
        err_log_file   = os.path.join(task_folder, "error.log")
        route_log_file = os.path.join(task_folder, "route.log")
        current_csv_file = os.path.join(task_folder, "movement.csv")

        # P11: 關閉舊的 CSV Handle（若有），再開啟新的持久 Handle
        global _csv_file_handle, _csv_writer
        if _csv_file_handle:
            try:
                _csv_file_handle.flush()
                _csv_file_handle.close()
            except Exception:
                pass
        _csv_file_handle = open(current_csv_file, mode='w', newline='', encoding='utf-8')
        _csv_writer = csv.writer(_csv_file_handle)
        _csv_writer.writerow(["Timestamp", "Latitude", "Longitude", "Action", "Note"])
        _csv_file_handle.flush()

        file_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
        term_fmt = logging.Formatter('%(message)s')

        all_h   = _make_file_handler(all_log_file,   logging.DEBUG,   file_fmt)
        err_h   = _make_file_handler(err_log_file,   logging.WARNING, file_fmt)
        route_h = _make_file_handler(route_log_file, logging.INFO,    file_fmt)
        term_h  = _make_term_handler(term_fmt)

        if not sys_logger:
            sys_logger = logging.getLogger("SystemLogger")
        _attach_handlers(sys_logger, [all_h, err_h, term_h])

        if not route_logger:
            route_logger = logging.getLogger("RouteLogger")
        _attach_handlers(route_logger, [all_h, route_h, term_h], level=logging.INFO)

        log_sys(f"=== Dedicated task log created ({today_str}/{time_str}) ===", "info")
    except Exception as e:
        print(f"[FATAL] Failed to initialize logs: {e}", file=sys.stderr)

def log_sys(message, level="info"):
    if not sys_logger: return
    level = level.lower()
    if level == "debug":    sys_logger.debug(message)
    elif level == "info":   sys_logger.info(message)
    elif level == "warning": sys_logger.warning(message)
    elif level == "error":   sys_logger.error(f"Error occurred: {message}")
    elif level == "critical": sys_logger.critical(f"\n[CRITICAL SYSTEM ERROR] {message}\n")

def log_route(message):
    if not route_logger: return
    route_logger.info(f"[ROUTE] {message}")

def log_movement(lat, lng, action, note=""):
    """P11: 使用持久 Handle 避免每次寫入都重新開啟檔案"""
    if not _csv_writer or not _csv_file_handle:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _csv_lock:
            _csv_writer.writerow([timestamp, lat, lng, action, note])
            _csv_file_handle.flush()
    except Exception as e:
        log_sys(f"CSV write failed: {e}", "error")

def init_server_logs():
    """伺服器啟動時初始化全域日誌（使用共用輔助函式）。"""
    global sys_logger
    if sys_logger: return

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    server_log_file = os.path.join(log_dir, "server.log")

    file_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    term_fmt = logging.Formatter('%(message)s')

    srv_h  = _make_file_handler(server_log_file, logging.DEBUG, file_fmt)
    term_h = _make_term_handler(term_fmt)

    sys_logger = logging.getLogger("SystemLogger")
    _attach_handlers(sys_logger, [srv_h, term_h])

# 系統啟動時自動初始化全域日誌
init_server_logs()