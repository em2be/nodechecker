import json
import os
import sys
import time
import requests

CONFIG_FILE = "inbound_config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(
            f"❌ Configuration file '{CONFIG_FILE}' not found in {os.getcwd()}"
        )
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error reading {CONFIG_FILE}: {e}")
        return None


def get_session(panel_url, username, password, base_path=""):
    session = requests.Session()
    login_url = f"{panel_url.rstrip('/')}{base_path}/login"
    payload = {"username": username, "password": password}

    try:
        res = session.post(login_url, data=payload, timeout=10)
        data = res.json()
        if data.get("success"):
            return session
        else:
            print(f"❌ Login failed: {data.get('msg')}")
            return None
    except Exception as e:
        print(f"❌ Connection error during login: {e}")
        return None


def check_and_restore():
    config = load_config()
    if not config:
        return 30

    panel_url = config.get("panel_url", "")
    username = config.get("username", "")
    password = config.get("password", "")
    base_path = config.get("base_path", "")
    target_inbound = config.get("inbound", {})
    check_interval = int(config.get("check_interval", 60))

    target_port = target_inbound.get("port")
    if not target_port:
        print("❌ 'port' is missing in target inbound JSON.")
        return check_interval

    session = get_session(panel_url, username, password, base_path)
    if not session:
        return check_interval

    list_url = f"{panel_url.rstrip('/')}{base_path}/panel/api/inbounds/list"
    try:
        res = session.get(list_url, timeout=10)
        data = res.json()
        if not data.get("success"):
            print(f"❌ Failed to fetch inbounds list: {data.get('msg')}")
            return check_interval

        inbounds = data.get("obj", [])
        if inbounds is None:
            inbounds = []

        # بررسی وجود اینباند بر اساس پورت
        exists = any(item.get("port") == target_port for item in inbounds)

        if exists:
            print(f"✔ Inbound on port {target_port} is active.")
        else:
            print(
                f"⚠️ Inbound on port {target_port} is missing! Restoring..."
            )
            add_url = (
                f"{panel_url.rstrip('/')}{base_path}/panel/api/inbounds/add"
            )

            # ساخت Payload استاندارد برای API پنل 3x-ui
            payload = {
                "up": target_inbound.get("up", 0),
                "down": target_inbound.get("down", 0),
                "total": target_inbound.get("total", 0),
                "remark": target_inbound.get("remark", ""),
                "enable": target_inbound.get("enable", True),
                "expiryTime": target_inbound.get("expiryTime", 0),
                "listen": target_inbound.get("listen", ""),
                "port": target_port,
                "protocol": target_inbound.get("protocol", "vless"),
                "settings": json.dumps(target_inbound.get("settings", {}))
                if isinstance(target_inbound.get("settings"), dict)
                else target_inbound.get("settings"),
                "streamSettings": json.dumps(
                    target_inbound.get("streamSettings", {})
                )
                if isinstance(target_inbound.get("streamSettings"), dict)
                else target_inbound.get("streamSettings"),
                "sniffing": json.dumps(target_inbound.get("sniffing", {}))
                if isinstance(target_inbound.get("sniffing"), dict)
                else target_inbound.get("sniffing"),
            }

            add_res = session.post(add_url, data=payload, timeout=10)
            add_data = add_res.json()

            if add_data.get("success"):
                print(
                    f"✅ Inbound on port {target_port} successfully restored!"
                )
            else:
                print(f"❌ Failed to restore inbound: {add_data.get('msg')}")

    except Exception as e:
        print(f"❌ Error during execution: {e}")

    return check_interval


if __name__ == "__main__":
    print("🚀 Node Watcher Started Successfully!")
    sys.stdout.flush()
    while True:
        try:
            interval = check_and_restore()
            sys.stdout.flush()
            time.sleep(interval)
        except Exception as main_e:
            print(f"❌ Unexpected error in loop: {main_e}")
            sys.stdout.flush()
            time.sleep(10)
