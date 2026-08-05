#!/usr/bin/env python3
"""
node_watcher.py – Auto-heal for Sanayi / 3X-UI
Keeps: inbound, clients, client_traffics, client_inbounds, settings.clients JSON
Only writes when something is missing (no infinite loop).
"""

import time
import json
import sqlite3
import subprocess
import logging
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger("node_watcher")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def stop_xui():
    subprocess.run(["systemctl", "stop", "x-ui"], check=False, timeout=20)
    time.sleep(1.5)
    log.info("x-ui stopped")


def start_xui():
    subprocess.run(["systemctl", "start", "x-ui"], check=False, timeout=20)
    time.sleep(2)
    log.info("x-ui started")


def table_exists(cur, name):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def get_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {r["name"] for r in cur.fetchall()}


def clients_data_of(item):
    data = item.get("clients") or []
    if not data and item.get("client_emails"):
        data = [{"email": e} for e in item["client_emails"]]
    return data


def ensure_client(cur, cd):
    email = cd.get("email")
    if not email:
        return None
    cur.execute("SELECT id FROM clients WHERE email = ?", (email,))
    row = cur.fetchone()
    if row:
        return row["id"]

    now_ms = int(time.time() * 1000)
    uuid_val = cd.get("id") or cd.get("uuid") or ""
    sub_id = cd.get("subId") or cd.get("sub_id") or ""
    enable = 1 if cd.get("enable", True) else 0

    cols = get_columns(cur, "clients")
    fields = ["email", "uuid", "sub_id", "enable"]
    values = [email, uuid_val, sub_id, enable]
    optional = {
        "flow": cd.get("flow") or "",
        "limit_ip": cd.get("limitIp") or 0,
        "total_gb": cd.get("totalGB") or 0,
        "expiry_time": cd.get("expiryTime") or 0,
        "tg_id": cd.get("tgId") or 0,
        "comment": cd.get("comment") or "",
        "reset": cd.get("reset") or 0,
        "password": cd.get("password") or "",
        "auth": cd.get("auth") or "",
        "security": cd.get("security") or "",
        "created_at": cd.get("created_at") or now_ms,
        "updated_at": now_ms,
    }
    for k, v in optional.items():
        if k in cols:
            fields.append(k)
            values.append(v)

    cur.execute(
        f"INSERT INTO clients ({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
        values
    )
    log.info(f"➕ Recreated client {email} (id={cur.lastrowid})")
    return cur.lastrowid


def ensure_traffic(cur, email, inbound_id, cd):
    cur.execute("SELECT id, inbound_id FROM client_traffics WHERE email = ?", (email,))
    row = cur.fetchone()
    if row:
        if row["inbound_id"] != inbound_id:
            cur.execute(
                "UPDATE client_traffics SET inbound_id = ?, enable = 1 WHERE email = ?",
                (inbound_id, email)
            )
            return True
        return False
    cur.execute("""
        INSERT INTO client_traffics
        (inbound_id, enable, email, up, down, expiry_time, total, reset, last_online)
        VALUES (?, 1, ?, 0, 0, ?, ?, 0, 0)
    """, (inbound_id, email, cd.get("expiryTime") or 0, cd.get("totalGB") or 0))
    log.info(f"➕ Created traffic for {email} → inbound {inbound_id}")
    return True


def ensure_link(cur, client_id, inbound_id):
    if not table_exists(cur, "client_inbounds"):
        return False
    cur.execute(
        "SELECT 1 FROM client_inbounds WHERE client_id = ? AND inbound_id = ?",
        (client_id, inbound_id)
    )
    if cur.fetchone():
        return False
    now_ms = int(time.time() * 1000)
    cur.execute("""
        INSERT OR IGNORE INTO client_inbounds
        (client_id, inbound_id, flow_override, created_at)
        VALUES (?, ?, NULL, ?)
    """, (client_id, inbound_id, now_ms))
    log.info(f"🔗 Linked client_id={client_id} → inbound {inbound_id}")
    return True


def client_obj_from_db_or_config(cur, cd):
    now_ms = int(time.time() * 1000)
    email = cd.get("email") or ""
    cur.execute("SELECT * FROM clients WHERE email = ?", (email,))
    row = cur.fetchone()
    if row:
        keys = row.keys()
        return {
            "id": row["uuid"] or cd.get("id") or "",
            "email": email,
            "flow": (row["flow"] if "flow" in keys and row["flow"] else None) or cd.get("flow") or "",
            "limitIp": (row["limit_ip"] if "limit_ip" in keys and row["limit_ip"] is not None else None) or cd.get("limitIp") or 0,
            "totalGB": (row["total_gb"] if "total_gb" in keys and row["total_gb"] is not None else None) or cd.get("totalGB") or 0,
            "expiryTime": (row["expiry_time"] if "expiry_time" in keys and row["expiry_time"] is not None else None) or cd.get("expiryTime") or 0,
            "enable": bool(row["enable"]) if row["enable"] is not None else True,
            "tgId": (row["tg_id"] if "tg_id" in keys and row["tg_id"] is not None else None) or cd.get("tgId") or 0,
            "subId": (row["sub_id"] if "sub_id" in keys and row["sub_id"] else None) or cd.get("subId") or "",
            "reset": (row["reset"] if "reset" in keys and row["reset"] is not None else None) or cd.get("reset") or 0,
            "comment": (row["comment"] if "comment" in keys and row["comment"] else None) or cd.get("comment") or "",
            "created_at": (row["created_at"] if "created_at" in keys and row["created_at"] else None) or cd.get("created_at") or now_ms,
            "updated_at": now_ms,
        }
    return {
        "id": cd.get("id") or cd.get("uuid") or "",
        "email": email,
        "flow": cd.get("flow") or "",
        "limitIp": cd.get("limitIp") or 0,
        "totalGB": cd.get("totalGB") or 0,
        "expiryTime": cd.get("expiryTime") or 0,
        "enable": cd.get("enable", True),
        "tgId": cd.get("tgId") or 0,
        "subId": cd.get("subId") or "",
        "reset": cd.get("reset") or 0,
        "comment": cd.get("comment") or "",
        "created_at": cd.get("created_at") or now_ms,
        "updated_at": now_ms,
    }


def ensure_settings_clients(cur, inbound_id, clients_data):
    """Add missing watched emails into settings.clients; do not remove others."""
    cur.execute("SELECT settings FROM inbounds WHERE id = ?", (inbound_id,))
    row = cur.fetchone()
    if not row:
        return False
    try:
        settings = json.loads(row["settings"] or "{}")
    except Exception:
        settings = {}
    existing = settings.get("clients") or []
    by_email = {c.get("email"): c for c in existing if c.get("email")}
    changed = False
    for cd in clients_data:
        email = cd.get("email")
        if not email:
            continue
        if email not in by_email:
            by_email[email] = client_obj_from_db_or_config(cur, cd)
            changed = True
            log.info(f"📝 Added {email} into settings JSON of inbound {inbound_id}")
    if not changed:
        return False
    settings["clients"] = list(by_email.values())
    settings.setdefault("decryption", "none")
    settings.setdefault("fallbacks", [])
    cur.execute(
        "UPDATE inbounds SET settings = ? WHERE id = ?",
        (json.dumps(settings, ensure_ascii=False), inbound_id)
    )
    return True


def settings_missing_emails(cur, inbound_id, clients_data):
    cur.execute("SELECT settings FROM inbounds WHERE id = ?", (inbound_id,))
    row = cur.fetchone()
    if not row:
        return True
    try:
        settings = json.loads(row["settings"] or "{}")
    except Exception:
        return True
    emails_in_json = {c.get("email") for c in (settings.get("clients") or []) if c.get("email")}
    for cd in clients_data:
        email = cd.get("email")
        if email and email not in emails_in_json:
            return True
    return False


def restore_inbound(cur, item):
    inbound_id = item["id"]
    clients_data = clients_data_of(item)
    client_ids = []
    for cd in clients_data:
        cid = ensure_client(cur, cd)
        if cid:
            client_ids.append(cid)
        email = cd.get("email")
        if email:
            ensure_traffic(cur, email, inbound_id, cd)

    settings = {
        "clients": [client_obj_from_db_or_config(cur, cd) for cd in clients_data],
        "decryption": "none",
        "fallbacks": []
    }
    stream_settings = json.dumps(
        item.get("stream_settings") or {"network": "tcp", "security": "none"},
        ensure_ascii=False
    )
    sniffing = json.dumps(item.get("sniffing") or {"enabled": False}, ensure_ascii=False)

    cur.execute("""
        INSERT INTO inbounds
        (id, user_id, up, down, total, remark, enable, expiry_time,
         listen, port, protocol, settings, stream_settings, tag, sniffing)
        VALUES (?, 1, 0, 0, 0, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?)
    """, (
        inbound_id,
        item.get("remark") or f"Watched_{inbound_id}",
        item.get("listen") or "",
        item.get("port") or 8443,
        item.get("protocol") or "vless",
        json.dumps(settings, ensure_ascii=False),
        stream_settings,
        item.get("tag") or f"in-{inbound_id}-watched",
        sniffing
    ))
    for cid in client_ids:
        ensure_link(cur, cid, inbound_id)
    log.info(f"✅ Restored inbound ID {inbound_id} with {len(clients_data)} clients")


def needs_work(cur, item):
    inbound_id = item["id"]
    clients_data = clients_data_of(item)
    cur.execute("SELECT id FROM inbounds WHERE id = ?", (inbound_id,))
    if cur.fetchone() is None:
        return True
    if settings_missing_emails(cur, inbound_id, clients_data):
        return True
    for cd in clients_data:
        email = cd.get("email")
        if not email:
            continue
        cur.execute("SELECT id FROM clients WHERE email = ?", (email,))
        row = cur.fetchone()
        if not row:
            return True
        if table_exists(cur, "client_inbounds"):
            cur.execute(
                "SELECT 1 FROM client_inbounds WHERE client_id = ? AND inbound_id = ?",
                (row["id"], inbound_id)
            )
            if not cur.fetchone():
                return True
        cur.execute("SELECT inbound_id FROM client_traffics WHERE email = ?", (email,))
        tr = cur.fetchone()
        if not tr or tr["inbound_id"] != inbound_id:
            return True
    return False


def do_sync(cur, item):
    inbound_id = item["id"]
    clients_data = clients_data_of(item)
    for cd in clients_data:
        cid = ensure_client(cur, cd)
        email = cd.get("email")
        if email:
            ensure_traffic(cur, email, inbound_id, cd)
        if cid:
            ensure_link(cur, cid, inbound_id)
    ensure_settings_clients(cur, inbound_id, clients_data)


def auto_heal_and_sync():
    modified = False
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        if not table_exists(cur, "inbounds") or not table_exists(cur, "client_traffics"):
            log.error("Required tables missing")
            return
        work_items = [item for item in WATCHED if needs_work(cur, item)]
        if not work_items:
            return
        stop_xui()
        conn.close()
        conn = get_conn()
        cur = conn.cursor()
        modified = True
        for item in work_items:
            cur.execute("SELECT id FROM inbounds WHERE id = ?", (item["id"],))
            if cur.fetchone() is None:
                restore_inbound(cur, item)
            else:
                do_sync(cur, item)
        conn.commit()
    except Exception as e:
        log.error(f"Error: {e}", exp_info=True)
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
        emails = w.get("client_emails") or [c.get("email") for c in w.get("clients", [])]
        log.info(f"   • ID {w['id']}  port={w.get('port')}  clients={emails}")
    while True:
        try:
            auto_heal_and_sync()
        except Exception as e:
            log.error(f"Unexpected: {e}", exc_info=True)
        time.sleep(CHECK_INTERVAL)
