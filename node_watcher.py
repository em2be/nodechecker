import json
import os
import sys
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    session.verify = False

    url_base = panel_url.rstrip("/")
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path
    base_path = base_path.rstrip("/")

    full_base = f"{url_base}{base_path}"
    login_url = f"{full_base}/login"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": full_base,
        "Referer": f"{login_url}",
    }

    payload = {"username": username, "password": password}

    try:
        # تست روش ۱: Form Data (استاندارد اصلی 3x-ui)
        res = session.post(
            login_url, data=payload, headers=headers, timeout=10
        )

        # اگر با Form Data خطای 403 داد، روش JSON امتحان می‌شود
        if res.status_code == 403:
            res = session.post(
                login_url, json=payload, headers=headers, timeout=10
            )

        if res.status_code != 200:
            print(
                f"❌ Login failed with HTTP Status Code: {res.status_code} on {login_url}"
            )
            return None

        try:
            data = res.json()
            if data.get("success"):
                return session
            else:
                print(f"❌ Login failed: {data.get('msg')}")
                return None
        except Exception:
            # اگر خروجی JSON نبود ولی کوکی ست شد
            if "session" in session.cookies or "x-ui" in session.cookies:
                return session
            print("❌ Invalid response format from panel during login.")
            return None

    except Exception as e:
        print(f"❌ Connection error during login: {e}")
        return None


def check_and_restore():
    config = load_config()
    if not config:
        return 5

    panel_url = config.get("panel_url", "")
    username = config.get("username", "")
    password = config.get("password", "")
    base_path = config.get("base_path", "")
    target_inbound = config.get("inbound", {})

    check_interval = int(config.get("check_interval", 5))

    target_port = target_inbound.get("port")
    if not target_port:
        print("❌ 'port' is missing in target inbound JSON.")
        return check_interval

    session = get_session(panel_url, username, password, base_path)
    if not session:
        return check_interval

    url_base = panel_url.rstrip("/")
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path
    base_path = base_path.rstrip("/")

    full_base = f"{url_base}{base_path}"
    list_url = f"{full_base}/panel/api/inbounds/list"

    try:
        res = session.get(list_url, timeout=10)
        if res.status_code != 200:
            print(f"❌ Fetch list failed with status: {res.status_code}")
            return check_interval

        data = res.json()
        if not data.get("success"):
            print(f"❌ Failed to fetch inbounds list: {data.get('msg')}")
            return check_interval

        inbounds = data.get("obj", [])
        if inbounds is None:
            inbounds = []

        exists = any(item.get("port") == target_port for item in inbounds)

        if exists:
            print(f"✔ Inbound on port {target_port} is active.")
        else:
            print(
                f"⚠️ Inbound on port {target_port} is missing! Restoring..."
            )
            add_url = f"{full_base}/panel/api/inbounds/add"

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

            headers = {"Accept": "application/json"}
            add_res = session.post(
                add_url, data=payload, headers=headers, timeout=10
            )
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
            time.sleep(5)
