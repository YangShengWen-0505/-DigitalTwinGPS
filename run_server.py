import os
from digital_twin import create_app

app = create_app()

if __name__ == "__main__":
    pc_tailscale_ip = os.getenv("PC_TAILSCALE_IP", "").strip()
    use_caddy       = os.getenv("USE_CADDY", "false").lower() == "true"
    flask_port      = int(os.getenv("FLASK_PORT", "5050"))

    if not pc_tailscale_ip:
        print("[WARNING] PC_TAILSCALE_IP is not set in .env!")
        print("[WARNING] Network URL in the banner below will be incorrect.")
        print("[WARNING] Please set PC_TAILSCALE_IP to your PC's Tailscale virtual IP (100.x.x.x).")
        pc_tailscale_ip = "<PC_TAILSCALE_IP_NOT_SET>"

    print("=====================================================")
    print("[SYSTEM] Digital Twin Server Starting")
    if use_caddy:
        print("[SYSTEM] Mode    : Caddy Reverse Proxy (HTTPS handled by Caddy)")
        print(f"[SYSTEM] Local   : https://localhost/map")
        print(f"[SYSTEM] Network : https://{pc_tailscale_ip}/map")
    else:
        print("[SYSTEM] Mode    : Development (adhoc SSL)")
        print(f"[SYSTEM] Local   : https://localhost:{flask_port}/map")
        print(f"[SYSTEM] Network : https://{pc_tailscale_ip}:{flask_port}/map")
    print("=====================================================")

    try:
        if use_caddy:
            # Caddy 模式 — Flask 只聽 localhost HTTP，TLS 由 Caddy 處理
            app.run(port=flask_port, host='127.0.0.1', use_reloader=False)
        else:
            # 開發模式：使用 adhoc 自簽憑證，監聽所有網路介面
            app.run(port=flask_port, host='0.0.0.0', use_reloader=False, ssl_context='adhoc')
    except Exception as e:
        print(f"Startup Failed: {e}")