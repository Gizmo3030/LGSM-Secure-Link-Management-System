import os
import sqlite3
import jwt
import datetime
from fastapi import FastAPI, HTTPException, Depends, Header, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
import bcrypt
import asyncio

app = FastAPI(title="LGSM Hub Dashboard")

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-hub-key")
ALGORITHM = "HS256"

# Database setup
DB_PATH = os.getenv("DB_PATH", "hub.db")

def init_db():
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS spokes 
                 (id INTEGER PRIMARY KEY, name TEXT, ip TEXT, port INTEGER, api_key TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT DEFAULT 'user')''')
    
    # Check if role column exists (for migration)
    c.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in c.fetchall()]
    if 'role' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")

    # Create default user if not exists
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ("admin", hashed, "admin"))
    else:
        # Ensure default admin has admin role
        c.execute("UPDATE users SET role='admin' WHERE username='admin'")
    conn.commit()
    conn.close()

init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Spoke(BaseModel):
    name: str
    ip: str
    port: int
    api_key: str

class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"

class PasswordChange(BaseModel):
    new_password: str

# Auth Helpers
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

def admin_required(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

@app.post("/login")
async def login(req: LoginRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM users WHERE username=?", (req.username,))
    row = c.fetchone()
    conn.close()
    
    if row and bcrypt.checkpw(req.password.encode(), row[0].encode()):
        token = create_access_token({"sub": req.username, "role": row[1]})
        return {"access_token": token}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/users")
async def list_users(user=Depends(admin_required)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "role": r[2]} for r in rows]

@app.post("/users")
async def create_user(req: UserCreate, user=Depends(admin_required)):
    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                  (req.username, hashed, req.role or "user"))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    conn.close()
    return {"message": "User created"}

@app.delete("/users/{username}")
async def delete_user(username: str, user=Depends(admin_required)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete super-admin")
    if username == user["sub"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return {"message": "User deleted"}

@app.post("/users/{username}/reset-password")
async def reset_password(username: str, req: PasswordChange, user=Depends(admin_required)):
    hashed = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE username=?", (hashed, username))
    conn.commit()
    conn.close()
    return {"message": f"Password reset for {username}"}

@app.post("/users/{username}/role")
async def change_user_role(username: str, role: str, user=Depends(admin_required)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot change super-admin role")
    if role not in ["user", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    conn.commit()
    conn.close()
    return {"message": f"Role updated for {username}"}

@app.post("/change-password")
async def change_password(req: PasswordChange, user=Depends(get_current_user)):
    username = user["sub"]
    hashed = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE username=?", (hashed, username))
    conn.commit()
    conn.close()
    return {"message": "Password updated"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(heartbeat_monitor())

async def heartbeat_monitor():
    while True:
        await asyncio.sleep(60)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, ip, port, api_key FROM spokes")
        spokes = c.fetchall()
        conn.close()
        
        async with httpx.AsyncClient() as client:
            for sid, name, ip, port, api_key in spokes:
                try:
                    resp = await client.get(f"http://{ip}:{port}/status", headers={"X-API-KEY": api_key}, timeout=5)
                    if resp.status_code != 200:
                        await send_discord_alert(f"⚠️ Spoke Alert: {name} ({ip}) is unresponsive (HTTP {resp.status_code})")
                except Exception:
                    await send_discord_alert(f"🚨 Spoke CRITICAL: {name} ({ip}) is OFFLINE")

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    with open("interface.html", "r") as f:
        return f.read()

@app.get("/install/setup.sh")
async def download_setup(user=Depends(admin_required)):
    path = "static/spoke/setup.sh"
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Installer missing")

@app.get("/install/main.py")
async def download_agent(user=Depends(admin_required)):
    path = "static/spoke/main.py"
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Agent script missing")

@app.post("/spokes")
async def add_spoke(spoke: Spoke, user=Depends(admin_required)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO spokes (name, ip, port, api_key) VALUES (?, ?, ?, ?)",
              (spoke.name, spoke.ip, spoke.port, spoke.api_key))
    conn.commit()
    conn.close()
    return {"message": "Spoke added"}

@app.get("/spokes")
async def list_spokes(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, ip, port, api_key FROM spokes")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "ip": r[2], "port": r[3], "api_key": r[4]} for r in rows]

@app.get("/settings")
async def get_settings(user=Depends(admin_required)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

@app.post("/settings")
async def update_settings(settings: dict, user=Depends(admin_required)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for key, value in settings.items():
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
    return {"message": "Settings updated"}

async def send_discord_alert(message: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='discord_webhook'")
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        async with httpx.AsyncClient() as client:
            await client.post(row[0], json={"content": message})

@app.get("/proxy/status/{spoke_id}")
async def proxy_status(spoke_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ip, port, api_key FROM spokes WHERE id=?", (spoke_id,))
    spoke = c.fetchone()
    conn.close()
    
    if not spoke:
        raise HTTPException(status_code=404, detail="Spoke not found")
    
    ip, port, api_key = spoke
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"http://{ip}:{port}/status", headers={"X-API-KEY": api_key})
            return resp.json()
        except Exception as e:
            return {"status": "offline", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=49950)
