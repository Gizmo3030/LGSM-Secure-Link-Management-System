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
# Support for Command Line Arguments
# Usage: ./setup.sh [HUB_ADDRESS] [GAME_USERS]
HUB_ADDR=${1:-""}
GAME_USERS=${2:-""}

if [ -z "$HUB_ADDR" ]; then
    read -p "Enter Hub Address (URL or FQDN) [e.g. http://hub.example.com]: " HUB_ADDR
fi

# Determine HUB_URL and HUB_IP
if [[ "$HUB_ADDR" == http* ]]; then
    # Full URL provided (e.g. from Hub UI)
    HUB_URL="${HUB_ADDR%/}" # Remove trailing slash if any
    HUB_IP=$(echo "$HUB_URL" | sed -e 's|^[^/]*//||' -e 's|[:/].*$||')
else
    # Legacy Host or Host:Port provided
    if [[ "$HUB_ADDR" == *":"* ]]; then
        HUB_IP=$(echo "$HUB_ADDR" | cut -d':' -f1)
        HUB_PORT=$(echo "$HUB_ADDR" | cut -d':' -f2)
    else
        HUB_IP=$HUB_ADDR
        # Default to 49950 if it's an IP, otherwise assume standard web port 80
        if [[ $HUB_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            HUB_PORT=49950
        else
            HUB_PORT=80
        fi
    fi
    
    if [ "$HUB_PORT" == "443" ]; then
        HUB_URL="https://$HUB_IP"
    elif [ "$HUB_PORT" == "80" ]; then
        HUB_URL="http://$HUB_IP"
    else
        HUB_URL="http://$HUB_IP:$HUB_PORT"
    fi
fi

if [ ! -f "main.py" ]; then
    if [ -n "$HUB_IP" ]; then
        echo "Fetching agent core from Hub at $HUB_URL..."
        wget -q -O main.py "$HUB_URL/install/main.py" || { echo "Error: Failed to fetch main.py from $HUB_URL/install/main.py"; exit 1; }
    else
        echo "Warning: main.py is missing and no Hub address provided to fetch it."
    fi
fi

# 2. Install Dependencies
echo "Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip tmux curl -qq

# 3. Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q fastapi uvicorn psutil httpx

# 4. Port & User Selection
SPOKE_PORT=49950
if [ -z "$1" ] && [ -t 0 ]; then
    read -p "Enter management port [default 49950]: " INPUT_PORT
    SPOKE_PORT=${INPUT_PORT:-49950}
fi

if [ -z "$GAME_USERS" ]; then
    if [ -t 0 ]; then
        echo "--- Multi-User Configuration ---"
        echo "You can specify a comma-separated list of users (e.g. pzserver,rustserver)"
        echo "Or leave blank to auto-discover all users in /home."
        read -p "Enter Game Users to monitor [default: auto]: " GAME_USERS
    fi
    GAME_USERS=${GAME_USERS:-"auto"}
fi

# 5. Firewall Hardening (UFW)
if command -v ufw >/dev/null 2>&1; then
    if [ -n "$HUB_IP" ]; then
        echo "Allowing traffic from $HUB_IP on port $SPOKE_PORT using UFW..."
        sudo ufw allow from "$HUB_IP" to any port "$SPOKE_PORT" || true
    else
        if [ -t 0 ]; then
            read -p "Enter Hub Public IP (to allow management traffic) [optional]: " ALT_HUB_IP
            if [ -n "$ALT_HUB_IP" ]; then
                sudo ufw allow from "$ALT_HUB_IP" to any port "$SPOKE_PORT"
                HUB_IP=$ALT_HUB_IP
            fi
        fi
    fi
else
    echo "Notice: UFW not found. Skipping firewall configuration."
fi

# 6. Generate API Key
API_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
echo "API_KEY=$API_KEY" > .env
echo "PORT=$SPOKE_PORT" >> .env
if [ -n "$HUB_IP" ]; then
    echo "HUB_IP=$HUB_IP" >> .env
    echo "HUB_URL=$HUB_URL" >> .env
fi
if [ -n "$GAME_USERS" ]; then
    echo "GAME_USERS=$GAME_USERS" >> .env
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

# 7.5 Setup Sudo Permissions (Auto-Discovery)
echo "Configuring sudoers for LGSM management..."
CURRENT_USER=$(whoami)
SUDOERS_FILE="/etc/sudoers.d/lgsm-spoke-$CURRENT_USER"
TMUX_PATH=$(which tmux || echo "/usr/bin/tmux")
TAIL_PATH=$(which tail || echo "/usr/bin/tail")

if [ "$GAME_USERS" = "auto" ]; then
    # Allow management of ANY user on the system
    # This is safe because only the spoke (authenticated with API KEY) can invoke these
    sudo bash -c "cat > $SUDOERS_FILE" <<EOF
$CURRENT_USER ALL=(ALL) NOPASSWD: $TMUX_PATH ls, $TAIL_PATH -f /home/*/log/console/*, /home/*/* *
EOF
else
    # Allow management of specific users only
    IFS=',' read -ra ADDR <<< "$GAME_USERS"
    SUDO_RULES=""
    for i in "${ADDR[@]}"; do
        USER_TRIM=$(echo "$i" | xargs)
        SUDO_RULES="$SUDO_RULES
$CURRENT_USER ALL=($USER_TRIM) NOPASSWD: $TMUX_PATH ls, $TAIL_PATH -f /home/$USER_TRIM/log/console/*, /home/$USER_TRIM/* *"
    done
    sudo bash -c "cat > $SUDOERS_FILE" <<EOF
$SUDO_RULES
EOF
fi

sudo chmod 440 "$SUDOERS_FILE"
echo "Sudoers permissions configured at $SUDOERS_FILE"

# 8. Auto-Registration
if [ -n "$HUB_IP" ]; then
    echo "Attempting auto-registration with Hub at $HUB_URL..."
    SPOKE_IP=$(hostname -I | awk '{print $1}')
    SPOKE_NAME=$(hostname)
    
    # Try to register
    curl -X POST "$HUB_URL/spokes/register" \
         -H "Content-Type: application/json" \
         -d "{\"name\": \"$SPOKE_NAME\", \"ip\": \"$SPOKE_IP\", \"port\": $SPOKE_PORT, \"api_key\": \"$API_KEY\"}" || echo "Auto-registration failed. Please add manually."
fi

echo "------------------------------------------------"
echo "Setup Complete!"
echo "Spoke is running and installed at $APP_DIR"
echo "Spoke is running on port $SPOKE_PORT"
echo "API KEY: $API_KEY"
echo "------------------------------------------------"
