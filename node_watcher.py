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

def sync_and_fix_clients(conn, inbound_id, clients):
    """ایجاد یا بروزرسانی سطر اختصاصی کلاینت در client_traffics به ازای این اینباند"""
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='client_traffics'")
    if not c.fetchone():
        return

    # دریافت لیست ستون‌های جدول جهت جلوگیری از خطای ساختار دیتابیس
    c.execute("PRAGMA table_info(client_traffics)")
    cols = [col[1] for col in c.fetchall()]

    for client in clients:
        email = client.get("email", "")
        uuid = client.get("id", "")
        sub_id = client.get("subId", "")
        expiry_time = client.get("expiryTime", 0)
        total_gb = client.get("totalGB", 0)
        enable = 1 if client.get("enable", True) else 0

        if not email and not uuid:
            continue

        # بررسی اختصاصی وجود کلاینت برای همین inbound_id خاص
        c.execute("""SELECT id FROM client_traffics 
                     WHERE inbound_id = ? AND (email = ? OR (uuid = ? AND uuid != ''))""", 
                  (inbound_id, email, uuid))
        row = c.fetchone()

        if row:
            # اگر سطر مربوط به این اینباند وجود دارد، بروزرسانی کن
            c.execute("""UPDATE client_traffics 
                         SET enable = ?, uuid = ?, sub_id = ?
                         WHERE id = ?""", (enable, uuid, sub_id, row[0]))
        else:
            # اگر سطر اختصاصی این اینباند وجود ندارد، یک سطر جدید درج کن
            fields = ["inbound_id", "enable", "email", "up", "down", "expiry_time", "total", "reset"]
            values = [inbound_id, enable, email, 0, 0, expiry_time, total_gb, 0]

            if "uuid" in cols:
                fields.append("uuid")
                values.append(uuid)
            if "sub_id" in cols:
                fields.append("sub_id")
                values.append(sub_id)

            placeholders = ", ".join(["?"] * len(fields))
            field_names = ", ".join(fields)
            
            c.execute(f"INSERT INTO client_traffics ({field_names}) VALUES ({placeholders})", values)

    # پاک‌سازی رکوردهای یتیم اینباندهای حذف‌شده
    c.execute("DELETE FROM client_traffics WHERE inbound_id NOT IN (SELECT id FROM inbounds)")

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
        conn.close()

        # ۱. اگر اینباند وجود ندارد (حذف شده است)
        if not row:
            print(f"⚠️ Inbound on port {target_port} missing from DB. Restoring...")
            
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

            # ساخت سطر جدید کلاینت متصل به ID جدید اینباند
            sync_and_fix_clients(conn, new_inbound_id, clients)

            conn.commit()
            conn.close()
            
            os.system("systemctl start x-ui")
            print(f"✅ Inbound & Client Row on port {target_port} successfully restored (ID: {new_inbound_id})!")

        else:
            # ۲. بررسی اینکه آیا سطر کلاینت برای ID فعلی اینباند ساخته شده یا خیر
            inbound_id = row[0]
            is_enabled = row[1]

            settings_dict = target.get("settings", {})
            clients = settings_dict.get("clients", []) if isinstance(settings_dict, dict) else []

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            missing_client_link = False
            for client in clients:
                email = client.get("email", "")
                c.execute("SELECT id FROM client_traffics WHERE inbound_id = ? AND email = ?", (inbound_id, email))
                if not c.fetchone():
                    missing_client_link = True
                    break

            if is_enabled == 0 or missing_client_link:
                conn.close()
                os.system("systemctl stop x-ui")
                time.sleep(1)

                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()

                c.execute("UPDATE inbounds SET enable = 1, expiry_time = 0 WHERE port = ?", (target_port,))
                sync_and_fix_clients(conn, inbound_id, clients)

                conn.commit()
                conn.close()
                
                os.system("systemctl start x-ui")
                print(f"✔ Attached missing client link to inbound ID {inbound_id}.")
            else:
                conn.close()

    except Exception as e:
        print(f"❌ Monitor DB Error: {e}")

    return check_interval

if __name__ == "__main__":
    print("🚀 Direct DB Node Watcher Running with Multi-Inbound Client Sync...")
    sys.stdout.flush()
    while True:
        try:
            interval = check_and_restore_db()
            sys.stdout.flush()
            time.sleep(interval)
        except Exception:
            time.sleep(5)
