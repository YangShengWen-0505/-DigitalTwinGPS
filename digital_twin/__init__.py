import hashlib
import logging

from flask import Flask, request

from digital_twin import config
from digital_twin.logger import log_sys

NOISY_GET_PATHS = {
    "/api/system_status",
    "/api/planned_route",
    "/api/navigation_history",
    "/api/csv",
    "/favicon.ico",
}


def create_app():
    app = Flask(__name__)
    app.secret_key = hashlib.sha256(config.API_SECRET_KEY.encode("utf-8")).hexdigest()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=True,
        MAX_CONTENT_LENGTH=64 * 1024,
    )

    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.before_request
    def log_request_info():
        # The dashboard polls these read-only endpoints frequently; keeping
        # them out of all.log makes mission events much easier to audit.
        if request.method == "GET" and (
            request.path in NOISY_GET_PATHS or request.path.startswith("/static/")
        ):
            return
        content_length = request.content_length or 0
        log_sys(
            f"Request: {request.method} {request.path} "
            f"from {request.remote_addr} content_length={content_length}",
            "info",
        )

    @app.after_request
    def add_security_headers(response):
        # Keep browser-facing defaults strict because this app is normally
        # exposed over Tailscale and authenticated with a shared API key.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    from digital_twin.api.routes import api_bp
    app.register_blueprint(api_bp)

    return app
