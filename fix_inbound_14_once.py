#!/usr/bin/env python3
"""
یک‌بار اجرا کن تا وضعیت فعلی inbound 14 و کلاینت‌های USAob8443 / Nob8443 را فوری درست کند.
بعد از اجرای موفق می‌توانی این فایل را پاک کنی.
"""

import json
import sqlite3
import subprocess
import time

DB_PATH = "/etc/x-ui/x-ui.db"

def main():
    print("Stopping x-ui ...")
    subprocess.run(["systemctl", "stop", "x-ui"], check=False)
    time.sleep(2)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- 1. Ensure inbound 14 exists ---
    cur.execute("SELECT id FROM inbounds WHERE id = 14")
    if not cur.fetchone():
        print("Inbound 14 missing – creating ...")
        stream = json.dumps({
            "network": "tcp",
            "security": "none",
            "tcpSettings": {"header": {"type": "none"}, "acceptProxyProtocol": False}
        })
        sniff = json.dumps({"enabled": False, "destOverride": ["http", "tls", "quic"]})
        cur.execute("""
            INSERT INTO inbounds
            (id, user_id, up, down, total, remark, enable, expiry_time,
             listen, port, protocol, settings, stream_settings, tag, sniffing)
            VALUES (14, 1, 0, 0, 0, 'Restored_Inbound_14', 1, 0, '', 8443, 'vless',
                    '{"clients":[],"decryption":"none","fallbacks":[]}', ?, 'in-14-restored', ?)
        """, (stream, sniff))
        conn.commit()

    # --- 2. Get real client data ---
    cur.execute("SELECT * FROM clients WHERE email IN ('USAob8443', 'Nob8443')")
    clients = cur.fetchall()
    print(f"Found {len(clients)} clients in clients table")

    now_ms = int(time.time() * 1000)
    clients_json = []
    for c in clients:
        clients_json.append({
            "id": c["uuid"],
            "email": c["email"],
            "flow": c["flow"] or "",
            "limitIp": c["limit_ip"] or 0,
            "totalGB": c["total_gb"] or 0,
            "expiryTime": c["expiry_time"] or 0,
            "enable": bool(c["enable"]) if c["enable"] is not None else True,
            "tgId": c["tg_id"] or 0,
            "subId": c["sub_id"] or "",
            "reset": c["reset"] or 0,
            "comment": c["comment"] or "",
            "created_at": c["created_at"] or now_ms,
            "updated_at": c["updated_at"] or now_ms,
        })
        # link in client_inbounds
        cur.execute("""
            INSERT OR IGNORE INTO client_inbounds
            (client_id, inbound_id, flow_override, created_at)
            VALUES (?, 14, NULL, ?)
        """, (c["id"], now_ms))
        print(f"  Linked {c['email']} (client_id={c['id']}) → inbound 14")

    # --- 3. Make sure client_traffics has inbound_id = 14 ---
    for c in clients:
        cur.execute("""
            UPDATE client_traffics SET inbound_id = 14 WHERE email = ?
        """, (c["email"],))

    # --- 4. Update settings JSON with REAL UUIDs ---
    settings = {
        "clients": clients_json,
        "decryption": "none",
        "fallbacks": []
    }
    cur.execute(
        "UPDATE inbounds SET settings = ?, remark = 'Restored_Inbound_14', enable = 1 WHERE id = 14",
        (json.dumps(settings, ensure_ascii=False),)
    )

    conn.commit()
    conn.close()

    print("Starting x-ui ...")
    subprocess.run(["systemctl", "start", "x-ui"], check=False)
    time.sleep(2)
    print("✅ Done. Check panel → Inbounds & Clients pages.")

if __name__ == "__main__":
    main()
