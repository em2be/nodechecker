#!/usr/bin/env python3
"""
node_watcher.py  –  Auto-heal + Sync for Sanayi / 3X-UI panel
Compatible with the multi-table schema:
  clients  +  client_inbounds  +  client_traffics  +  inbounds
"""

import time
import json
import sqlite3
import subprocess
import logging
from datetime import datetime

DB_PATH = "/etc/x-ui/x-ui.db"
CHECK_INTERVAL = 15          # seconds
LOG_FILE = "/var/log/node_watcher.log"

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
        log.info("x-ui service stopped")
    except Exception as e:
        log.warning(f"Failed to stop x-ui: {e}")


def start_xui():
    try:
        subprocess.run(["systemctl", "start", "x-ui"], check=False, timeout=20)
        time.sleep(2)
        log.info("x-ui service started")
    except Exception as e:
        log.warning(f"Failed to start x-ui: {e}")


def table_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cursor.fetchone() is not None


def get_columns(cursor, table: str) -> set:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cursor.fetchall()}


def build_client_json(client_row: sqlite3.Row) -> dict:
    """Build the client object that goes inside inbounds.settings JSON."""
    now_ms = int(time.time() * 1000)
    return {
        "id": client_row["uuid"] or "",
        "email": client_row["email"],
        "flow": client_row["flow"] or "",
        "limitIp": client_row["limit_ip"] or 0,
        "totalGB": client_row["total_gb"] or 0,
        "expiryTime": client_row["expiry_time"] or 0,
        "enable": bool(client_row["enable"]) if client_row["enable"] is not None else True,
        "tgId": client_row["tg_id"] or 0,
        "subId": client_row["sub_id"] or "",
        "reset": client_row["reset"] or 0,
        "comment": client_row["comment"] or "",
        "created_at": client_row["created_at"] or now_ms,
        "updated_at": client_row["updated_at"] or now_ms,
    }


def auto_heal_and_sync():
    modified = False
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        # ---- safety checks ----
        if not table_exists(cur, "inbounds") or not table_exists(cur, "client_traffics"):
            log.error("Required tables missing – abort")
            return

        has_clients_table = table_exists(cur, "clients")
        has_client_inbounds = table_exists(cur, "client_inbounds")
        ct_cols = get_columns(cur, "client_traffics")
        clients_cols = get_columns(cur, "clients") if has_clients_table else set()

        # ============================================================
        # 1. Find orphaned inbound_ids (exist in client_traffics but not in inbounds)
        # ============================================================
        cur.execute("""
            SELECT DISTINCT inbound_id
            FROM client_traffics
            WHERE inbound_id IS NOT NULL
              AND inbound_id NOT IN (SELECT id FROM inbounds)
        """)
        orphans = [row["inbound_id"] for row in cur.fetchall()]

        if orphans:
            stop_xui()
            # re-open connection after stop
            conn.close()
            conn = get_conn()
            cur = conn.cursor()
            modified = True

            for missing_id in orphans:
                log.info(f"Orphaned inbound_id detected → {missing_id}")

                # Collect all client emails that belong to this inbound_id
                cur.execute(
                    "SELECT email FROM client_traffics WHERE inbound_id = ?",
                    (missing_id,)
                )
                emails = [r["email"] for r in cur.fetchall() if r["email"]]

                clients_json = []
                client_ids_to_link = []   # list of (client_id, inbound_id)

                if has_clients_table and emails:
                    placeholders = ",".join("?" * len(emails))
                    cur.execute(
                        f"SELECT * FROM clients WHERE email IN ({placeholders})",
                        emails
                    )
                    for crow in cur.fetchall():
                        clients_json.append(build_client_json(crow))
                        client_ids_to_link.append(crow["id"])
                else:
                    # fallback – create minimal entries (should rarely happen)
                    for email in emails:
                        import uuid as uuid_mod
                        clients_json.append({
                            "id": str(uuid_mod.uuid4()),
                            "email": email,
                            "flow": "",
                            "limitIp": 0,
                            "totalGB": 0,
                            "expiryTime": 0,
                            "enable": True,
                            "tgId": 0,
                            "subId": "",
                            "reset": 0,
                            "comment": "",
                        })

                settings = json.dumps({
                    "clients": clients_json,
                    "decryption": "none",
                    "fallbacks": []
                }, ensure_ascii=False)

                # Keep stream_settings simple & compatible
                stream_settings = json.dumps({
                    "network": "tcp",
                    "security": "none",
                    "tcpSettings": {
                        "header": {"type": "none"},
                        "acceptProxyProtocol": False
                    }
                })

                sniffing = json.dumps({
                    "enabled": False,
                    "destOverride": ["http", "tls", "quic"]
                })

                tag = f"in-{missing_id}-restored"

                # Insert the inbound (preserve original id)
                cur.execute("""
                    INSERT INTO inbounds
                    (id, user_id, up, down, total, remark, enable, expiry_time,
                     listen, port, protocol, settings, stream_settings, tag, sniffing)
                    VALUES (?, 1, 0, 0, 0, ?, 1, 0, '', 8443, 'vless', ?, ?, ?, ?)
                """, (
                    missing_id,
                    f"Restored_Inbound_{missing_id}",
                    settings,
                    stream_settings,
                    tag,
                    sniffing
                ))

                # Link clients via client_inbounds
                if has_client_inbounds and client_ids_to_link:
                    now_ms = int(time.time() * 1000)
                    for cid in client_ids_to_link:
                        # avoid duplicate primary-key error
                        cur.execute("""
                            INSERT OR IGNORE INTO client_inbounds
                            (client_id, inbound_id, flow_override, created_at)
                            VALUES (?, ?, NULL, ?)
                        """, (cid, missing_id, now_ms))

                conn.commit()
                log.info(f"✅ Restored inbound ID {missing_id} with {len(clients_json)} clients + client_inbounds links")

        # ============================================================
        # 2. Sync existing inbounds (only if we did NOT just restore)
        # ============================================================
        if not modified:
            cur.execute("SELECT id, settings FROM inbounds")
            for inbound in cur.fetchall():
                inbound_id = inbound["id"]
                try:
                    settings = json.loads(inbound["settings"] or "{}")
                except Exception:
                    settings = {}

                if "clients" not in settings or not isinstance(settings["clients"], list):
                    settings["clients"] = []

                existing_emails = {c.get("email"): c for c in settings["clients"] if c.get("email")}

                # clients that belong to this inbound according to client_traffics
                cur.execute(
                    "SELECT email FROM client_traffics WHERE inbound_id = ?",
                    (inbound_id,)
                )
                db_emails = [r["email"] for r in cur.fetchall() if r["email"]]

                changed = False
                for email in db_emails:
                    if email in existing_emails:
                        continue

                    # need to add this client into settings
                    if has_clients_table:
                        cur.execute("SELECT * FROM clients WHERE email = ?", (email,))
                        crow = cur.fetchone()
                        if crow:
                            settings["clients"].append(build_client_json(crow))
                            changed = True

                            # also ensure client_inbounds link exists
                            if has_client_inbounds:
                                now_ms = int(time.time() * 1000)
                                cur.execute("""
                                    INSERT OR IGNORE INTO client_inbounds
                                    (client_id, inbound_id, flow_override, created_at)
                                    VALUES (?, ?, NULL, ?)
                                """, (crow["id"], inbound_id, now_ms))
                        else:
                            log.warning(f"Email {email} exists in client_traffics but not in clients table")
                    else:
                        import uuid as uuid_mod
                        settings["clients"].append({
                            "id": str(uuid_mod.uuid4()),
                            "email": email,
                            "flow": "",
                            "limitIp": 0,
                            "totalGB": 0,
                            "expiryTime": 0,
                            "enable": True,
                            "tgId": 0,
                            "subId": "",
                        })
                        changed = True

                if changed:
                    if not modified:
                        stop_xui()
                        conn.close()
                        conn = get_conn()
                        cur = conn.cursor()
                        modified = True

                    cur.execute(
                        "UPDATE inbounds SET settings = ? WHERE id = ?",
                        (json.dumps(settings, ensure_ascii=False), inbound_id)
                    )
                    conn.commit()
                    log.info(f"✔ Synced clients for inbound ID {inbound_id}")

        # ============================================================
        # 3. Fix missing client_inbounds links for already-restored inbounds
        #    (covers the current broken state of inbound 14)
        # ============================================================
        if has_clients_table and has_client_inbounds:
            cur.execute("""
                SELECT ct.inbound_id, c.id AS client_id, c.email
                FROM client_traffics ct
                JOIN clients c ON c.email = ct.email
                WHERE ct.inbound_id IS NOT NULL
                  AND ct.inbound_id IN (SELECT id FROM inbounds)
                  AND NOT EXISTS (
                      SELECT 1 FROM client_inbounds ci
                      WHERE ci.client_id = c.id AND ci.inbound_id = ct.inbound_id
                  )
            """)
            missing_links = cur.fetchall()

            if missing_links:
                if not modified:
                    stop_xui()
                    conn.close()
                    conn = get_conn()
                    cur = conn.cursor()
                    modified = True

                now_ms = int(time.time() * 1000)
                for row in missing_links:
                    cur.execute("""
                        INSERT OR IGNORE INTO client_inbounds
                        (client_id, inbound_id, flow_override, created_at)
                        VALUES (?, ?, NULL, ?)
                    """, (row["client_id"], row["inbound_id"], now_ms))
                    log.info(f"🔗 Linked client {row['email']} → inbound {row['inbound_id']}")

                # Also make sure the settings JSON of those inbounds contains the correct UUIDs
                affected_inbounds = {r["inbound_id"] for r in missing_links}
                for iid in affected_inbounds:
                    cur.execute("SELECT settings FROM inbounds WHERE id = ?", (iid,))
                    row = cur.fetchone()
                    if not row:
                        continue
                    try:
                        settings = json.loads(row["settings"] or "{}")
                    except Exception:
                        settings = {"clients": []}

                    # rebuild clients list from real data
                    cur.execute("""
                        SELECT c.* FROM clients c
                        JOIN client_traffics ct ON ct.email = c.email
                        WHERE ct.inbound_id = ?
                    """, (iid,))
                    real_clients = [build_client_json(r) for r in cur.fetchall()]
                    settings["clients"] = real_clients
                    if "decryption" not in settings:
                        settings["decryption"] = "none"
                    if "fallbacks" not in settings:
                        settings["fallbacks"] = []

                    cur.execute(
                        "UPDATE inbounds SET settings = ? WHERE id = ?",
                        (json.dumps(settings, ensure_ascii=False), iid)
                    )
                    log.info(f"🔄 Rebuilt settings JSON for inbound {iid} with real UUIDs")

                conn.commit()

    except Exception as e:
        log.error(f"Error in watcher: {e}", exc_info=True)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if modified:
            start_xui()


if __name__ == "__main__":
    log.info("🚀 Node Watcher (Sanayi-compatible) started")
    while True:
        try:
            auto_heal_and_sync()
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
        time.sleep(CHECK_INTERVAL)
