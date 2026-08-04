#!/bin/bash

set -e

echo "🚀 Starting Node Watcher Installation..."

# ۱. نصب پیش‌نیازها
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y python3 python3-pip python3-sqlite3 >/dev/null 2>&1 || true

# ۲. ساخت مسیر
INSTALL_DIR="/opt/node-watcher"
mkdir -p "$INSTALL_DIR"

# ۳. اصلاح مشکل احتمالی CSRF Secret در دیتابیس x-ui
echo "🔧 Checking and fixing x-ui database secret/token..."
python3 -c "
import sqlite3, os, secrets

db_path = '/etc/x-ui/x-ui.db' if os.path.exists('/etc/x-ui/x-ui.db') else '/usr/local/x-ui/db/x-ui.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(\"SELECT value FROM settings WHERE key = 'secret'\")
    res = c.fetchone()
    if not res or not res[0]:
        new_secret = secrets.token_hex(16)
        c.execute(\"UPDATE settings SET value = ? WHERE key = 'secret'\", (new_secret,))
        conn.commit()
        print('✔ CSRF Secret key fixed in database.')
    conn.close()
"

# ۴. متوقف کردن x-ui جهت اعمال کانفیگ اولیه
systemctl stop x-ui || true

# ۵. ایجاد یا کپی فایل‌های اصلی
# (در صورت دانلود از گیت‌هاب، فایل‌ها کپی می‌شوند)
cp -f node_watcher.py "$INSTALL_DIR/" 2>/dev/null || true
cp -f inbound_config.json "$INSTALL_DIR/" 2>/dev/null || true

# ۶. راه‌اندازی و اجرای اولیه پایشگر
python3 "$INSTALL_DIR/node_watcher.py" &
PID=$!
sleep 3
kill -9 $PID 2>/dev/null || true

# ۷. استارت مجدد x-ui
systemctl start x-ui

# ۸. تنظیم سرویس systemd
cp -f node-watcher.service /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
systemctl enable node-watcher
systemctl restart node-watcher

echo "🎉 Node Watcher Installed & Activated Successfully!"
