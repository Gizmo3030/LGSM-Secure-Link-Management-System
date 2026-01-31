# LGSM Secure-Link Management System

A professional-grade, two-part management system for LinuxGSM (LGSM).

## Architecture

1.  **The Spoke**: A headless, lightweight agent installed on game server VMs.
2.  **The Hub**: A secure, Dockerized centralized dashboard to monitor and control all Spokes.

## Components

### Spoke
- **`setup.sh`**: One-click installer.
- **`main.py`**: high-performance Python API (FastAPI) interacting with LGSM.

### Hub
- **`app.py`**: Dashboard backend (FastAPI).
- **`interface.html`**: Dashboard UI (Tailwind CSS).
- **`docker-compose.yml` & `Dockerfile`**: Containerization logic.

## Setup Instructions

### Hub Setup (Central Dashboard)
1. Navigate to the `hub` directory.
2. Run `docker compose up -d`.
3. Access the dashboard at `http://localhost:49950` (default port).

### Spoke Setup (Game Server VM)
**Easy Way (One-Liner):**
1. Ensure the Hub is running.
2. Run this command on your Game Server VM:
   ```bash
   wget -O setup.sh http://YOUR_HUB_IP:49950/install/setup.sh && chmod +x setup.sh && ./setup.sh
   ```
3. Follow the prompts (enter Hub IP when asked to fetch `main.py`).

**Manual Way:**
1. Copy `spoke/setup.sh` and `spoke/main.py` to the game server VM.
2. Run `chmod +x setup.sh && ./setup.sh`.
3. Follow the prompts to configure the Hub IP and API keys.

## Features
- Unified dashboard for all LGSM instances.
- High-speed status reporting via `tmux` checks.
- Asynchronous command execution (start, stop, restart, etc.).
- Real-time log streaming via WebSockets.
- **Security**: JWT authentication, hashed passwords (bcrypt), and IP whitelisting for Spokes.
- **Discord Integration**: Webhook alerts for outages or critical errors.
- **Heartbeat Monitor**: Automated health checks every 60 seconds.

## Advanced Usage

### Discord Alerts
1. Go to **Settings** in the Hub Dashboard.
2. Paste your Discord Webhook URL.
3. The Hub will now ping your Discord if a Spoke goes offline.

### Bulk Actions
The dashboard allows you to view the status of the entire fleet. Standard actions like "Restart All" can be triggered via the Hub API (WIP UI button).
