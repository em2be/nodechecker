#!/bin/bash
set -e

INSTALL_DIR="/opt/node-watcher"

echo "🔒 Node Inbound Watcher Installation"
echo "======================================"

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

CONFIG_PATH="${INSTALL_DIR}/inbound_config.json"

read -p "Is panel using HTTPS? (y/N): " USE_HTTPS
if [[ "$USE_HTTPS" =~ ^[Yy]$ ]]; then
  SCHEME="https"
else
  SCHEME="http"
fi

read -p "Enter Panel Port (default: 8080): " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-8080}

read -p "Enter Base Path (if any, e.g. /xui or leave empty): " BASE_PATH

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

echo ""
echo "📝 Generating inbound_config.json..."
python3 -c "
import json, sys

panel_url = '${SCHEME}://127.0.0.1:${PANEL_PORT}'
username = '''${PANEL_USER}'''
password = '''${PANEL_PASS}'''
base_path = '''${BASE_PATH}'''
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
    'base_path': base_path,
    'check_interval': 5,
    'inbound': inbound_data
}

with open('$CONFIG_PATH', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print('✅ Configuration created successfully.')
"

echo ""
echo "🔄 [1/3] Checking System Package Status..."
if [ -f /var/lib/apt/periodic/update-success-stamp ] && [ $(find /var/lib/apt/periodic/update-success-stamp -mmin -1440 2>/dev/null) ]; then
    echo "⚡ Package list is already up-to-date. Skipping apt-get update..."
else
    echo "🌐 Updating package index..."
    DEBIAN_FRONTEND=noninteractive apt-get update -y -o Dpkg::Use-PTY=0
    mkdir -p /var/lib/apt/periodic
    touch /var/lib/apt/periodic/update-success-stamp
fi

echo ""
echo "📦 [2/3] Installing Python Dependencies..."
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    -o Dpkg::Progress-Fancy="1" \
    python3-requests python3-urllib3 python3-pip nano git

echo ""
echo "⚙️ [3/3] Configuring Systemd Service..."
cat <<SERVICE_EOF > /etc/systemd/system/node-watcher.service
[Unit]
Description=Node Inbound Auto Healing Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 -u ${INSTALL_DIR}/node_watcher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cp checker.sh /usr/local/bin/checker 2>/dev/null || true
chmod +x /usr/local/bin/checker 2>/dev/null || true

systemctl daemon-reload
systemctl enable node-watcher
systemctl restart node-watcher

echo ""
echo "===================================================="
echo "✅ Installation completed successfully!"
echo "👉 Type 'checker' in your terminal to open management menu."
echo "===================================================="
