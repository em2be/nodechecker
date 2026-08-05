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


def table_exists(cur, name):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def get_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {r["name"] for r in cur.fetchall()}


def ensure_client_in_db(cur, client_data):
    """
    Make sure client exists in `clients` table.
    Returns client_id (row id) or None.
    client_data comes from config (saved at install time from inbound JSON).
    """
    email = client_data.get("email")
    if not email:
        return None

    cur.execute("SELECT id FROM clients WHERE email = ?", (email,))
    row = cur.fetchone()
    if row:
        return row["id"]

    # client was deleted – recreate from saved data
    now_ms = int(time.time() * 1000)
    uuid_val = client_data.get("id") or client_data.get("uuid") or ""
    sub_id = client_data.get("subId") or client_data.get("sub_id") or ""
    enable = 1 if client_data.get("enable", True) else 0
    flow = client_data.get("flow") or ""
    limit_ip = client_data.get("limitIp") or client_data.get("limit_ip") or 0
    total_gb = client_data.get("totalGB") or client_data.get("total_gb") or 0
    expiry = client_data.get("expiryTime") or client_data.get("expiry_time") or 0
    tg_id = client_data.get("tgId") or client_data.get("tg_id") or 0
    comment = client_data.get("comment") or ""
    reset = client_data.get("reset") or 0
    password = client_data.get("password") or ""
    auth = client_data.get("auth") or ""
    security = client_data.get("security") or ""

    cols = get_columns(cur, "clients")
    fields = ["email", "uuid", "sub_id", "enable"]
    values = [email, uuid_val, sub_id, enable]

    optional = {
        "flow": flow,
        "limit_ip": limit_ip,
        "total_gb": total_gb,
        "expiry_time": expiry,
        "tg_id": tg_id,
        "comment": comment,
        "reset": reset,
        "password": password,
        "auth": auth,
        "security": security,
        "created_at": client_data.get("created_at") or now_ms,
        "updated_at": now_ms,
    }
    for k, v in optional.items():
        if k in cols:
            fields.append(k)
            values.append(v)

    placeholders = ",".join("?" * len(fields))
    cur.execute(
        f"INSERT INTO clients ({','.join(fields)}) VALUES ({placeholders})",
        values
    )
    client_id = cur.lastrowid
    log.info(f"➕ Recreated client {email} (id={client_id}) in clients table")
    return client_id


def ensure_client_traffic(cur, email, inbound_id, client_data):
    """Ensure a row exists in client_traffics for this email+inbound."""
    cur.execute(
        "SELECT id FROM client_traffics WHERE email = ?",
        (email,)
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE client_traffics SET inbound_id = ?, enable = 1 WHERE email = ?",
            (inbound_id, email)
        )
        return

    enable = 1 if client_data.get("enable", True) else 0
    expiry = client_data.get("expiryTime") or 0
    total = client_data.get("totalGB") or client_data.get("total") or 0

    cur.execute("""
        INSERT INTO client_traffics (inbound_id, enable, email, up, down, expiry_time, total, reset, last_online)
        VALUES (?, ?, ?, 0, 0, ?, ?, 0, 0)
    """, (inbound_id, enable, email, expiry, total))
    log.info(f"➕ Created client_traffics row for {email} → inbound {inbound_id}")


def build_settings_clients(cur, clients_data):
    """Build the clients array for inbounds.settings from DB (preferred) or saved data."""
    result = []
    now_ms = int(time.time() * 1000)
    for cd in clients_data:
        email = cd.get("email")
        if not email:
            continue
        cur.execute("SELECT * FROM clients WHERE email = ?", (email,))
        row = cur.fetchone()
        if row:
            result.append({
                "id": row["uuid"] or cd.get("id") or "",
                "email": row["email"],
                "flow": (row["flow"] if "flow" in row.keys() else None) or cd.get("flow") or "",
                "limitIp": (row["limit_ip"] if "limit_ip" in row.keys() else None) or cd.get("limitIp") or 0,
                "totalGB": (row["total_gb"] if "total_gb" in row.keys() else None) or cd.get("totalGB") or 0,
                "expiryTime": (row["expiry_time"] if "expiry_time" in row.keys() else None) or cd.get("expiryTime") or 0,
                "enable": bool(row["enable"]) if row["enable"] is not None else True,
                "tgId": (row["tg_id"] if "tg_id" in row.keys() else None) or cd.get("tgId") or 0,
                "subId": (row["sub_id"] if "sub_id" in row.keys() else None) or cd.get("subId") or "",
                "reset": (row["reset"] if "reset" in row.keys() else None) or cd.get("reset") or 0,
                "comment": (row["comment"] if "comment" in row.keys() else None) or cd.get("comment") or "",
                "created_at": (row["created_at"] if "created_at" in row.keys() else None) or cd.get("created_at") or now_ms,
                "updated_at": now_ms,
            })
        else:
            result.append({
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
            })
    return result


def restore_inbound(cur, item):
    inbound_id = item["id"]
    clients_data = item.get("clients") or []
    if not clients_data and item.get("client_emails"):
        clients_data = [{"email": e} for e in item["client_emails"]]

    client_ids = []
    for cd in clients_data:
        cid = ensure_client_in_db(cur, cd)
        if cid:
            client_ids.append(cid)
        email = cd.get("email")
        if email:
            ensure_client_traffic(cur, email, inbound_id, cd)

    settings_clients = build_settings_clients(cur, clients_data)
    settings = {
        "clients": settings_clients,
        "decryption": "none",
        "fallbacks": []
    }

    stream_settings = json.dumps(item.get("stream_settings", {
        "network": "tcp",
        "security": "none"
    }), ensure_ascii=False)

    sniffing = json.dumps(item.get("sniffing", {"enabled": False}), ensure_ascii=False)

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
        inbound_id, remark, listen, port, protocol,
        json.dumps(settings, ensure_ascii=False),
        stream_settings, tag, sniffing
    ))

    if table_exists(cur, "client_inbounds") and client_ids:
        now_ms = int(time.time() * 1000)
        for cid in client_ids:
            cur.execute("""
                INSERT OR IGNORE INTO client_inbounds
                (client_id, inbound_id, flow_override, created_at)
                VALUES (?, ?, NULL, ?)
            """, (cid, inbound_id, now_ms))

    log.info(f"✅ Restored inbound ID {inbound_id} ({remark}) with {len(settings_clients)} clients")


def sync_existing(cur, item):
    """
    For an existing inbound: ensure clients + links + settings are correct.
    Returns True only if something actually changed.
    """
    inbound_id = item["id"]
    clients_data = item.get("clients") or []
    if not clients_data and item.get("client_emails"):
        clients_data = [{"email": e} for e in item["client_emails"]]
    if not clients_data:
        return False

    changed = False
    now_ms = int(time.time() * 1000)

    client_ids = []
    for cd in clients_data:
        cid = ensure_client_in_db(cur, cd)
        if cid:
            client_ids.append(cid)
        email = cd.get("email")
        if email:
            cur.execute("SELECT inbound_id FROM client_traffics WHERE email = ?", (email,))
            tr = cur.fetchone()
            if not tr:
                ensure_client_traffic(cur, email, inbound_id, cd)
                changed = True
            elif tr["inbound_id"] != inbound_id:
                cur.execute(
                    "UPDATE client_traffics SET inbound_id = ? WHERE email = ?",
                    (inbound_id, email)
                )
                changed = True

    if table_exists(cur, "client_inbounds"):
        for cid in client_ids:
            cur.execute("""
                INSERT OR IGNORE INTO client_inbounds
                (client_id, inbound_id, flow_override, created_at)
                VALUES (?, ?, NULL, ?)
            """, (cid, inbound_id, now_ms))
            if cur.rowcount > 0:
                log.info(f"🔗 Linked client_id={cid} → inbound {inbound_id}")
                changed = True

    new_clients = build_settings_clients(cur, clients_data)
    new_settings = {
        "clients": new_clients,
        "decryption": "none",
        "fallbacks": []
    }
    new_settings_str = json.dumps(new_settings, ensure_ascii=False, sort_keys=True)

    cur.execute("SELECT settings FROM inbounds WHERE id = ?", (inbound_id,))
    row = cur.fetchone()
    if row:
        try:
            old = json.loads(row["settings"] or "{}")
            old_norm = json.dumps({
                "clients": old.get("clients", []),
                "decryption": old.get("decryption", "none"),
                "fallbacks": old.get("fallbacks", [])
            }, ensure_ascii=False, sort_keys=True)
        except Exception:
            old_norm = ""

        if old_norm != new_settings_str:
            cur.execute(
                "UPDATE inbounds SET settings = ? WHERE id = ?",
                (json.dumps(new_settings, ensure_ascii=False), inbound_id)
            )
            log.info(f"🔄 Updated settings JSON for inbound {inbound_id}")
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

        to_restore = []
        to_sync = []
        for item in WATCHED:
            inbound_id = item["id"]
            cur.execute("SELECT id FROM inbounds WHERE id = ?", (inbound_id,))
            if cur.fetchone() is None:
                to_restore.append(item)
            else:
                to_sync.append(item)

        if not to_restore and not to_sync:
            return

        would_change = bool(to_restore)
        if not would_change:
            for item in to_sync:
                clients_data = item.get("clients") or []
                if not clients_data and item.get("client_emails"):
                    clients_data = [{"email": e} for e in item["client_emails"]]
                for cd in clients_data:
                    email = cd.get("email")
                    if not email:
                        continue
                    cur.execute("SELECT id FROM clients WHERE email = ?", (email,))
                    if not cur.fetchone():
                        would_change = True
                        break
                    if table_exists(cur, "client_inbounds"):
                        cur.execute(
                            "SELECT 1 FROM client_inbounds ci "
                            "JOIN clients c ON c.id = ci.client_id "
                            "WHERE c.email = ? AND ci.inbound_id = ?",
                            (email, item["id"])
                        )
                        if not cur.fetchone():
                            would_change = True
                            break
                if would_change:
                    break

        if not would_change and not to_restore:
            for item in to_sync:
                clients_data = item.get("clients") or []
                if not clients_data and item.get("client_emails"):
                    clients_data = [{"email": e} for e in item["client_emails"]]
                new_clients = build_settings_clients(cur, clients_data)
                new_str = json.dumps(
                    {"clients": new_clients, "decryption": "none", "fallbacks": []},
                    ensure_ascii=False, sort_keys=True
                )
                cur.execute("SELECT settings FROM inbounds WHERE id = ?", (item["id"],))
                row = cur.fetchone()
                if row:
                    try:
                        old = json.loads(row["settings"] or "{}")
                        old_str = json.dumps({
                            "clients": old.get("clients", []),
                            "decryption": old.get("decryption", "none"),
                            "fallbacks": old.get("fallbacks", [])
                        }, ensure_ascii=False, sort_keys=True)
                        if old_str != new_str:
                            would_change = True
                            break
                    except Exception:
                        would_change = True
                        break

        if not would_change and not to_restore:
            return

        stop_xui()
        conn.close()
        conn = get_conn()
        cur = conn.cursor()
        modified = True

        for item in to_restore:
            cur.execute("SELECT id FROM inbounds WHERE id = ?", (item["id"],))
            if cur.fetchone() is None:
                restore_inbound(cur, item)

        for item in to_sync:
            sync_existing(cur, item)

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
        emails = w.get("client_emails") or [c.get("email") for c in w.get("clients", [])]
        log.info(f"   • ID {w['id']}  port={w.get('port')}  clients={emails}")
    while True:
        try:
            auto_heal_and_sync()
        except Exception as e:
            log.error(f"Unexpected: {e}", exc_info=True)
        time.sleep(CHECK_INTERVAL)
