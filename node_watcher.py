#!/usr/bin/env python3
"""
node_watcher.py – Configurable Auto-heal + Sync for Sanayi / 3X-UI
Only watches the inbounds defined in config.json
"""

import time
import json
import sqlite3
import subprocess
import logging
import os
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

# ---------- load config ----------
if not CONFIG_PATH.exists():
    print("❌ config.json not found. Run install.sh first.")
    sys.exit(1)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CFG = json.load(f)

DB_PATH = CFG.get("db_path", "/etc/x-ui/x-ui.db")
CHECK_INTERVAL = int(CFG.get("check_interval", 15))
LOG_FILE = CFG.get("log_file", "/var/log/node_watcher.log")
WATCHED = CFG.get("watched_inbounds", [])

if not WATCHED:
    print("❌ No inbounds defined in config.json")
    sys.exit(1)

# ---------- logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("node_watcher")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def stop_xui():
    try:
        subprocess.run(["systemctl", "stop", "x-ui"], check=False, timeout=20)
        time.sleep(1.5)
        log.info("x-ui stopped")
    except Exception as e:
        log.warning(f"stop x-ui failed: {e}")


def start_xui():
    try:
        subprocess.run(["systemctl", "start", "x-ui"], check=False, timeout=20)
        time.sleep(2)
        log.info("x-ui started")
    except Exception as e:
        log.warning(f"start x-ui failed: {e}")


def table_exists(cur, name: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def build_client_json(row: sqlite3.Row) -> dict:
    now_ms = int(time.time() * 1000)
    return {
        "id": row["uuid"] or "",
        "email": row["email"],
        "flow": row["flow"] or "",
        "limitIp": row["limit_ip"] or 0,
        "totalGB": row["total_gb"] or 0,
        "expiryTime": row["expiry_time"] or 0,
        "enable": bool(row["enable"]) if row["enable"] is not None else True,
        "tgId": row["tg_id"] or 0,
        "subId": row["sub_id"] or "",
        "reset": row["reset"] or 0,
        "comment": row["comment"] or "",
        "created_at": row["created_at"] or now_ms,
        "updated_at": row["updated_at"] or now_ms,
    }


def restore_inbound(cur, item: dict):
    """Create the inbound from the saved config + real clients from DB."""
    inbound_id = item["id"]
    emails = item.get("client_emails", [])

    clients_json = []
    client_ids = []

    if emails and table_exists(cur, "clients"):
        placeholders = ",".join("?" * len(emails))
        cur.execute(f"SELECT * FROM clients WHERE email IN ({placeholders})", emails)
        for row in cur.fetchall():
            clients_json.append(build_client_json(row))
            client_ids.append(row["id"])

    settings = {
        "clients": clients_json,
        "decryption": "none",
        "fallbacks": []
    }

    stream_settings = json.dumps(item.get("stream_settings", {
        "network": "tcp",
        "security": "none",
        "tcpSettings": {"header": {"type": "none"}, "acceptProxyProtocol": False}
    }), ensure_ascii=False)

    sniffing = json.dumps(item.get("sniffing", {
        "enabled": False,
        "destOverride": ["http", "tls", "quic"]
    }), ensure_ascii=False)

    tag = item.get("tag") or f"in-{inbound_id}-watched"
    remark = item.get("remark") or f"Watched_Inbound_{inbound_id}"
    port = item.get("port", 8443)
    protocol = item.get("protocol", "vless")
    listen = item.get("listen", "")

    cur.execute("""
        INSERT INTO inbounds
        (id, user_id, up, down, total, remark, enable, expiry_time,
         listen, port, protocol, settings, stream_settings, tag, sniffing)
        VALUES (?, 1, 0, 0, 0, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?)
    """, (
        inbound_id,
        remark,
        listen,
        port,
        protocol,
        json.dumps(settings, ensure_ascii=False),
        stream_settings,
        tag,
        sniffing
    ))

    # link clients
    if table_exists(cur, "client_inbounds") and client_ids:
        now_ms = int(time.time() * 1000)
        for cid in client_ids:
            cur.execute("""
                INSERT OR IGNORE INTO client_inbounds
                (client_id, inbound_id, flow_override, created_at)
                VALUES (?, ?, NULL, ?)
            """, (cid, inbound_id, now_ms))

    # make sure client_traffics points to this inbound
    for email in emails:
        cur.execute(
            "UPDATE client_traffics SET inbound_id = ? WHERE email = ?",
            (inbound_id, email)
        )

    log.info(f"✅ Restored inbound ID {inbound_id} ({remark}) with {len(clients_json)} clients")


def fix_links_and_settings(cur, item: dict):
    """Ensure client_inbounds links + settings JSON are correct for an existing inbound."""
    inbound_id = item["id"]
    emails = item.get("client_emails", [])
    if not emails:
        return False

    changed = False
    now_ms = int(time.time() * 1000)

    # 1. client_inbounds links
    if table_exists(cur, "clients") and table_exists(cur, "client_inbounds"):
        placeholders = ",".join("?" * len(emails))
        cur.execute(f"SELECT id, email FROM clients WHERE email IN ({placeholders})", emails)
        for row in cur.fetchall():
            cur.execute("""
                INSERT OR IGNORE INTO client_inbounds
                (client_id, inbound_id, flow_override, created_at)
                VALUES (?, ?, NULL, ?)
            """, (row["id"], inbound_id, now_ms))
            if cur.rowcount > 0:
                log.info(f"🔗 Linked {row['email']} → inbound {inbound_id}")
                changed = True

    # 2. rebuild settings JSON with real UUIDs
    if table_exists(cur, "clients"):
        placeholders = ",".join("?" * len(emails))
        cur.execute(f"SELECT * FROM clients WHERE email IN ({placeholders})", emails)
        real_clients = [build_client_json(r) for r in cur.fetchall()]

        cur.execute("SELECT settings FROM inbounds WHERE id = ?", (inbound_id,))
        row = cur.fetchone()
        if row:
            try:
                settings = json.loads(row["settings"] or "{}")
            except Exception:
                settings = {}
            settings["clients"] = real_clients
            settings.setdefault("decryption", "none")
            settings.setdefault("fallbacks", [])
            cur.execute(
                "UPDATE inbounds SET settings = ? WHERE id = ?",
                (json.dumps(settings, ensure_ascii=False), inbound_id)
            )
            changed = True
            log.info(f"🔄 Updated settings JSON for inbound {inbound_id}")

    # 3. client_traffics inbound_id
    for email in emails:
        cur.execute(
            "UPDATE client_traffics SET inbound_id = ? WHERE email = ? AND (inbound_id IS NULL OR inbound_id != ?)",
            (inbound_id, email, inbound_id)
        )
        if cur.rowcount > 0:
            changed = True

    return changed


def auto_heal_and_sync():
    modified = False
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        if not table_exists(cur, "inbounds") or not table_exists(cur, "client_traffics"):
            log.error("Required tables missing")
            return

        for item in WATCHED:
            inbound_id = item["id"]

            cur.execute("SELECT id FROM inbounds WHERE id = ?", (inbound_id,))
            exists = cur.fetchone() is not None

            if not exists:
                if not modified:
                    stop_xui()
                    conn.close()
                    conn = get_conn()
                    cur = conn.cursor()
                    modified = True
                restore_inbound(cur, item)
                conn.commit()
            else:
                if fix_links_and_settings(cur, item):
                    if not modified:
                        stop_xui()
                        conn.close()
                        conn = get_conn()
                        cur = conn.cursor()
                        modified = True
                        fix_links_and_settings(cur, item)
                    conn.commit()

    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if modified:
            start_xui()


if __name__ == "__main__":
    log.info(f"🚀 Node Watcher started – watching {len(WATCHED)} inbound(s)")
    for w in WATCHED:
        log.info(f"   • ID {w['id']}  port={w.get('port')}  emails={w.get('client_emails', [])}")
    while True:
        try:
            auto_heal_and_sync()
        except Exception as e:
            log.error(f"Unexpected: {e}", exc_info=True)
        time.sleep(CHECK_INTERVAL)
