import csv
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_ROOT = BASE_DIR / "logs"

current_session_dir: Optional[Path] = None
current_csv_file: Optional[Path] = None

_csv_file_handle = None
_csv_writer = None
_csv_lock = threading.Lock()
_handler_lock = threading.Lock()

sys_logger = logging.getLogger("DigitalTwin.system")
route_logger = logging.getLogger("DigitalTwin.route")
security_logger = logging.getLogger("DigitalTwin.security")


class TerminalFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Keep the terminal focused on operator-facing route events and warnings;
        # detailed request/debug output still goes to file handlers.
        return record.levelno >= logging.WARNING or record.name == route_logger.name


def _formatter(with_date: bool = False) -> logging.Formatter:
    datefmt = "%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S"
    return logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt=datefmt)


def _file_handler(path: Path, level: int, with_date: bool = False) -> logging.FileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(_formatter(with_date=with_date))
    return handler


def _terminal_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(TerminalFilter())
    return handler


def _attach_handlers(logger_obj: logging.Logger, handlers: list[logging.Handler], level: int = logging.DEBUG) -> None:
    # Handlers are replaced when a new mission session starts so each task gets
    # its own all/route/error/security files.
    for old_handler in logger_obj.handlers[:]:
        old_handler.close()
        logger_obj.removeHandler(old_handler)
    logger_obj.setLevel(level)
    logger_obj.propagate = False
    for handler in handlers:
        logger_obj.addHandler(handler)


def init_server_logs() -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    server_log = LOG_ROOT / "server.log"
    security_log = LOG_ROOT / "security.log"
    term = _terminal_handler()
    with _handler_lock:
        _attach_handlers(sys_logger, [_file_handler(server_log, logging.DEBUG, with_date=True), term])
        _attach_handlers(security_logger, [_file_handler(security_log, logging.INFO, with_date=True)])


def _close_csv() -> None:
    global _csv_file_handle, _csv_writer
    with _csv_lock:
        if _csv_file_handle:
            try:
                # Flush before rotating sessions so history playback never sees
                # a partially buffered movement.csv.
                _csv_file_handle.flush()
                _csv_file_handle.close()
            finally:
                _csv_file_handle = None
                _csv_writer = None


def init_task_logs() -> dict[str, str]:
    global current_session_dir, current_csv_file, _csv_file_handle, _csv_writer

    # Each mission owns a timestamped directory to make history browsing and
    # troubleshooting independent from later restarts.
    _close_csv()
    now = datetime.now()
    current_session_dir = LOG_ROOT / now.strftime("%Y-%m-%d") / now.strftime("%H-%M-%S")
    current_session_dir.mkdir(parents=True, exist_ok=True)
    current_csv_file = current_session_dir / "movement.csv"

    with _csv_lock:
        _csv_file_handle = current_csv_file.open(mode="w", newline="", encoding="utf-8")
        _csv_writer = csv.writer(_csv_file_handle)
        _csv_writer.writerow([
            "Timestamp",
            "Latitude",
            "Longitude",
            "Action",
            "Note",
            "TimestampISO",
            "DeltaSeconds",
            "DistanceMeters",
        ])
        _csv_file_handle.flush()

    all_log = current_session_dir / "all.log"
    route_log = current_session_dir / "route.log"
    error_log = current_session_dir / "error.log"
    security_log = current_session_dir / "security.log"
    sys_term = _terminal_handler()
    route_term = _terminal_handler()

    with _handler_lock:
        all_handler = _file_handler(all_log, logging.DEBUG)
        error_handler = _file_handler(error_log, logging.WARNING)
        _attach_handlers(sys_logger, [all_handler, error_handler, sys_term])
        _attach_handlers(route_logger, [_file_handler(route_log, logging.INFO), _file_handler(all_log, logging.INFO), route_term])
        _attach_handlers(security_logger, [_file_handler(security_log, logging.INFO), _file_handler(all_log, logging.INFO)])

    log_sys(f"Task log session created: {current_session_dir}", "info")
    return get_log_status()


def get_log_status() -> dict[str, str | None]:
    return {
        "session_dir": str(current_session_dir) if current_session_dir else None,
        "movement_csv": str(current_csv_file) if current_csv_file else None,
    }


def write_mission_snapshot(mission: dict) -> None:
    if not current_session_dir:
        return
    try:
        snapshot = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mission": mission,
        }
        (current_session_dir / "mission.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log_sys(f"Mission snapshot write failed: {exc}", "warning")


def _resolve_history_session(date_value: str, session_value: str) -> Path:
    if not date_value or not session_value:
        raise FileNotFoundError("History session not found")
    session_dir = (LOG_ROOT / date_value / session_value).resolve()
    root = LOG_ROOT.resolve()
    # Resolve and check ancestry to prevent path traversal through history APIs.
    if root not in session_dir.parents:
        raise FileNotFoundError("History session not found")
    if not session_dir.exists() or not session_dir.is_dir():
        raise FileNotFoundError("History session not found")
    return session_dir


def list_history_sessions(limit: int = 100) -> list[dict]:
    sessions: list[dict] = []
    if not LOG_ROOT.exists():
        return sessions

    for date_dir in sorted(LOG_ROOT.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for session_dir in sorted(date_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            movement_csv = session_dir / "movement.csv"
            if not movement_csv.exists():
                continue

            metadata = {}
            mission_file = session_dir / "mission.json"
            if mission_file.exists():
                try:
                    metadata = json.loads(mission_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    metadata = {}

            stat = movement_csv.stat()
            sessions.append({
                "date": date_dir.name,
                "session": session_dir.name,
                "id": f"{date_dir.name}/{session_dir.name}",
                "created_at": metadata.get("created_at"),
                "start": metadata.get("mission", {}).get("init_loc", ""),
                "stops": len(metadata.get("mission", {}).get("stops", [])),
                "csv_size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
            if len(sessions) >= limit:
                return sessions
    return sessions


def read_history_csv(date_value: str, session_value: str, start_line: int = 0) -> str:
    session_dir = _resolve_history_session(date_value, session_value)
    path = session_dir / "movement.csv"
    if not path.exists():
        raise FileNotFoundError("History CSV not found")
    start_line = max(0, start_line)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return "".join(handle.readlines()[start_line:])


def read_history_log(date_value: str, session_value: str, log_name: str) -> str:
    session_dir = _resolve_history_session(date_value, session_value)
    filename = {
        "all": "all.log",
        "route": "route.log",
        "error": "error.log",
        "security": "security.log",
    }.get(log_name)
    if not filename:
        raise ValueError("Unsupported log name")
    path = session_dir / filename
    if not path.exists():
        raise FileNotFoundError("History log not found")
    return path.read_text(encoding="utf-8")


def read_current_log(log_name: str) -> str:
    if not current_session_dir:
        raise FileNotFoundError("Task not started")

    filename = {
        "all": "all.log",
        "route": "route.log",
        "error": "error.log",
        "security": "security.log",
    }.get(log_name)
    if not filename:
        raise ValueError("Unsupported log name")

    path = current_session_dir / filename
    if not path.exists():
        raise FileNotFoundError("Log file not found")
    return path.read_text(encoding="utf-8")


def read_current_csv(start_line: int = 0) -> str:
    if not current_csv_file or not current_csv_file.exists():
        raise FileNotFoundError("No movement data")
    start_line = max(0, start_line)
    with _csv_lock:
        with current_csv_file.open("r", encoding="utf-8", newline="") as handle:
            return "".join(handle.readlines()[start_line:])


def log_sys(message: str, level: str = "info") -> None:
    log_method = getattr(sys_logger, level.lower(), sys_logger.info)
    log_method(message)


def log_route(message: str) -> None:
    route_logger.info("[ROUTE] %s", message)


def log_security(message: str, level: str = "info") -> None:
    log_method = getattr(security_logger, level.lower(), security_logger.info)
    log_method(message)


def log_movement(
    lat: float,
    lng: float,
    action: str,
    note: str = "",
    *,
    sent_at: float | None = None,
    delta_seconds: float | None = None,
    distance_meters: float | None = None,
) -> None:
    if not _csv_writer or not _csv_file_handle:
        return
    sent_dt = datetime.fromtimestamp(sent_at) if sent_at else datetime.now()
    timestamp = sent_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    timestamp_iso = sent_dt.isoformat(timespec="milliseconds")
    delta_value = "" if delta_seconds is None else f"{delta_seconds:.3f}"
    distance_value = "" if distance_meters is None else f"{distance_meters:.2f}"
    try:
        with _csv_lock:
            _csv_writer.writerow([
                timestamp,
                f"{float(lat):.7f}",
                f"{float(lng):.7f}",
                action,
                note,
                timestamp_iso,
                delta_value,
                distance_value,
            ])
            _csv_file_handle.flush()
    except Exception as exc:
        log_sys(f"CSV write failed: {exc}", "error")


init_server_logs()
