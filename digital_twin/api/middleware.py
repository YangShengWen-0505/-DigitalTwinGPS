import hmac
from functools import wraps

from flask import jsonify, request, session

from digital_twin import config, logger


def mask_secret(value: str | None) -> str:
    if not value:
        return "None"
    return f"{value[:4]}..." if len(value) > 4 else "****"


def has_valid_api_key() -> bool:
    api_key = request.headers.get("X-API-Key", "")
    return bool(api_key) and hmac.compare_digest(api_key, config.API_SECRET_KEY)


def has_valid_session() -> bool:
    return bool(session.get("authenticated"))


def require_api_key(allow_session: bool = True):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if has_valid_api_key() or (allow_session and has_valid_session()):
                return f(*args, **kwargs)

            logger.log_security(
                f"Unauthorized request: {request.method} {request.path} "
                f"from {request.remote_addr}; key={mask_secret(request.headers.get('X-API-Key'))}",
                "warning",
            )
            return jsonify({"error": "Unauthorized"}), 401

        return decorated_function

    return decorator
