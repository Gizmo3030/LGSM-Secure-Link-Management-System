# 🎮 LGSM Secure-Link Management System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A centralized management system for [LinuxGSM](https://linuxgsm.com/) (LGSM) that provides a secure dashboard to monitor and control multiple game servers from a single location.

## 🏗️ Architecture

The system consists of two main components:

1.  **The Hub**: A secure, centralized dashboard (Dockerized) used to monitor and control all spokes.
2.  **The Spoke**: A lightweight, headless agent installed on each individual game server VM.

## 🚀 Features

- **Unified Dashboard**: View your entire fleet of game servers at a glance.
- **Instance Control**: Start, stop, restart, and update LGSM instances directly from the UI.
- **Real-Time Logs**: View the last 100 lines of console output for each server.
- **Telemetric Monitoring**: Track CPU, RAM, and Disk usage across all game VMs.
- **Security First**: 
    - JWT-based authentication for the Hub.
    - Hashed passwords via BCrypt.
    - API Key validation between Hub and Spokes.
    - Optional firewall hardening (UFW support in setup).
- **Discord Integration**: Get instant notifications via webhooks when a server goes offline.
- **Auto-Discovery**: Spokes automatically detect LGSM scripts in `/home` directories.

## 🛠️ Components

### Hub
- **Python / FastAPI**: High-performance backend.
- **SQLite**: lightweight database for spoke configurations and user management.
- **Tailwind CSS / Alpine.js**: Modern, responsive dashboard UI.
- **Dockerized**: Easy deployment with `docker-compose`.

### Spoke
- **Python / FastAPI**: lightweight agent.
- **Systemd Integration**: Runs as a background service for high availability.
- **No Global Sudo Required**: Respects security constraints while still providing full control.

## ⚙️ Setup Instructions

### 1. Hub Setup (Central Dashboard)

1.  Navigate to the `hub` directory.
2.  Run the system with Docker:
    ```bash
    docker compose up -d
    ```
3.  Access the dashboard at `http://YOUR_HUB_IP:49950`.
4.  Default credentials: `admin` / `admin123` (Change these immediately in settings!).

### 2. Spoke Setup (Game Server VM)

Run the one-liner on your game server:
```bash
wget -O setup.sh http://YOUR_HUB_IP:49950/install/setup.sh && chmod +x setup.sh && ./setup.sh YOUR_HUB_IP
```
*Note: Replace `YOUR_HUB_IP` with the IP address of your Hub server.*

The installer will:
- Install system dependencies (`python3-venv`, `tmux`, etc.).
- Set up a virtual environment.
- Generate a unique API key.
- Register itself with the Hub.
- Setup a systemd service to start on boot.

## 🛡️ License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details. Free to use, modify, and distribute.

## 🤝 Contributing

Feel free to open issues or submit pull requests to improve the system!

---
*Developed by Gizmo3030*
