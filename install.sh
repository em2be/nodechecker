#!/bin/bash
set -e

echo "=============================================="
echo "  Node Watcher Installer (MHSanaei / 3X-UI)"
echo "=============================================="
echo ""

INSTALL_DIR="/opt/node-watcher"
SERVICE_FILE="/etc/systemd/system/node-watcher.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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

read_json_paste() {
    local label="$1"
    echo ""
    echo ">>> $label"
    echo "    JSON کامل را پیست کنید، بعد Ctrl+D بزنید:"
    echo "----------------------------------------"
    local raw
    raw=$(cat)
    echo "----------------------------------------"
    if ! echo "$raw" | jq empty 2>/dev/null; then
        echo "❌ JSON نامعتبر است"
        return 1
    fi
    echo "$raw"
}

normalize_inbound_json() {
    local raw
    raw=$(cat)
    echo "$raw" | jq '
      (if type == "array" then .[0] else . end) as $o |
      {
        id: ($o.id // $o.Id // 0),
        port: ($o.port // $o.Port // 8443),
        remark: ($o.remark // $o.Remark // ("Watched_" + (($o.id // 0)|tostring))),
        protocol: ($o.protocol // $o.Protocol // "vless"),
        listen: ($o.listen // $o.Listen // ""),
        tag: ($o.tag // $o.Tag // ("in-" + (($o.id // 0)|tostring) + "-watched")),
        stream_settings: (
          if ($o.stream_settings | type) == "object" then $o.stream_settings
          elif ($o.streamSettings | type) == "object" then $o.streamSettings
          elif ($o.stream_settings | type) == "string" then ($o.stream_settings | fromjson? // {})
          elif ($o.streamSettings | type) == "string" then ($o.streamSettings | fromjson? // {})
          else {"network":"tcp","security":"none"} end
        ),
        sniffing: (
          if ($o.sniffing | type) == "object" then $o.sniffing
          elif ($o.sniffing | type) == "string" then ($o.sniffing | fromjson? // {})
          else {"enabled":false} end
        ),
        client_emails: (
          if ($o.client_emails | type) == "array" then $o.client_emails
          elif ($o.settings | type) == "object" and ($o.settings.clients | type) == "array" then
            [$o.settings.clients[]?.email // empty]
          elif ($o.settings | type) == "string" then
            (($o.settings | fromjson? // {}) | .clients // []) | map(.email // empty) | map(select(. != ""))
          elif ($o.clients | type) == "array" then
            [$o.clients[]?.email // empty]
          else [] end
        ),
        clients: (
          if ($o.clients | type) == "array" and (($o.clients|length) > 0) then $o.clients
          elif ($o.settings | type) == "object" and ($o.settings.clients | type) == "array" then $o.settings.clients
          elif ($o.settings | type) == "string" then
            (($o.settings | fromjson? // {}) | .clients // [])
          else [] end
        )
      }
    '
}

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

systemctl stop node-watcher 2>/dev/null || true

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/backups"
mkdir -p "$INSTALL_DIR/IMPORT"

cp "$SCRIPT_DIR/node_watcher.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/checker.sh" "$INSTALL_DIR/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/node_watcher.py"
[ -f "$INSTALL_DIR/checker.sh" ] && chmod +x "$INSTALL_DIR/checker.sh"
ln -sf "$INSTALL_DIR/checker.sh" /usr/local/bin/checker 2>/dev/null || true

echo "چند تا inbound می‌خوای watch بشه؟"
NUM=$(ask "تعداد inbound" "1")

if ! [[ "$NUM" =~ ^[0-9]+$ ]] || [ "$NUM" -lt 1 ]; then
    echo "❌ عدد نامعتبر"
    exit 1
fi

echo ""
echo "برای هر inbound، JSON کامل را از پنل Export کن و پیست کن."
echo "(بعد از پیست، Ctrl+D بزن)"
echo ""

WATCHED_JSON="[]"

for ((i=1; i<=NUM; i++)); do
    echo "========== Inbound #$i از $NUM =========="
    RAW=""
    while true; do
        RAW=$(read_json_paste "Inbound #$i") || continue
        break
    done

    ITEM=$(echo "$RAW" | normalize_inbound_json) || {
        echo "❌ نتوانست JSON را نرمال کند"
        exit 1
    }

    echo ""
    echo "  خلاصه:"
    echo "$ITEM" | jq -r '"  ID=\(.id)  port=\(.port)  remark=\(.remark)  clients=\(.client_emails|join(","))"'
    echo ""

    WATCHED_JSON=$(echo "$WATCHED_JSON" | jq --argjson item "$ITEM" '. + [$item]')
    echo "  ✔ Inbound #$i ثبت شد"
    echo ""
done

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

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Node Watcher - Auto heal & sync for 3X-UI / MHSanaei panel
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
echo "لاگ زنده:     journalctl -u node-watcher -f"
echo "بکاپ‌ها:      $INSTALL_DIR/backups/"
echo "Import:       $INSTALL_DIR/IMPORT/"
echo ""
