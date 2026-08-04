import json
import os
import time
import requests

CONFIG_FILE = "inbound_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Configuration file '{CONFIG_FILE}' not found.")
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

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
        return

    panel_url = config.get("panel_url")
    username = config.get("username")
    password = config.get("password")
    base_path = config.get("base_path", "")
    target_inbound = config.get("inbound", {})

    target_port = target_inbound.get("port")
    if not target_port:
        print("❌ 'port' is missing in target inbound JSON.")
        return

    session = get_session(panel_url, username, password, base_path)
    if not session:
        return

    list_url = f"{panel_url.rstrip('/')}{base_path}/panel/api/inbounds/list"
    try:
        res = session.get(list_url, timeout=10)
        data = res.json()
        if not data.get("success"):
            print(f"❌ Failed to fetch inbounds list: {data.get('msg')}")
            return

        inbounds = data.get("obj", [])
        
        # بررسی وجود اینباند بر اساس پورت
        exists = any(item.get("port") == target_port for item in inbounds)

        if exists:
            print(f"✔ Inbound on port {target_port} is active.")
        else:
            print(f"⚠️ Inbound on port {target_port} is missing! Restoring full inbound structure...")
            add_url = f"{panel_url.rstrip('/')}{base_path}/panel/api/inbounds/add"
            
            # ارسال ساختار کامل JSON به‌صورت payload
            add_res = session.post(add_url, json=target_inbound, timeout=10)
            add_data = add_res.json()

            if add_data.get("success"):
                print(f"✅ Inbound on port {target_port} successfully restored!")
            else:
                print(f"❌ Failed to restore inbound: {add_data.get('msg')}")

    except Exception as e:
        print(f"❌ Error during execution: {e}")

if __name__ == "__main__":
    while True:
        check_and_restore()
        time.sleep(60)
