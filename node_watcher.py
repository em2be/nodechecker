import json
import os
import sys
import time
import requests

CONFIG_FILE = "inbound_config.json"


class NodeInboundWatcher:

    def __init__(self, config_path):
        self.config_path = config_path
        self.config = self.load_config()
        self.session = requests.Session()

        self.panel_url = self.config.get(
            "panel_url", "http://127.0.0.1:2053"
        ).rstrip("/")
        self.username = self.config.get("username", "admin")
        self.password = self.config.get("password")
        self.base_path = self.config.get("base_path", "")
        self.base_api_url = f"{self.panel_url}{self.base_path}"

        self.inbound_data = self.config.get("inbound", {})
        self.target_port = self.inbound_data.get("port")
        self.target_clients = self.inbound_data.get("settings", {}).get(
            "clients", []
        )

    def load_config(self):
        if not os.path.exists(self.config_path):
            print(f"❌ Error: Config file '{self.config_path}' not found!")
            sys.exit(1)
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Error reading JSON config: {e}")
            sys.exit(1)

    def login(self):
        login_url = f"{self.base_api_url}/login"
        payload = {"username": self.username, "password": self.password}
        try:
            res = self.session.post(login_url, data=payload, timeout=10)
            data = res.json()
            return data.get("success", False)
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False

    def get_inbounds(self):
        url = f"{self.base_api_url}/panel/api/inbounds/list"
        try:
            res = self.session.get(url, timeout=10)
            data = res.json()
            if data.get("success"):
                return data.get("obj", [])
        except Exception as e:
            print(f"❌ Error fetching inbounds: {e}")
        return []

    def create_inbound(self):
        url = f"{self.base_api_url}/panel/api/inbounds/add"
        payload = {
            "remark": self.inbound_data.get("remark", "Auto-Created-Inbound"),
            "port": self.target_port,
            "protocol": self.inbound_data.get("protocol", "vless"),
            "enable": True,
            "settings": json.dumps(self.inbound_data.get("settings", {})),
            "streamSettings": json.dumps(
                self.inbound_data.get("streamSettings", {})
            ),
            "sniffing": json.dumps(self.inbound_data.get("sniffing", {})),
        }
        try:
            res = self.session.post(url, json=payload, timeout=10)
            data = res.json()
            if data.get("success"):
                print(f"✅ Inbound on port {self.target_port} created.")
                return True
        except Exception as e:
            print(f"❌ Error creating inbound: {e}")
        return False

    def add_client(self, inbound_id, client_info):
        url = f"{self.base_api_url}/panel/api/inbounds/addClient"
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_info]}),
        }
        try:
            res = self.session.post(url, json=payload, timeout=10)
            data = res.json()
            if data.get("success"):
                print(
                    f"✅ Client '{client_info.get('email')}' attached to Inbound {inbound_id}."
                )
                return True
        except Exception as e:
            print(f"❌ Error attaching client: {e}")
        return False

    def check_and_sync(self):
        print(
            f"🔍 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Checking inbound on port {self.target_port}..."
        )

        if not self.login():
            print("❌ Panel login failed.")
            return

        inbounds = self.get_inbounds()
        target_inbound = next(
            (ib for ib in inbounds if ib.get("port") == self.target_port), None
        )

        if not target_inbound:
            print(
                f"⚠️ Inbound port {self.target_port} missing! Re-creating..."
            )
            if self.create_inbound():
                inbounds = self.get_inbounds()
                target_inbound = next(
                    (
                        ib
                        for ib in inbounds
                        if ib.get("port") == self.target_port
                    ),
                    None,
                )

        if target_inbound:
            inbound_id = target_inbound["id"]
            current_settings = json.loads(target_inbound.get("settings", "{}"))
            existing_clients = current_settings.get("clients", [])
            existing_emails = [c.get("email") for c in existing_clients]

            for target_client in self.target_clients:
                email = target_client.get("email")
                if email not in existing_emails:
                    print(
                        f"⚠️ Client '{email}' missing on Inbound {inbound_id}. Attaching..."
                    )
                    self.add_client(inbound_id, target_client)
                else:
                    print(
                        f"ℹ️ Inbound {self.target_port} & Client '{email}' are healthy."
                    )


def main():
    watcher = NodeInboundWatcher(CONFIG_FILE)
    watcher.check_and_sync()

    while True:
        try:
            time.sleep(60)
            watcher.check_and_sync()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()