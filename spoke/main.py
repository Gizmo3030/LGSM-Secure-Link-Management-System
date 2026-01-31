import os
import subprocess
import psutil
import httpx
import socket
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import asyncio

app = FastAPI(title="LGSM Spoke Agent")

# Environment variables loaded from .env via systemd
API_KEY = os.getenv("API_KEY")
HUB_IP = os.getenv("HUB_IP")
PORT = int(os.getenv("PORT", 49950))
# GAME_USERS can be a comma-separated list of usernames
GAME_USERS = os.getenv("GAME_USERS", os.getenv("GAME_USER", "auto"))

def get_target_users():
    """Returns a list of (username, home_dir) to monitor."""
    import pwd
    targets = []
    
    if GAME_USERS == "auto":
        # Auto-discover LGSM users: any real user with a home in /home
        for p in pwd.getpwall():
            if p.pw_dir.startswith("/home/") and p.pw_uid >= 1000:
                targets.append((p.pw_name, p.pw_dir))
    else:
        # Use specifically configured users
        user_list = [u.strip() for u in GAME_USERS.split(",") if u.strip()]
        for username in user_list:
            try:
                p = pwd.getpwnam(username)
                targets.append((p.pw_name, p.pw_dir))
            except KeyError:
                print(f"Warning: Configured user '{username}' not found on system.")
    return targets

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def register_with_hub():
    if HUB_IP:
        try:
            # Get the primary IP address of the spoke
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((HUB_IP, 49950))
            spoke_ip = s.getsockname()[0]
            s.close()
            
            spoke_name = socket.gethostname()
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://{HUB_IP}:49950/spokes/register",
                    json={
                        "name": spoke_name,
                        "ip": spoke_ip,
                        "port": PORT,
                        "api_key": API_KEY
                    },
                    timeout=5.0
                )
                if resp.status_code == 200:
                    print(f"Successfully registered with hub at {HUB_IP}")
                else:
                    print(f"Hub registration returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Failed to auto-register with hub: {e}")

async def verify_token(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

@app.get("/status")
async def get_status(x_api_key: str = Header(...)):
    await verify_token(x_api_key)
    try:
        all_instances = []
        targets = get_target_users()
        
        for u_name, u_dir in targets:
            # 1. Discover all possible LGSM scripts in the home directory
            scripts = []
            excluded_files = ['setup.sh', 'uninstall.sh', 'main.py', 'linuxgsm.sh', 'lgsm', 'functions', 'log', 'backups', 'serverfiles', 'lgsm-db']
            try:
                for item in os.listdir(u_dir):
                    item_path = os.path.join(u_dir, item)
                    # Heuristic: executable file, not a directory, and not common system or LGSM core files
                    if (os.path.isfile(item_path) and 
                        os.access(item_path, os.X_OK) and 
                        not item.startswith('.') and
                        item not in excluded_files):
                        
                        # Only include if it ends with 'server' or it's a known LGSM script type
                        # Or if it contains 'lgsm' or './functions' in its content (lite check)
                        is_lgsm = item.endswith('server')
                        if not is_lgsm:
                            try:
                                with open(item_path, 'r', errors='ignore') as f:
                                    head = f.read(500)
                                    if 'LGSM' in head or 'linuxgsm' in head or 'check_deps' in head:
                                        is_lgsm = True
                            except:
                                pass
                        
                        if is_lgsm:
                            scripts.append(item)
            except Exception:
                pass

            # 2. Check which ones have active tmux sessions
            active_sessions = []
            try:
                # Get UID for the user to locate the tmux socket
                import pwd
                current_user = pwd.getpwuid(os.getuid()).pw_name
                
                try:
                    user_info = pwd.getpwnam(u_name)
                    uid = user_info.pw_uid
                    socket_path = f"/tmp/tmux-{uid}/default"
                    
                    # If we are the same user or root, we don't need sudo
                    if current_user == u_name or os.getuid() == 0:
                        tmux_cmd = ["tmux"]
                    else:
                        tmux_cmd = ["sudo", "-n", "-u", u_name, "tmux"]
                    
                    if os.path.exists(socket_path):
                        tmux_cmd += ["-S", socket_path]
                    tmux_cmd += ["ls"]
                    
                    result = subprocess.run(
                        tmux_cmd, 
                        capture_output=True, text=True, timeout=2
                    )
                    
                    if result.returncode == 0:
                        for line in result.stdout.strip().split("\n"):
                            if ":" in line:
                                session_name = line.split(":")[0].strip()
                                active_sessions.append(session_name)
                    elif "no server running" in result.stderr.lower() or "failed to connect" in result.stderr.lower():
                        pass
                except KeyError:
                    pass # User doesn't exist?
            except Exception:
                pass

            # 3. Combine into instance objects
            for script in scripts:
                # LGSM session names are often the script name
                # We also check if any active session CONTAINS the script name as a fallback
                is_running = any(script == s or s.startswith(script + "-") for s in active_sessions)
                
                # Double-check with process list as a total fallback
                if not is_running:
                    try:
                        # Check if any process owned by this user has this script name in its cmdline
                        for proc in psutil.process_iter(['username', 'cmdline']):
                            if (proc.info['username'] == u_name and 
                                proc.info['cmdline'] and 
                                any(script in arg for arg in proc.info['cmdline']) and
                                'tmux' in ' '.join(proc.info['cmdline']).lower()):
                                is_running = True
                                break
                    except:
                        pass

                all_instances.append({
                    "user": u_name,
                    "script": script,
                    "session": script if is_running else None,
                    "status": "running" if is_running else "stopped"
                })

            # 4. Add any "Zombie" sessions (tmux sessions with no matching script)
            for session in active_sessions:
                if session not in scripts:
                    all_instances.append({
                        "user": u_name,
                        "script": session,
                        "session": session,
                        "status": "running",
                        "is_zombie": True
                    })

        return {"status": "online", "sessions": all_instances}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/telemetry")
async def get_telemetry(x_api_key: str = Header(...)):
    await verify_token(x_api_key)
    return {
        "cpu_usage": psutil.cpu_percent(interval=1),
        "ram_usage": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage('/').percent
    }

@app.post("/command/{script}/{action}")
async def run_command(script: str, action: str, x_api_key: str = Header(...), user: Optional[str] = None):
    await verify_token(x_api_key)
    allowed_actions = ["start", "stop", "restart", "update", "backup"]
    if action not in allowed_actions:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    # Validate script name to prevent path traversal and command injection
    if not script or '/' in script or '\\' in script or script.startswith('.') or ';' in script or '|' in script or '&' in script:
        raise HTTPException(status_code=400, detail="Invalid script name")
    
    # Resolve which user to run as
    target_user = user
    target_dir = None
    
    if not target_user:
        # Fallback to auto-discovery of the script's owner if not provided
        targets = get_target_users()
        for u_name, u_dir in targets:
            if os.path.exists(f"{u_dir}/{script}"):
                target_user = u_name
                target_dir = u_dir
                break
    else:
        # Get directory for specific requested user
        import pwd
        try:
            target_dir = pwd.getpwnam(target_user).pw_dir
        except:
            raise HTTPException(status_code=404, detail=f"User {target_user} not found")

    if not target_user or not target_dir:
        raise HTTPException(status_code=404, detail=f"Could not locate script '{script}' for any managed user")

    # Construct and run command
    current_user = pwd.getpwuid(os.getuid()).pw_name
    if current_user == target_user or os.getuid() == 0:
        cmd = f"{target_dir}/{script} {action}"
    else:
        cmd = f"sudo -n -u {target_user} {target_dir}/{script} {action}"
        
    subprocess.Popen(cmd.split(), start_new_session=True)
    return {"message": f"Command '{action}' triggered for {script} as {target_user}"}

@app.get("/logs/{script}")
async def get_logs(script: str, x_api_key: str = Header(...), user: Optional[str] = None, lines: int = 100):
    await verify_token(x_api_key)
    
    # Validate script name to prevent path traversal and command injection
    if not script or '/' in script or '\\' in script or script.startswith('.') or ';' in script or '|' in script or '&' in script:
        raise HTTPException(status_code=400, detail="Invalid script name")
    
    # Validate lines parameter to prevent abuse
    if lines < 1 or lines > 10000:
        raise HTTPException(status_code=400, detail="Lines parameter must be between 1 and 10000")
    
    # Discovery user for logs
    target_user = user
    target_dir = None
    
    if not target_user:
        for u_name, u_dir in get_target_users():
            if os.path.exists(f"{u_dir}/log/console/{script}-console.log"):
                target_user = u_name
                target_dir = u_dir
                break
    else:
        import pwd
        try:
            target_dir = pwd.getpwnam(target_user).pw_dir
        except:
            raise HTTPException(status_code=404, detail=f"User {target_user} not found")

    if not target_user or not target_dir:
        raise HTTPException(status_code=404, detail="Could not identify user or directory for this script")

    # Try a few common LGSM log locations
    possible_paths = [
        f"{target_dir}/log/console/{script}-console.log",
        f"{target_dir}/log/console/{script}.log",
        f"{target_dir}/log/{script}-console.log"
    ]
    
    log_path = None
    for p in possible_paths:
        # Since we might not have permission to p, we check existence with sudo if needed
        # but usually os.path.exists works if the agent has some permissions or is root
        if os.path.exists(p):
            log_path = p
            break
            
    if not log_path:
        # Final attempt: just try the most likely one even if os.path.exists failed (permissions?)
        log_path = possible_paths[0]

    try:
        import pwd
        current_user = pwd.getpwuid(os.getuid()).pw_name
        
        # 1. Try direct read first (always preferred if possible)
        try:
            if os.path.exists(log_path) and os.access(log_path, os.R_OK):
                cmd = ["tail", "-n", str(lines), log_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return {"script": script, "logs": result.stdout}
        except:
            pass

        # 2. Try sudo fallback if not same user
        if current_user != target_user and os.getuid() != 0:
            cmd = ["sudo", "-n", "-u", target_user, "tail", "-n", str(lines), log_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                return {"script": script, "logs": result.stdout}
            
            err_msg = result.stderr.lower()
            if "no such file" in err_msg:
                raise HTTPException(status_code=404, detail=f"Log file not found at {log_path}")
            if "password is required" in err_msg or "sudo: a password is required" in err_msg:
                raise HTTPException(status_code=403, detail="Permission denied. Agent cannot use sudo and doesn't have read access to the log file. Try: sudo chmod 644 " + log_path)
            
            return {"error": f"Failed to read logs: {result.stderr or 'Check file permissions'}", "code": result.returncode}
        else:
            # We are the user but tail failed or os.access lied
            return {"error": "Could not read log file. Check if it exists and has content."}

    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@app.websocket("/logs/{script}")
async def stream_logs(websocket: WebSocket, script: str):
    # Note: API Key validation for WebSockets usually happens via query params or subprotocols
    # For simplicity here, we assume the initial handshake or a token param
    await websocket.accept()
    process = None
    try:
        # Validate script name to prevent path traversal and command injection
        if not script or '/' in script or '\\' in script or script.startswith('.') or ';' in script or '|' in script or '&' in script:
            await websocket.send_text("Invalid script name")
            await websocket.close()
            return
        
        # Discovery user for logs
        target_user = None
        target_dir = None
        
        # Try to find which user owns this script/log
        for u_name, u_dir in get_target_users():
            if os.path.exists(f"{u_dir}/log/console/{script}-console.log"):
                target_user = u_name
                target_dir = u_dir
                break
        
        if not target_user:
            await websocket.send_text(f"Log file not found for script {script}")
            await websocket.close()
            return

        log_path = f"{target_dir}/log/console/{script}-console.log"
        cmd = ["sudo", "-n", "-u", target_user, "tail", "-f", log_path]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().strip())
    except WebSocketDisconnect:
        if process:
            process.terminate()
    except Exception as e:
        if websocket:
            await websocket.send_text(f"Error: {str(e)}")
            await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
