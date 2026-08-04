#!/bin/bash
set -e

INSTALL_DIR="/opt/node-watcher"

echo "🔒 Node Inbound Watcher Installation"
echo "======================================"

# ساخت پوشه اختصاصی جهت جلوگیری از مشکلات مسیردهی
mkdir -p "$INSTALL_DIR"
cp node_watcher.py "$INSTALL_DIR/" 2>/dev/null || true
cd "$INSTALL_DIR"

CONFIG_PATH="${INSTALL_DIR}/inbound_config.json"

read -p "Enter Panel Port (default: 2053): " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-2053}

read -p "Enter Panel Username: " PANEL_USER
read -sp "Enter Panel Password: " PANEL_PASS
echo ""

echo "----------------------------------------------------"
echo "Paste your Inbound JSON below and press Ctrl+D when finished:"
echo "----------------------------------------------------"

INBOUND_JSON=$(cat)

if [ -z "$INBOUND_JSON" ]; then
  echo "❌ Error: Inbound JSON cannot be empty!"
  exit 1
fi

echo "📝 Generating inbound_config.json..."
python3 -c "
import json, sys

panel_url = 'http://127.0.0.1:${PANEL_PORT}'
username = '''${PANEL_USER}'''
password = '''${PANEL_PASS}'''
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
    'check_interval': 60,
    'inbound': inbound_data
}

with open('$CONFIG_PATH', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print('✅ Configuration created successfully.')
"

echo "📦 Installing requirements..."
DEBIAN_FRONTEND=noninteractive apt-get update -y > /dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-requests python3-pip nano > /dev/null

cat <<SERVICE_EOF > /etc/systemd/system/node-watcher.service
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
SERVICE_EOF

# ایجاد دستور checker
cp checker.sh /usr/local/bin/checker
chmod +x /usr/local/bin/checker

systemctl daemon-reload
systemctl enable node-watcher
systemctl restart node-watcher

echo ""
echo "✅ Setup finished! Type 'checker' in your terminal to open management menu."
