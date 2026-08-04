#!/bin/bash
set -e

echo "=============================================="
echo "  Node Watcher Installer (Sanayi / 3X-UI)"
echo "=============================================="
echo ""

INSTALL_DIR="/opt/node-watcher"
SERVICE_FILE="/etc/systemd/system/node-watcher.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------- helpers ----------
ask() {
    local prompt="$1"
    local default="$2"
    local val
    if [ -n "$default" ]; then
        read -rp "$prompt [$default]: " val
        echo "${val:-$default}"
    else
        read -rp "$prompt: " val
        echo "$val"
    fi
}

# ---------- stop old service ----------
systemctl stop node-watcher 2>/dev/null || true

# ---------- create dir ----------
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/node_watcher.py" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/node_watcher.py"

# ---------- interactive config ----------
echo ""
echo "چند تا inbound می‌خوای watch بشه؟"
NUM=$(ask "تعداد inbound" "1")

if ! [[ "$NUM" =~ ^[0-9]+$ ]] || [ "$NUM" -lt 1 ]; then
    echo "❌ عدد نامعتبر"
    exit 1
fi

echo ""
echo "حالا برای هر inbound اطلاعات لازم رو وارد کن."
echo "(می‌تونی از پنل → Inbounds → Export یا از دیتابیس JSON بگیری)"
echo ""

WATCHED_JSON="[]"

for ((i=1; i<=NUM; i++)); do
    echo "---------- Inbound #$i از $NUM ----------"

    ID=$(ask "  ID اینباند (عدد)" "")
    PORT=$(ask "  Port" "8443")
    REMARK=$(ask "  Remark / نام" "Watched_Inbound_$ID")
    PROTOCOL=$(ask "  Protocol" "vless")
    TAG=$(ask "  Tag" "in-${ID}-watched")

    echo ""
    echo "  ایمیل کلاینت‌هایی که متعلق به این inbound هستن رو وارد کن"
    echo "  (با کاما جدا کن، مثال: USAob8443,Nob8443)"
    EMAILS_RAW=$(ask "  Client emails" "")
    # convert to json array
    EMAILS_JSON="[]"
    if [ -n "$EMAILS_RAW" ]; then
        EMAILS_JSON=$(echo "$EMAILS_RAW" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' | jq -R . | jq -s .)
    fi

    echo ""
    echo "  آیا می‌خوای stream_settings و sniffing پیش‌فرض باشه؟ (y/n)"
    USE_DEFAULT=$(ask "  پیش‌فرض؟" "y")

    if [[ "$USE_DEFAULT" =~ ^[Yy]$ ]]; then
        STREAM='{"network":"tcp","security":"none","tcpSettings":{"header":{"type":"none"},"acceptProxyProtocol":false}}'
        SNIFF='{"enabled":false,"destOverride":["http","tls","quic"]}'
    else
        echo "  stream_settings رو به صورت یک خط JSON وارد کن:"
        read -r STREAM
        echo "  sniffing رو به صورت یک خط JSON وارد کن:"
        read -r SNIFF
    fi

    # build one inbound object
    ITEM=$(jq -n \
        --argjson id "$ID" \
        --argjson port "$PORT" \
        --arg remark "$REMARK" \
        --arg protocol "$PROTOCOL" \
        --arg tag "$TAG" \
        --argjson emails "$EMAILS_JSON" \
        --argjson stream "$STREAM" \
        --argjson sniff "$SNIFF" \
        '{
            id: $id,
            port: $port,
            remark: $remark,
            protocol: $protocol,
            listen: "",
            tag: $tag,
            client_emails: $emails,
            stream_settings: $stream,
            sniffing: $sniff
        }')

    WATCHED_JSON=$(echo "$WATCHED_JSON" | jq --argjson item "$ITEM" '. + [$item]')
    echo "  ✔ Inbound #$i ثبت شد"
    echo ""
done

# ---------- write config.json ----------
DB_PATH=$(ask "مسیر دیتابیس" "/etc/x-ui/x-ui.db")
INTERVAL=$(ask "فاصله چک (ثانیه)" "15")

jq -n \
    --arg db "$DB_PATH" \
    --argjson interval "$INTERVAL" \
    --argjson watched "$WATCHED_JSON" \
    '{
        db_path: $db,
        check_interval: $interval,
        log_file: "/var/log/node_watcher.log",
        watched_inbounds: $watched
    }' > "$INSTALL_DIR/config.json"

echo ""
echo "✅ config.json ساخته شد:"
cat "$INSTALL_DIR/config.json"
echo ""

# ---------- systemd service ----------
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Node Watcher - Auto heal & sync for 3X-UI / Sanayi panel
After=network.target x-ui.service
Wants=x-ui.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/node_watcher.py
Restart=always
RestartSec=8
StandardOutput=journal
StandardError=journal
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable node-watcher
systemctl restart node-watcher

echo ""
echo "=============================================="
echo "  نصب تموم شد!"
echo "=============================================="
echo ""
echo "وضعیت سرویس:"
systemctl status node-watcher --no-pager -l || true
echo ""
echo "لاگ زنده:"
echo "  journalctl -u node-watcher -f"
echo ""
echo "ویرایش کانفیگ:"
echo "  nano $INSTALL_DIR/config.json"
echo "  systemctl restart node-watcher"
echo ""
