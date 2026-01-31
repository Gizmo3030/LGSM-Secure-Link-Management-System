#!/bin/bash

# LGSM Spoke Uninstaller
# Purpose: Stop services and cleanup spoke installation.

set -e

APP_DIR="/opt/lgsm-spoke"
SERVICE_NAME="lgsm-spoke.service"

echo "Starting LGSM Spoke Uninstallation..."

# 1. Stop and Remove systemd service
if [ -f "/etc/systemd/system/$SERVICE_NAME" ]; then
    echo "Stopping and disabling $SERVICE_NAME..."
    sudo systemctl stop "$SERVICE_NAME" || true
    sudo systemctl disable "$SERVICE_NAME" || true
    sudo rm "/etc/systemd/system/$SERVICE_NAME"
    sudo systemctl daemon-reload
    echo "Service removed."
fi

# 2. Cleanup Firewall (Optional/Best Effort)
if command -v ufw >/dev/null 2>&1; then
    # Try to extract the port from the .env if it exists
    if [ -f "$APP_DIR/.env" ]; then
        SPOKE_PORT=$(grep "PORT=" "$APP_DIR/.env" | cut -d'=' -f2)
        if [ -n "$SPOKE_PORT" ]; then
            echo "Note: You may want to manually remove UFW rules for port $SPOKE_PORT:"
            echo "      sudo ufw delete allow [port]"
        fi
    fi
fi

# 3. Remove Application Directory
if [ -d "$APP_DIR" ]; then
    echo "Removing application directory $APP_DIR..."
    sudo rm -rf "$APP_DIR"
    echo "Files removed."
fi

echo "------------------------------------------------"
echo "Uninstallation Complete!"
echo "Note: This spoke may still appear in your Hub Dashboard."
echo "Please delete it manually from the Dashboard if desired."
echo "------------------------------------------------"
