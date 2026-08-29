from fastapi import APIRouter, Depends, HTTPException, Body
from api.dependencies import get_memory, get_security_manager
from api.middleware.auth import get_current_user
import hashlib
import os
import hmac
from datetime import datetime
import logging

router = APIRouter(prefix="/api/auth", tags=["Auth"])
logger = logging.getLogger("JARVIS.API.Auth")

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{pw_hash.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        salt_hex, hash_hex = hashed.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def ensure_admin_user(memory):
    try:
        conn = memory.dbs.get_conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email         TEXT,
                phone_number  TEXT,
                role          TEXT DEFAULT 'user',
                created_at    TEXT NOT NULL
            )
        """)
        c.execute("SELECT COUNT(*) FROM users")
        count = c.fetchone()[0]
        if count == 0:
            logger.info("No users found in database. Auto-creating default 'admin' user...")
            api_key = os.environ.get("JARVIS_API_KEY", "admin123")
            email = os.environ.get("JARVIS_NOTIFY_EMAIL", "admin@localhost")
            pw_hash = hash_password(api_key)
            from datetime import timezone
            created_at = datetime.now(timezone.utc).isoformat()
            c.execute(
                "INSERT INTO users (username, password_hash, email, phone_number, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("admin", pw_hash, email, "", "admin", created_at)
            )
            conn.commit()
            logger.info("Default 'admin' user created successfully.")
    except Exception as e:
        logger.error(f"Failed to ensure admin user: {e}")

@router.post("/signup")
async def signup(body: dict = Body(...), memory = Depends(get_memory)):
    username = body.get("username")
    password = body.get("password")
    email = body.get("email", "")
    phone_number = body.get("phone_number", "")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
        
    username = username.strip().lower()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    conn = memory.dbs.get_conn()
    c = conn.cursor()
    
    # Check if username exists
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    if c.fetchone():
        raise HTTPException(status_code=400, detail="Username is already taken")
        
    pw_hash = hash_password(password)
    created_at = datetime.utcnow().isoformat()
    
    try:
        c.execute(
            "INSERT INTO users (username, password_hash, email, phone_number, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, pw_hash, email, phone_number, "user", created_at)
        )
        conn.commit()
        return {"status": "success", "message": "User registered successfully"}
    except Exception as e:
        logger.error(f"Registration database error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user account")

@router.post("/login")
async def login(body: dict = Body(...), memory = Depends(get_memory), security_mgr = Depends(get_security_manager)):
    username = body.get("username")
    password = body.get("password")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
        
    username = username.strip().lower()
    conn = memory.dbs.get_conn()
    c = conn.cursor()
    
    c.execute("SELECT password_hash, role, email, phone_number FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    
    if not row or not verify_password(password, row[0]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    role = row[1]
    email = row[2]
    phone = row[3]
    
    token = security_mgr.create_jwt(user_id=username, role=role)
    return {
        "token": token,
        "username": username,
        "role": role,
        "email": email,
        "phone_number": phone
    }

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), memory = Depends(get_memory)):
    username = current_user.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Authentication token missing user payload")
        
    conn = memory.dbs.get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, email, phone_number, role, created_at FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="User profile not found")
        
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "phone_number": row[3],
        "role": row[4],
        "created_at": row[5]
    }

@router.post("/update")
async def update_profile(body: dict = Body(...), current_user: dict = Depends(get_current_user), memory = Depends(get_memory)):
    username = current_user.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    email = body.get("email")
    phone_number = body.get("phone_number")
    password = body.get("password")
    old_password = body.get("old_password")
    
    conn = memory.dbs.get_conn()
    c = conn.cursor()
    
    # Query current record
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
        
    # If password is changing, verify old password
    update_pw = False
    new_pw_hash = None
    if password:
        if not old_password:
            raise HTTPException(status_code=400, detail="Old password is required to set a new password")
        if not verify_password(old_password, row[0]):
            raise HTTPException(status_code=400, detail="Incorrect old password")
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
        new_pw_hash = hash_password(password)
        update_pw = True
        
    try:
        if update_pw:
            c.execute(
                "UPDATE users SET email = ?, phone_number = ?, password_hash = ? WHERE username = ?",
                (email, phone_number, new_pw_hash, username)
            )
        else:
            c.execute(
                "UPDATE users SET email = ?, phone_number = ? WHERE username = ?",
                (email, phone_number, username)
            )
        conn.commit()
        return {"status": "success", "message": "Profile updated successfully"}
    except Exception as e:
        logger.error(f"Failed to update profile for {username}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save profile changes")
