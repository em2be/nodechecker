import json
import os
import sys
import time
import sqlite3

def get_db_path():
    paths = ['/etc/x-ui/x-ui.db', '/usr/local/x-ui/db/x-ui.db']
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]

DB_PATH = get_db_path()
CONFIG_FILE = "/opt/node-watcher/inbound_config.json"

def sync_clients_to_traffics(conn, inbound_id, clients):
    """همگام‌سازی کلاینت‌ها با جدول client_traffics جهت نمایش درست در صفحه Clients"""
    c = conn.cursor()
    # بررسی وجود جدول client_traffics در ۳x-ui
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='client_traffics'")
    if not c.fetchone():
        return

    for client in clients:
        email = client.get("email", "")
        if not email:
            continue
        
        # بررسی وجود کلاینت در جدول
        c.execute("SELECT id FROM client_traffics WHERE email = ?", (email,))
        row = c.fetchone()
        
        if row:
            # بروزرسانی inbound_id کلاینت موجود
            c.execute("""UPDATE client_traffics 
                         SET inbound_id = ?, enable = 1 
                         WHERE email = ?""", (inbound_id, email))
        else:
            # ایجاد رکورد جدید در صورت عدم وجود
            c.execute("""INSERT INTO client_traffics 
                         (inbound_id, enable, email, up, down, expiry_time, total, reset) 
                         VALUES (?, 1, ?, 0, 0, 0, 0, 0)""", (inbound_id, email))

def check_and_restore_db():
    if not os.path.exists(DB_PATH) or not os.path.exists(CONFIG_FILE):
        return 5

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ Error reading config: {e}")
        return 5

    target = config.get("inbound", {})
    check_interval = int(config.get("check_interval", 5))
    target_port = target.get("port", 8443)

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        row = c.execute("SELECT id, enable FROM inbounds WHERE port = ?", (target_port,)).fetchone()

        if not row:
            print(f"⚠️ Inbound on port {target_port} missing from DB. Restoring...")
            conn.close()
            os.system("systemctl stop x-ui")
            time.sleep(1)

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            settings_dict = target.get("settings", {})
            clients = settings_dict.get("clients", []) if isinstance(settings_dict, dict) else []

            s_str = json.dumps(settings_dict)
            st_str = json.dumps(target.get("streamSettings", {}))
            sn_str = json.dumps(target.get("sniffing", {}))

            c.execute("PRAGMA table_info(inbounds)")
            cols = [col[1] for col in c.fetchall()]

            if "tag" in cols:
                c.execute("""INSERT INTO inbounds (user_id, up, down, total, remark, enable, expiry_time, listen, port, protocol, settings, stream_settings, tag, sniffing)
                             VALUES (1, 0, 0, 0, ?, 1, 0, '', ?, ?, ?, ?, ?, ?)""",
                          (target.get("remark", "Node-Outbound"), target_port, target.get("protocol", "vless"), s_str, st_str, f"inbound-{target_port}", sn_str))
            else:
                c.execute("""INSERT INTO inbounds (user_id, up, down, total, remark, enable, expiry_time, listen, port, protocol, settings, stream_settings, sniffing)
                             VALUES (1, 0, 0, 0, ?, 1, 0, '', ?, ?, ?, ?, ?)""",
                          (target.get("remark", "Node-Outbound"), target_port, target.get("protocol", "vless"), s_str, st_str, sn_str))

            new_inbound_id = c.lastrowid

            # همگام‌سازی جدول client_traffics با ID جدید اینباند
            sync_clients_to_traffics(conn, new_inbound_id, clients)

            conn.commit()
            conn.close()
            os.system("systemctl start x-ui")
            print(f"✅ Inbound & Clients on port {target_port} successfully restored into DB!")

        elif row[1] == 0:
            inbound_id = row[0]
            settings_dict = target.get("settings", {})
            clients = settings_dict.get("clients", []) if isinstance(settings_dict, dict) else []

            c.execute("UPDATE inbounds SET enable = 1, expiry_time = 0 WHERE port = ?", (target_port,))
            
            # همگام‌سازی جدول client_traffics
            sync_clients_to_traffics(conn, inbound_id, clients)

            conn.commit()
            conn.close()
            print(f"✔ Re-enabled inbound & synced clients on port {target_port}.")
            os.system("systemctl restart x-ui")
        else:
            # همگام‌سازی دوره ای جهت اطمینان از اتصال کلاینت‌ها
            inbound_id = row[0]
            settings_dict = target.get("settings", {})
            clients = settings_dict.get("clients", []) if isinstance(settings_dict, dict) else []
            sync_clients_to_traffics(conn, inbound_id, clients)
            conn.commit()
            conn.close()

    except Exception as e:
        print(f"❌ Monitor DB Error: {e}")

    return check_interval

if __name__ == "__main__":
    print("🚀 Direct DB Node Watcher Running with Client Sync...")
    sys.stdout.flush()
    while True:
        try:
            interval = check_and_restore_db()
            sys.stdout.flush()
            time.sleep(interval)
        except Exception:
            time.sleep(5)
