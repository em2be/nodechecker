#!/bin/bash
set -e

echo "🔒 Node Inbound Watcher Setup"
echo "=============================="

# دریافت اطلاعات لاگین پنل
read -p "Enter Panel Port (default: 2053): " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-2053}

read -p "Enter Panel Username: " PANEL_USER
read -sp "Enter Panel Password: " PANEL_PASS
echo ""

INSTALL_DIR=$(pwd)
CONFIG_PATH="${INSTALL_DIR}/inbound_config.json"

echo "----------------------------------------------------"
echo "Paste your Inbound JSON below and press Ctrl+D when finished:"
echo "----------------------------------------------------"

# دریافت JSON چندخطی از ترمینال
INBOUND_JSON=$(cat)

# اعتبارسنجی اولیه برای خالی نبودن ورودی
if [ -z "$INBOUND_JSON" ]; then
  echo "❌ Error: Inbound JSON cannot be empty!"
  exit 1
fi

# ساخت فایل کانفیگ نهایی روی سرور
echo "📝 Generating inbound_config.json..."
python3 -c "
import json, sys

panel_url = 'http://127.0.0.1:${PANEL_PORT}'
username = '${PANEL_USER}'
password = '${PANEL_PASS}'

raw_inbound = '''$INBOUND_JSON'''

try:
    inbound_data = json.loads(raw_inbound)
except Exception as e:
    print('❌ Invalid JSON provided:', e)
    sys.exit(1)

config = {
    'panel_url': panel_url,
    'username': username,
    'password': password,
    'base_path': '',
    'inbound': inbound_data
}

with open('$CONFIG_PATH', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print('✅ Configuration created successfully.')
"

# نصب پیش‌نیازها و تعریف سرویس
echo "📦 Setting up environment and systemd service..."
apt-get update -y > /dev/null
apt-get install -y python3 python3-pip > /dev/null
pip3 install requests --break-system-packages > /dev/null 2>&1 || pip3 install requests > /dev/null 2>&1

cat <<EOF > /etc/systemd/system/node-watcher.service
[Unit]
Description=Node Inbound Auto Healing Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/node_watcher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable node-watcher
systemctl restart node-watcher

echo ""
echo "✅ Setup finished and node-watcher service is active!"
