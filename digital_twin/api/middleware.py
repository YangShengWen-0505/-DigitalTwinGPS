from functools import wraps
from flask import request, jsonify
from digital_twin import config, logger

def require_api_key(f):
    """API 安全驗證中間件，檢查 X-API-Key Header"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            logger.log_sys("Authorization failed: Missing X-API-Key header.", "error")
            return jsonify({"error": "Unauthorized Access. Missing API Key."}), 401
        if api_key != config.API_SECRET_KEY:
            logger.log_sys(f"Authorization failed: Invalid API Key received (first 4 chars: '{api_key[:4]}...').", "error")
            return jsonify({"error": "Unauthorized Access. Invalid API Key."}), 401
            
        logger.log_sys("Authorization successful: API Key is valid.", "info")
        return f(*args, **kwargs)
    return decorated_function