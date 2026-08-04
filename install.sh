#!/bin/bash
set -e

echo "🔒 Node Inbound Watcher Interactive Setup"
echo "=========================================="

# دریافت اطلاعات حساس از کاربر
read -p "Enter Panel Port (default: 2053): " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-2053}

read -p "Enter Panel Username: " PANEL_USER
read -sp "Enter Panel Password: " PANEL_PASS
echo ""

read -p "Enter Tunnel Inbound Port on Node (e.g. 8443): " TUNNEL_PORT
read -p "Enter Target Client UUID: " CLIENT_UUID
read -p "Enter Target Client Email (default: tunnel-user@node): " CLIENT_EMAIL
CLIENT_EMAIL=${CLIENT_EMAIL:-tunnel-user@node}

INSTALL_DIR=$(pwd)
CONFIG_PATH="${INSTALL_DIR}/inbound_config.json"

# جایگزینی مقادیر در فایل کانفیگ محلی (روی سرور)
echo "📝 Generating local config file..."
cat <<EOF > "$CONFIG_PATH"
{
  "panel_url": "http://127.0.0.1:${PANEL_PORT}",
  "username": "${PANEL_USER}",
  "password": "${PANEL_PASS}",
  "base_path": "",
  "inbound": {
    "remark": "Node-Tunnel-${TUNNEL_PORT}",
    "port": ${TUNNEL_PORT},
    "protocol": "vless",
    "enable": true,
    "settings": {
      "clients": [
        {
          "id": "${CLIENT_UUID}",
          "email": "${CLIENT_EMAIL}",
          "enable": true,
          "expiryTime": 0,
          "totalGB": 0,
          "flow": ""
        }
      ],
      "decryption": "none",
      "fallbacks": []
    },
    "streamSettings": {
      "network": "ws",
      "security": "none",
      "wsSettings": {
        "path": "/tunnel-path",
        "headers": {}
      }
    },
    "sniffing": {
      "enabled": true,
      "destOverride": ["http", "tls"]
    }
  }
}
EOF

# نصب پیش‌نیازها و سرویس
echo "📦 Installing requirements..."
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
echo "✅ Installation successfully completed without exposing credentials!"