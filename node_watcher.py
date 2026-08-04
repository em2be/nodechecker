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
    """اصلاح قطعی پیوند کلاینت‌ها با اینباند جدید بر اساس Email و UUID"""
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='client_traffics'")
    if not c.fetchone():
        return

    for client in clients:
        email = client.get("email", "")
        uuid = client.get("id", "")

        if not email:
            continue

        # ۱. ابتدا بررسی وجود کلاینت با Email یا UUID
        c.execute("SELECT id FROM client_traffics WHERE email = ? OR uuid = ?", (email, uuid))
        row = c.fetchone()

        if row:
            # انتقال کلاینت موجود به ID اینباند جدید
            c.execute("""UPDATE client_traffics 
                         SET inbound_id = ?, enable = 1, uuid = ?
                         WHERE email = ? OR uuid = ?""", (inbound_id, uuid, email, uuid))
        else:
            # درج کلاینت جدید اگر اصلاً در جدول نبود
            sub_id = client.get("subId", "")
            c.execute("""INSERT INTO client_traffics 
                         (inbound_id, enable, email, up, down, expiry_time, total, reset, uuid, sub_id) 
                         VALUES (?, 1, ?, 0, 0, 0, 0, 0, ?, ?)""", (inbound_id, email, uuid, sub_id))

    # ۲. پاک‌سازی رکوردهای یتیم (ارتباط‌های قدیمی که اینباندشان حذف شده)
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

        # حالت اول: اینباند کلاً وجود ندارد (نیاز به بازسازی)
        if not row:
            print(f"⚠️ Inbound on port {target_port} missing from DB. Restoring...")
            
            # متوقف کردن x-ui برای خالی کردن کش RAM
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

            # همگام‌سازی و انتقال کلاینت به ID جدید
            sync_and_fix_clients(conn, new_inbound_id, clients)

            conn.commit()
            conn.close()
            
            os.system("systemctl start x-ui")
            print(f"✅ Inbound & Clients on port {target_port} successfully restored (ID: {new_inbound_id})!")

        else:
            # حالت دوم: اینباند وجود دارد اما بررسی هماهنگی ID کلاینت‌ها لازم است
            inbound_id = row[0]
            is_enabled = row[1]

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            # بررسی آیا کلاینت متصل به ID قدیمی است یا نه
            settings_dict = target.get("settings", {})
            clients = settings_dict.get("clients", []) if isinstance(settings_dict, dict) else []
            
            needs_update = False
            for client in clients:
                email = client.get("email", "")
                c.execute("SELECT inbound_id FROM client_traffics WHERE email = ?", (email,))
                tr_row = c.fetchone()
                if tr_row and tr_row[0] != inbound_id:
                    needs_update = True
                    break

            if is_enabled == 0 or needs_update:
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
                print(f"✔ Fixed client-inbound mapping and enabled port {target_port}.")
            else:
                conn.close()

    except Exception as e:
        print(f"❌ Monitor DB Error: {e}")

    return check_interval

if __name__ == "__main__":
    print("🚀 Direct DB Node Watcher Running with Relational Fix...")
    sys.stdout.flush()
    while True:
        try:
            interval = check_and_restore_db()
            sys.stdout.flush()
            time.sleep(interval)
        except Exception:
            time.sleep(5)
