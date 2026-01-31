#!/bin/bash

# LGSM Spoke Installer
# Purpose: Auto-install dependencies, configure firewall, and setup persistence as a systemd service.

set -e

echo "Starting LGSM Spoke Setup..."

# 0. Create Application Directory
APP_DIR="/opt/lgsm-spoke"
echo "Creating application directory at $APP_DIR..."
sudo mkdir -p "$APP_DIR"
sudo chown $(whoami):$(whoami) "$APP_DIR"
cd "$APP_DIR"

# 1. Configuration & Fetching
read -p "Enter Hub IP Address [e.g. 192.168.1.100, optional]: " HUB_IP

if [ ! -f "main.py" ]; then
    if [ -n "$HUB_IP" ]; then
        echo "Fetching agent core from Hub..."
        wget -q -O main.py "http://$HUB_IP:49950/install/main.py"
    else
        echo "Warning: main.py is missing and no Hub IP provided to fetch it."
    fi
fi

# 2. Install Dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip tmux curl

# 3. Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn psutil httpx

# 4. Port Selection
read -p "Enter management port [default 49950]: " SPOKE_PORT
SPOKE_PORT=${SPOKE_PORT:-49950}

# 5. Firewall Hardening (UFW)
if command -v ufw >/dev/null 2>&1; then
    if [ -n "$HUB_IP" ]; then
        echo "Allowing traffic from $HUB_IP on port $SPOKE_PORT using UFW..."
        sudo ufw allow from "$HUB_IP" to any port "$SPOKE_PORT"
    else
        read -p "Enter Hub Public IP (to allow management traffic) [optional]: " ALT_HUB_IP
        if [ -n "$ALT_HUB_IP" ]; then
             sudo ufw allow from "$ALT_HUB_IP" to any port "$SPOKE_PORT"
             HUB_IP=$ALT_HUB_IP
        else
            echo "Warning: No Hub IP provided. UFW rules not applied for source IP limiting."
        fi
    fi
else
    echo "Notice: UFW not found. Skipping firewall configuration."
    echo "Please ensure port $SPOKE_PORT is open on your network firewall."
fi

# 6. Generate API Key
API_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
echo "API_KEY=$API_KEY" > .env
echo "PORT=$SPOKE_PORT" >> .env
if [ -n "$HUB_IP" ]; then
    echo "HUB_IP=$HUB_IP" >> .env
fi

# 7. Persistence (systemd)
echo "Setting up systemd service..."
USER_NAME=$(whoami)
SERVICE_FILE="/etc/systemd/system/lgsm-spoke.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=LGSM Secure-Link Spoke Agent
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port $SPOKE_PORT
Restart=always
EnvironmentFile=$APP_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable lgsm-spoke
sudo systemctl start lgsm-spoke

# 8. Auto-Registration
if [ -n "$HUB_IP" ]; then
    echo "Attempting auto-registration with Hub at $HUB_IP..."
    SPOKE_IP=$(hostname -I | awk '{print $1}')
    SPOKE_NAME=$(hostname)
    
    # Try to register
    curl -X POST "http://$HUB_IP:49950/spokes/register" \
         -H "Content-Type: application/json" \
         -d "{\"name\": \"$SPOKE_NAME\", \"ip\": \"$SPOKE_IP\", \"port\": $SPOKE_PORT, \"api_key\": \"$API_KEY\"}" || echo "Auto-registration failed. Please add manually."
fi

echo "------------------------------------------------"
echo "Setup Complete!"
echo "Spoke is running and installed at $APP_DIR"
echo "Spoke is running on port $SPOKE_PORT"
echo "API KEY: $API_KEY"
echo "------------------------------------------------"
