#!/bin/bash
INSTALL_DIR="/opt/node-watcher"
CONFIG_FILE="${INSTALL_DIR}/config.json"
BACKUP_DIR="${INSTALL_DIR}/backups"
IMPORT_DIR="${INSTALL_DIR}/IMPORT"
REPO_URL="https://github.com/em2be/nodechecker.git"

mkdir -p "$BACKUP_DIR" "$IMPORT_DIR"

# ---------- helpers ----------
load_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "❌ config.json یافت نشد: $CONFIG_FILE"
        return 1
    fi
    cat "$CONFIG_FILE"
}

save_config() {
    local data="$1"
    echo "$data" | jq . > "$CONFIG_FILE"
}

restart_service() {
    systemctl restart node-watcher 2>/dev/null || true
    echo "✔ سرویس restart شد"
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

list_watched() {
    local cfg
    cfg=$(load_config) || return 1
    local count
    count=$(echo "$cfg" | jq '.watched_inbounds | length')
    if [ "$count" -eq 0 ]; then
        echo "(لیست خالی است)"
        return 0
    fi
    echo "$cfg" | jq -r '
      .watched_inbounds
      | to_entries[]
      | "  [\(.key)]  ID=\(.value.id)  port=\(.value.port)  remark=\(.value.remark)  clients=\((.value.client_emails // [])|join(","))"
    '
}

# ---------- submenu: manage inbounds ----------
manage_inbounds_menu() {
    while true; do
        clear
        echo "=========================================="
        echo "  Manage Watched Inbounds"
        echo "=========================================="
        echo " 0) View current list"
        echo " 1) Add new inbound (paste JSON)"
        echo " 2) Edit inbound (paste new JSON)"
        echo " 3) Remove inbound"
        echo " 4) Export watch list (backup)"
        echo " 5) Import from IMPORT/ or backup"
        echo " 6) Back to main menu"
        echo "=========================================="
        read -rp "Select [0-6]: " sub
        case $sub in
            0)
                echo ""
                echo "--- Watched Inbounds ---"
                list_watched
                echo ""
                read -rp "Press Enter..."
                ;;
            1)
                echo ""
                RAW=$(read_json_paste "New inbound JSON") || {
                    read -rp "Press Enter..."
                    continue
                }
                ITEM=$(echo "$RAW" | normalize_inbound_json) || {
                    echo "❌ normalize failed"
                    read -rp "Press Enter..."
                    continue
                }
                echo ""
                echo "خلاصه:"
                echo "$ITEM" | jq -r '"  ID=\(.id)  port=\(.port)  remark=\(.remark)  clients=\(.client_emails|join(","))"'
                read -rp "اضافه شود؟ (y/n) [y]: " conf
                conf=${conf:-y}
                if [[ "$conf" =~ ^[Yy]$ ]]; then
                    cfg=$(load_config)
                    eid=$(echo "$ITEM" | jq '.id')
                    exists=$(echo "$cfg" | jq --argjson id "$eid" '[.watched_inbounds[] | select(.id == $id)] | length')
                    if [ "$exists" -gt 0 ]; then
                        echo "⚠️  inbound با ID=$eid از قبل در لیست هست. اول Remove کن یا Edit کن."
                    else
                        cfg=$(echo "$cfg" | jq --argjson item "$ITEM" '.watched_inbounds += [$item]')
                        save_config "$cfg"
                        restart_service
                        echo "✅ اضافه شد"
                    fi
                else
                    echo "لغو شد"
                fi
                read -rp "Press Enter..."
                ;;
            2)
                echo ""
                echo "--- انتخاب inbound برای ویرایش ---"
                list_watched
                cfg=$(load_config) || {
                    read -rp "Press Enter..."
                    continue
                }
                count=$(echo "$cfg" | jq '.watched_inbounds | length')
                if [ "$count" -eq 0 ]; then
                    echo "لیست خالی است"
                    read -rp "Press Enter..."
                    continue
                fi
                read -rp "شماره ردیف [0-$((count-1))]: " idx
                if ! [[ "$idx" =~ ^[0-9]+$ ]] || [ "$idx" -ge "$count" ]; then
                    echo "❌ شماره نامعتبر"
                    read -rp "Press Enter..."
                    continue
                fi
                echo ""
                echo "فعلی:"
                echo "$cfg" | jq --argjson i "$idx" '.watched_inbounds[$i]'
                RAW=$(read_json_paste "JSON جدید برای جایگزینی") || {
                    read -rp "Press Enter..."
                    continue
                }
                ITEM=$(echo "$RAW" | normalize_inbound_json) || {
                    echo "❌ normalize failed"
                    read -rp "Press Enter..."
                    continue
                }
                echo ""
                echo "جدید:"
                echo "$ITEM" | jq -r '"  ID=\(.id)  port=\(.port)  remark=\(.remark)  clients=\(.client_emails|join(","))"'
                read -rp "جایگزین شود؟ (y/n) [y]: " conf
                conf=${conf:-y}
                if [[ "$conf" =~ ^[Yy]$ ]]; then
                    cfg=$(echo "$cfg" | jq --argjson i "$idx" --argjson item "$ITEM" '.watched_inbounds[$i] = $item')
                    save_config "$cfg"
                    restart_service
                    echo "✅ ویرایش شد"
                else
                    echo "لغو شد"
                fi
                read -rp "Press Enter..."
                ;;
            3)
                echo ""
                echo "--- انتخاب inbound برای حذف ---"
                list_watched
                cfg=$(load_config) || {
                    read -rp "Press Enter..."
                    continue
                }
                count=$(echo "$cfg" | jq '.watched_inbounds | length')
                if [ "$count" -eq 0 ]; then
                    echo "لیست خالی است"
                    read -rp "Press Enter..."
                    continue
                fi
                read -rp "شماره ردیف برای حذف [0-$((count-1))]: " idx
                if ! [[ "$idx" =~ ^[0-9]+$ ]] || [ "$idx" -ge "$count" ]; then
                    echo "❌ شماره نامعتبر"
                    read -rp "Press Enter..."
                    continue
                fi
                echo "$cfg" | jq --argjson i "$idx" -r '
                  .watched_inbounds[$i]
                  | "  حذف: ID=\(.id)  remark=\(.remark)"
                '
                read -rp "مطمئنی؟ (y/n) [n]: " conf
                conf=${conf:-n}
                if [[ "$conf" =~ ^[Yy]$ ]]; then
                    cfg=$(echo "$cfg" | jq --argjson i "$idx" 'del(.watched_inbounds[$i])')
                    save_config "$cfg"
                    restart_service
                    echo "✅ حذف شد"
                else
                    echo "لغو شد"
                fi
                read -rp "Press Enter..."
                ;;
            4)
                mkdir -p "$BACKUP_DIR"
                TS=$(date +%Y%m%d_%H%M%S)
                OUT="${BACKUP_DIR}/watched_${TS}.json"
                cfg=$(load_config) || {
                    read -rp "Press Enter..."
                    continue
                }
                echo "$cfg" | jq '{watched_inbounds, exported_at: now | todate, db_path, check_interval}' > "$OUT"
                echo ""
                echo "✅ بکاپ ذخیره شد:"
                echo "   $OUT"
                echo ""
                echo "برای دانلود از روی سیستم خودت مثلاً:"
                echo "   scp root@SERVER:$OUT ."
                read -rp "Press Enter..."
                ;;
            5)
                echo ""
                echo "--- فایل‌های موجود در IMPORT/ ---"
                shopt -s nullglob
                files=("$IMPORT_DIR"/*.json)
                if [ ${#files[@]} -eq 0 ]; then
                    echo "(خالی — فایل JSON را در $IMPORT_DIR بگذار)"
                    echo ""
                    echo "--- بکاپ‌های موجود ---"
                    bfiles=("$BACKUP_DIR"/*.json)
                    if [ ${#bfiles[@]} -eq 0 ]; then
                        echo "(بکاپ هم نیست)"
                        read -rp "Press Enter..."
                        continue
                    fi
                    for i in "${!bfiles[@]}"; do
                        echo "  [b$i] ${bfiles[$i]}"
                    done
                    read -rp "انتخاب بکاپ (مثلاً b0) یا Enter برای لغو: " pick
                    if [[ "$pick" =~ ^b[0-9]+$ ]]; then
                        bi=${pick#b}
                        SRC="${bfiles[$bi]}"
                    else
                        echo "لغو شد"
                        read -rp "Press Enter..."
                        continue
                    fi
                else
                    for i in "${!files[@]}"; do
                        echo "  [$i] ${files[$i]}"
                    done
                    echo ""
                    echo "--- بکاپ‌ها ---"
                    bfiles=("$BACKUP_DIR"/*.json)
                    for i in "${!bfiles[@]}"; do
                        echo "  [b$i] ${bfiles[$i]}"
                    done
                    read -rp "شماره فایل IMPORT یا bN برای بکاپ: " pick
                    if [[ "$pick" =~ ^b[0-9]+$ ]]; then
                        bi=${pick#b}
                        SRC="${bfiles[$bi]}"
                    elif [[ "$pick" =~ ^[0-9]+$ ]] && [ "$pick" -lt ${#files[@]} ]; then
                        SRC="${files[$pick]}"
                    else
                        echo "❌ نامعتبر"
                        read -rp "Press Enter..."
                        continue
                    fi
                fi
                shopt -u nullglob

                if [ ! -f "$SRC" ]; then
                    echo "❌ فایل پیدا نشد"
                    read -rp "Press Enter..."
                    continue
                fi
                echo ""
                echo "منبع: $SRC"
                if ! jq empty "$SRC" 2>/dev/null; then
                    echo "❌ JSON نامعتبر"
                    read -rp "Press Enter..."
                    continue
                fi

                IMPORTED=$(jq '
                  if .watched_inbounds then .watched_inbounds
                  elif type == "array" then .
                  else [.] end
                ' "$SRC")

                echo "تعداد inbound در فایل: $(echo "$IMPORTED" | jq 'length')"
                echo "$IMPORTED" | jq -r '
                  to_entries[]
                  | "  [\(.key)] ID=\(.value.id) remark=\(.value.remark)"
                '
                echo ""
                echo "1) جایگزینی کامل لیست فعلی"
                echo "2) ادغام (اضافه کردن، ID تکراری نادیده)"
                read -rp "انتخاب [1/2]: " mode
                cfg=$(load_config)
                if [ "$mode" = "1" ]; then
                    NORM="[]"
                    len=$(echo "$IMPORTED" | jq 'length')
                    for ((i=0; i<len; i++)); do
                        one=$(echo "$IMPORTED" | jq --argjson i "$i" '.[$i]')
                        n=$(echo "$one" | normalize_inbound_json)
                        NORM=$(echo "$NORM" | jq --argjson item "$n" '. + [$item]')
                    done
                    cfg=$(echo "$cfg" | jq --argjson w "$NORM" '.watched_inbounds = $w')
                    save_config "$cfg"
                    restart_service
                    echo "✅ لیست جایگزین شد"
                else
                    len=$(echo "$IMPORTED" | jq 'length')
                    for ((i=0; i<len; i++)); do
                        one=$(echo "$IMPORTED" | jq --argjson i "$i" '.[$i]')
                        n=$(echo "$one" | normalize_inbound_json)
                        eid=$(echo "$n" | jq '.id')
                        exists=$(echo "$cfg" | jq --argjson id "$eid" '[.watched_inbounds[] | select(.id == $id)] | length')
                        if [ "$exists" -eq 0 ]; then
                            cfg=$(echo "$cfg" | jq --argjson item "$n" '.watched_inbounds += [$item]')
                            echo "  + اضافه شد ID=$eid"
                        else
                            echo "  ~ رد شد (تکراری) ID=$eid"
                        fi
                    done
                    save_config "$cfg"
                    restart_service
                    echo "✅ ادغام تمام شد"
                fi
                read -rp "Press Enter..."
                ;;
            6)
                return
                ;;
            *)
                echo "❌ نامعتبر"
                sleep 1
                ;;
        esac
    done
}

# ---------- main menu ----------
show_menu() {
    clear
    echo "=========================================="
    echo " Node Watcher Management Menu "
    echo "=========================================="
    echo " 1) Uninstall Service"
    echo " 2) Update Script from GitHub"
    echo " 3) Reinstall (Fresh Setup)"
    echo " 4) Manage Watched Inbounds"
    echo " 5) View Logs"
    echo " 6) Start Service"
    echo " 7) Stop Service"
    echo " 8) Change Timer (Interval in Seconds)"
    echo " 9) Status"
    echo "10) Edit raw config.json"
    echo " 0) Exit"
    echo "=========================================="
    read -rp "Select an option [0-10]: " choice
    case $choice in
        1)
            echo "🛑 Uninstalling Node Watcher..."
            systemctl stop node-watcher 2>/dev/null || true
            systemctl disable node-watcher 2>/dev/null || true
            rm -f /etc/systemd/system/node-watcher.service
            systemctl daemon-reload
            rm -rf "$INSTALL_DIR"
            rm -f /usr/local/bin/checker
            echo "✅ Node Watcher fully uninstalled."
            exit 0
            ;;
        2)
            echo "🔄 Updating Node Watcher..."
            if [ -d "$INSTALL_DIR/.git" ]; then
                cd "$INSTALL_DIR" && git pull
                systemctl restart node-watcher
                echo "✅ Updated successfully!"
            else
                echo "❌ Git directory not found in $INSTALL_DIR."
                echo "   Use option 3 (Reinstall) instead."
            fi
            read -rp "Press Enter to return..."
            show_menu
            ;;
        3)
            echo "🔄 Reinstalling Node Watcher..."
            systemctl stop node-watcher 2>/dev/null || true
            TMPDIR=$(mktemp -d)
            git clone "$REPO_URL" "$TMPDIR/repo"
            OLD_CONFIG=""
            [ -f "$CONFIG_FILE" ] && OLD_CONFIG=$(cat "$CONFIG_FILE")
            rm -rf "$INSTALL_DIR"
            mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/backups" "$INSTALL_DIR/IMPORT"
            cp -r "$TMPDIR/repo/"* "$INSTALL_DIR/"
            rm -rf "$TMPDIR"
            chmod +x "$INSTALL_DIR/install.sh" "$INSTALL_DIR/checker.sh" "$INSTALL_DIR/node_watcher.py" 2>/dev/null || true
            ln -sf "$INSTALL_DIR/checker.sh" /usr/local/bin/checker
            if [ -n "$OLD_CONFIG" ]; then
                echo "$OLD_CONFIG" > "$CONFIG_FILE"
                echo "✔ Previous config restored."
                cat > /etc/systemd/system/node-watcher.service << EOF
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
                systemctl enable --now node-watcher
                echo "✅ Reinstalled and service restarted with old config."
            else
                cd "$INSTALL_DIR"
                ./install.sh
            fi
            exit 0
            ;;
        4)
            manage_inbounds_menu
            show_menu
            ;;
        5)
            echo "📋 Showing live logs (Press Ctrl+C to exit logs):"
            journalctl -u node-watcher -f
            show_menu
            ;;
        6)
            systemctl start node-watcher
            echo "✅ Service started."
            read -rp "Press Enter to return..."
            show_menu
            ;;
        7)
            systemctl stop node-watcher
            echo "🛑 Service stopped."
            read -rp "Press Enter to return..."
            show_menu
            ;;
        8)
            if [ -f "$CONFIG_FILE" ]; then
                read -rp "Enter new check interval in seconds (e.g. 30): " SECONDS_VAL
                if [[ "$SECONDS_VAL" =~ ^[0-9]+$ ]]; then
                    python3 -c "
import json
with open('$CONFIG_FILE', 'r+') as f:
    data = json.load(f)
    data['check_interval'] = int($SECONDS_VAL)
    f.seek(0)
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.truncate()
"
                    systemctl restart node-watcher
                    echo "✅ Timer updated to $SECONDS_VAL seconds."
                else
                    echo "❌ Invalid number entered."
                fi
            else
                echo "❌ Configuration file not found!"
            fi
            read -rp "Press Enter to return..."
            show_menu
            ;;
        9)
            systemctl status node-watcher --no-pager -l || true
            echo ""
            if [ -f "$CONFIG_FILE" ]; then
                echo "--- Current config (summary) ---"
                jq '{db_path, check_interval, watched: [.watched_inbounds[] | {id, port, remark, clients: .client_emails}]}' "$CONFIG_FILE" 2>/dev/null || cat "$CONFIG_FILE"
            fi
            read -rp "Press Enter to return..."
            show_menu
            ;;
        10)
            if [ -f "$CONFIG_FILE" ]; then
                nano "$CONFIG_FILE"
                systemctl restart node-watcher
                echo "✅ Config updated and service restarted."
            else
                echo "❌ Configuration file not found: $CONFIG_FILE"
            fi
            read -rp "Press Enter to return..."
            show_menu
            ;;
        0)
            exit 0
            ;;
        *)
            echo "❌ Invalid option!"
            sleep 1
            show_menu
            ;;
    esac
}

show_menu
