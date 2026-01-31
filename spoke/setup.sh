#!/bin/bash

# LGSM Spoke Installer
# Purpose: Auto-install dependencies, configure firewall, and setup persistence as a systemd service.

set -e

echo "Starting LGSM Spoke Setup..."

# 0. Fetch main.py if missing
if [ ! -f "main.py" ]; then
    read -p "Enter Hub IP to fetch agent script [optional]: " HUB_IP_FETCH
    if [ -n "$HUB_IP_FETCH" ]; then
        echo "Fetching agent core from Hub..."
        wget -q -O main.py "http://$HUB_IP_FETCH:49950/install/main.py"
    fi
fi

# 1. Install Dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip ufm tmux

# 2. Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn psutil

# 3. Port Selection
read -p "Enter management port [default 49950]: " SPOKE_PORT
SPOKE_PORT=${SPOKE_PORT:-49950}

# 4. Firewall Hardening (UFW)
read -p "Enter Hub Public IP (to allow management traffic): " HUB_IP
if [ -n "$HUB_IP" ]; then
    echo "Allowing traffic from $HUB_IP on port $SPOKE_PORT..."
    sudo ufw allow from "$HUB_IP" to any port "$SPOKE_PORT"
else
    echo "Warning: No Hub IP provided. UFW rules not applied for source IP limiting."
fi

# 5. Generate API Key
API_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
echo "API_KEY=$API_KEY" > .env
echo "PORT=$SPOKE_PORT" >> .env

# 6. Persistence (systemd)
echo "Setting up systemd service..."
USER_NAME=$(whoami)
SERVICE_FILE="/etc/systemd/system/lgsm-spoke.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=LGSM Secure-Link Spoke Agent
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/uvicorn main:app --host 0.0.0.0 --port $SPOKE_PORT
Restart=always
EnvironmentFile=$(pwd)/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable lgsm-spoke
sudo systemctl start lgsm-spoke

echo "------------------------------------------------"
echo "Setup Complete!"
echo "Spoke is running on port $SPOKE_PORT"
echo "API KEY: $API_KEY"
echo "Please add this IP and Key to your Hub Dashboard."
echo "------------------------------------------------"
