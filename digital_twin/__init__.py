import logging
from flask import Flask, request
from digital_twin.logger import log_sys

def create_app():
    app = Flask(__name__)
    # 關閉常規日誌，避免終端機雜亂
    flask_log = logging.getLogger('werkzeug')
    flask_log.setLevel(logging.ERROR)
    
    @app.before_request
    def log_request_info():
        raw_key = request.headers.get('X-API-Key', '')
        masked_key = f"{raw_key[:4]}..." if len(raw_key) > 4 else ("****" if raw_key else "None")
        content_type = request.headers.get('Content-Type', 'None')
        log_sys(f"Request: {request.method} {request.url} | X-API-Key: {masked_key} | Content-Type: {content_type}", "info")
        if request.is_json:
            log_sys(f"Payload (JSON): {request.get_json(silent=True)}", "info")
        elif request.data:
            log_sys(f"Payload (Raw): {request.data.decode('utf-8', errors='ignore')}", "info")
        
    from digital_twin.api.routes import api_bp
    app.register_blueprint(api_bp)
    
    return app