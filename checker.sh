#!/bin/bash

INSTALL_DIR="/opt/node-watcher"
CONFIG_FILE="${INSTALL_DIR}/inbound_config.json"

show_menu() {
    clear
    echo "=========================================="
    echo "       Node Watcher Management Menu       "
    echo "=========================================="
    echo " 1) Uninstall Service"
    echo " 2) Update Script from GitHub"
    echo " 3) Reinstall (Fresh Setup)"
    echo " 4) Edit Inbound JSON"
    echo " 5) View Logs"
    echo " 6) Start Service"
    echo " 7) Stop Service"
    echo " 8) Change Timer (Interval in Seconds)"
    echo " 0) Exit"
    echo "=========================================="
    read -p "Select an option [0-8]: " choice

    case $choice in
        1)
            echo "🛑 Uninstalling Node Watcher..."
            systemctl stop node-watcher || true
            systemctl disable node-watcher || true
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
                echo "❌ Git directory not found in $INSTALL_DIR. Reinstalling is recommended."
            fi
            read -p "Press Enter to return..."
            show_menu
            ;;
        3)
            echo "🔄 Reinstalling Node Watcher..."
            systemctl stop node-watcher || true
            rm -rf "$INSTALL_DIR"
            git clone https://github.com/em2be/nodechecker.git "$INSTALL_DIR"
            cd "$INSTALL_DIR"
            chmod +x install.sh checker.sh
            ./install.sh
            exit 0
            ;;
        4)
            if [ -f "$CONFIG_FILE" ]; then
                nano "$CONFIG_FILE"
                systemctl restart node-watcher
                echo "✅ Config updated and service restarted."
            else
                echo "❌ Configuration file not found!"
            fi
            read -p "Press Enter to return..."
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
            read -p "Press Enter to return..."
            show_menu
            ;;
        7)
            systemctl stop node-watcher
            echo "🛑 Service stopped."
            read -p "Press Enter to return..."
            show_menu
            ;;
        8)
            if [ -f "$CONFIG_FILE" ]; then
                read -p "Enter new check interval in seconds (e.g. 30): " SECONDS_VAL
                if [[ "$SECONDS_VAL" =~ ^[0-9]+$ ]]; then
                    python3 -c "
import json
with open('$CONFIG_FILE', 'r+') as f:
    data = json.load(f)
    data['check_interval'] = int($SECONDS_VAL)
    f.seek(0)
    json.dump(data, f, indent=2)
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
            read -p "Press Enter to return..."
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
