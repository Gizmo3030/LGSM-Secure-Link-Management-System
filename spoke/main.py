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
        # Check tmux ls for game server sessions
        result = subprocess.run(["tmux", "ls"], capture_output=True, text=True)
        sessions = result.stdout.strip().split("\n") if result.returncode == 0 else []
        return {"status": "online", "sessions": sessions}
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
async def run_command(script: str, action: str, x_api_key: str = Header(...)):
    await verify_token(x_api_key)
    # Validate action to prevent injection
    allowed_actions = ["start", "stop", "restart", "update", "backup"]
    if action not in allowed_actions:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    # Run command asynchronously
    cmd = f"./{script} {action}"
    subprocess.Popen(cmd.split(), start_new_session=True)
    return {"message": f"Command '{action}' triggered for {script}"}

@app.websocket("/logs/{script}")
async def stream_logs(websocket: WebSocket, script: str):
    # Note: API Key validation for WebSockets usually happens via query params or subprotocols
    # For simplicity here, we assume the initial handshake or a token param
    await websocket.accept()
    try:
        # Assuming LGSM logs are in log/console/script-console.log
        log_path = f"log/console/{script}-console.log"
        if not os.path.exists(log_path):
            await websocket.send_text(f"Log file not found at {log_path}")
            await websocket.close()
            return

        process = await asyncio.create_subprocess_exec(
            "tail", "-f", log_path,
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
        await websocket.send_text(f"Error: {str(e)}")
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
