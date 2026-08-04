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

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# ---------- prerequisites (only if missing) ----------
echo "Checking prerequisites..."

MISSING=()
need_cmd python3 || MISSING+=("python3")
need_cmd jq     || MISSING+=("jq")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Installing missing packages: ${MISSING[*]}"
    if need_cmd apt-get; then
        apt-get update -qq
        apt-get install -y -qq "${MISSING[@]}"
    elif need_cmd yum; then
        yum install -y "${MISSING[@]}"
    else
        echo "❌ Cannot install packages automatically. Please install: ${MISSING[*]}"
        exit 1
    fi
else
    echo "✔ python3 and jq already installed – skipping"
fi
echo ""

# ---------- stop old service ----------
systemctl stop node-watcher 2>/dev/null || true

# ---------- create dir & copy files ----------
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/node_watcher.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/checker.sh" "$INSTALL_DIR/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/node_watcher.py"
[ -f "$INSTALL_DIR/checker.sh" ] && chmod +x "$INSTALL_DIR/checker.sh"
ln -sf "$INSTALL_DIR/checker.sh" /usr/local/bin/checker 2>/dev/null || true

# ---------- interactive config ----------
echo "چند تا inbound می‌خوای watch بشه؟"
NUM=$(ask "تعداد inbound" "1")

if ! [[ "$NUM" =~ ^[0-9]+$ ]] || [ "$NUM" -lt 1 ]; then
    echo "❌ عدد نامعتبر"
    exit 1
fi

echo ""
echo "برای هر inbound، JSON کاملش رو از پنل کپی کن و اینجا پیست کن."
echo "بعد از پیست کردن، یک خط خالی بذار و بعد Ctrl+D بزن."
echo ""

WATCHED_JSON="[]"

for ((i=1; i<=NUM; i++)); do
    echo "---------- Inbound #$i از $NUM ----------"
    echo "JSON کامل inbound رو پیست کن (بعدش Ctrl+D):"
    echo ""

    # read multi-line JSON until EOF (Ctrl+D)
    RAW_JSON=$(cat)

    # validate json
    if ! echo "$RAW_JSON" | jq empty 2>/dev/null; then
        echo "❌ JSON نامعتبر است. دوباره تلاش کن."
        exit 1
    fi

    # extract fields
    ID=$(echo "$RAW_JSON" | jq -r '.id // empty')
    PORT=$(echo "$RAW_JSON" | jq -r '.port // 8443')
    REMARK=$(echo "$RAW_JSON" | jq -r '.remark // "Watched_Inbound"')
    PROTOCOL=$(echo "$RAW_JSON" | jq -r '.protocol // "vless"')
    TAG=$(echo "$RAW_JSON" | jq -r '.tag // ("in-" + (.id|tostring) + "-watched")')
    LISTEN=$(echo "$RAW_JSON" | jq -r '.listen // ""')

    # stream_settings (panel uses streamSettings camelCase)
    STREAM=$(echo "$RAW_JSON" | jq -c '.streamSettings // .stream_settings // {"network":"tcp","security":"none"}')

    # sniffing
    SNIFF=$(echo "$RAW_JSON" | jq -c '.sniffing // {"enabled":false}')

    # client emails from settings.clients
    EMAILS_JSON=$(echo "$RAW_JSON" | jq -c '[.settings.clients[]?.email // empty] | map(select(. != null and . != ""))')

    if [ -z "$ID" ] || [ "$ID" = "null" ]; then
        echo "❌ فیلد id در JSON پیدا نشد"
        exit 1
    fi

    echo ""
    echo "  ✔ ID=$ID  Port=$PORT  Remark=$REMARK"
    echo "  ✔ Clients: $(echo "$EMAILS_JSON" | jq -r 'join(", ")')"
    echo ""

    ITEM=$(jq -n \
        --argjson id "$ID" \
        --argjson port "$PORT" \
        --arg remark "$REMARK" \
        --arg protocol "$PROTOCOL" \
        --arg tag "$TAG" \
        --arg listen "$LISTEN" \
        --argjson emails "$EMAILS_JSON" \
        --argjson stream "$STREAM" \
        --argjson sniff "$SNIFF" \
        '{
            id: $id,
            port: $port,
            remark: $remark,
            protocol: $protocol,
            listen: $listen,
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
echo "منوی مدیریت:  checker"
echo ""
systemctl status node-watcher --no-pager -l || true
echo ""
