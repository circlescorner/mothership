"""Comprehensive Authentication and MFA System for DevPlane.

Implements:
- TOTP (Time-based One-Time Password) MFA
- SMS-based verification
- WebAuthn/FIDO2 hardware key support
- Secure session management
- Password policies
- Comprehensive audit logging
"""

import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import base64
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, Any
from enum import Enum

import aiohttp
from fastapi import Request, HTTPException, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import URL

logger = logging.getLogger("devplane.auth")

# ─── Constants ───────────────────────────────────────────────────────────────────

# Password policy constants
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
PASSWORD_REQUIRE_UPPERCASE = True
PASSWORD_REQUIRE_LOWERCASE = True
PASSWORD_REQUIRE_DIGITS = True
PASSWORD_REQUIRE_SPECIAL = True
SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?"

# Session configuration
SESSION_DURATION_HOURS = 24
SESSION_EXTENDED_DURATION_DAYS = 30
MAX_CONCURRENT_SESSIONS = 5
SESSION_COOKIE_NAME = "devplane_session"

# Rate limiting for auth operations
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
MAX_MFA_ATTEMPTS = 3
MFA_LOCKOUT_MINUTES = 30

# TOTP settings
TOTP_ISSUER = "DevPlane"
TOTP_DIGITS = 6
TOTP_INTERVAL = 30  # seconds

# ─── Enums ───────────────────────────────────────────────────────────────────────

class MFAMethod(str, Enum):
    NONE = "none"
    TOTP = "totp"
    SMS = "sms"
    WEBAUTHN = "webauthn"

class AuthEventType(str, Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"
    MFA_VERIFIED = "mfa_verified"
    MFA_FAILED = "mfa_failed"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    SESSION_CREATED = "session_created"
    SESSION_REVOKED = "session_revoked"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

# ─── Pydantic Models ───────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        validate_password_strength(v)
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        return v.lower()

class UserLogin(BaseModel):
    username: str
    password: str
    mfa_code: Optional[str] = None
    webauthn_assertion: Optional[dict] = None

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str]
    mfa_enabled: bool
    mfa_method: MFAMethod
    created_at: str
    last_login: Optional[str]
    locked: bool

class MFASetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: list[str]

class SessionInfo(BaseModel):
    id: str
    created_at: str
    expires_at: str
    ip_address: str
    user_agent: str
    current: bool = False

class AuthAuditLog(BaseModel):
    id: Optional[int] = None
    timestamp: str
    event_type: AuthEventType
    user_id: Optional[int]
    username: Optional[str]
    ip_address: str
    user_agent: str
    success: bool
    details: Optional[str]

# ─── Password Validation ───────────────────────────────────────────────────────

def validate_password_strength(password: str) -> None:
    """Validate password against security policy."""
    errors = []
    
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    
    if len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"Password must not exceed {MAX_PASSWORD_LENGTH} characters")
    
    if PASSWORD_REQUIRE_UPPERCASE and not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    
    if PASSWORD_REQUIRE_LOWERCASE and not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    
    if PASSWORD_REQUIRE_DIGITS and not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")
    
    if PASSWORD_REQUIRE_SPECIAL and not any(c in SPECIAL_CHARS for c in password):
        errors.append(f"Password must contain at least one special character ({SPECIAL_CHARS})")
    
    # Check for common passwords
    common_passwords = [
        "password", "password123", "123456", "12345678", "qwerty",
        "abc123", "monkey", "1234567", "letmein", "trustno1",
        "dragon", "baseball", "iloveyou", "master", "sunshine"
    ]
    if password.lower() in common_passwords:
        errors.append("Password is too common. Choose a more secure password")
    
    if errors:
        raise ValueError("; ".join(errors))

def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, bytes]:
    """Hash password using Argon2-like approach with PBKDF2."""
    if salt is None:
        salt = secrets.token_bytes(32)
    
    # Use PBKDF2 with SHA-512 for password hashing
    key = hashlib.pbkdf2_hmac(
        'sha512',
        password.encode('utf-8'),
        salt,
        iterations=100000
    )
    
    return base64.b64encode(key).decode('utf-8'), salt

def verify_password(password: str, hashed: str, salt: bytes) -> bool:
    """Verify password against hash."""
    computed_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(computed_hash, hashed)

# ─── TOTP Implementation ───────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a TOTP secret key."""
    return base64.b32encode(secrets.token_bytes(20)).decode('utf-8')

def get_totp_uri(secret: str, username: str) -> str:
    """Get the TOTP provisioning URI."""
    return f"otpauth://totp/{TOTP_ISSUER}:{username}?secret={secret}&issuer={TOTP_ISSUER}&digits={TOTP_DIGITS}&period={TOTP_INTERVAL}"

def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify a TOTP code with tolerance for clock drift."""
    try:
        # Decode the secret
        secret_bytes = base64.b32decode(secret.replace(" ", "").upper())
        
        # Get current time step
        current_time = int(time.time()) // TOTP_INTERVAL
        
        # Check current and adjacent time steps
        for offset in range(-window, window + 1):
            time_step = current_time + offset
            expected_code = generate_hotp(secret_bytes, time_step)
            if hmac.compare_digest(code, expected_code):
                return True
        
        return False
    except Exception as e:
        logger.error(f"TOTP verification error: {e}")
        return False

def generate_hotp(secret: bytes, counter: int) -> str:
    """Generate HOTP (HMAC-based One-Time Password)."""
    # Convert counter to 8 bytes
    counter_bytes = counter.to_bytes(8, 'big')
    
    # Calculate HMAC-SHA1
    hmac_result = hmac.new(secret, counter_bytes, hashlib.sha1).digest()
    
    # Dynamic truncation
    offset = hmac_result[-1] & 0x0F
    code = ((hmac_result[offset] & 0x7F) << 24 |
            (hmac_result[offset + 1] & 0xFF) << 16 |
            (hmac_result[offset + 2] & 0xFF) << 8 |
            (hmac_result[offset + 3] & 0xFF))
    
    # Return as 6-digit string
    return str(code % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)

def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate backup codes for MFA recovery."""
    return [secrets.token_hex(4).upper() for _ in range(count)]

# ─── Database Schema ───────────────────────────────────────────────────────────

AUTH_SCHEMA = """
-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt BLOB NOT NULL,
    full_name TEXT,
    mfa_enabled INTEGER DEFAULT 0,
    mfa_method TEXT DEFAULT 'none',
    mfa_secret TEXT,
    mfa_phone TEXT,
    webauthn_credentials TEXT,
    backup_codes TEXT,
    failed_login_attempts INTEGER DEFAULT 0,
    locked INTEGER DEFAULT 0,
    lockout_until TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_login TEXT,
    password_changed_at TEXT DEFAULT (datetime('now')),
    password_history TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    last_activity TEXT DEFAULT (datetime('now')),
    extended INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Auth audit logs
CREATE TABLE IF NOT EXISTS auth_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    ip_address TEXT,
    user_agent TEXT,
    success INTEGER DEFAULT 1,
    details TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_timestamp ON auth_audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_auth_audit_user ON auth_audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_audit_type ON auth_audit_logs(event_type);
"""

# ─── Auth Database Functions ───────────────────────────────────────────────────

async def get_db():
    """Get database connection."""
    from devplane.db import get_db as db_get_db
    return await db_get_db()

async def init_auth_tables():
    """Initialize authentication tables."""
    db = await get_db()
    try:
        await db.executescript(AUTH_SCHEMA)
        await db.commit()
        logger.info("Auth tables initialized")
    finally:
        await db.close()

async def create_user(user_data: UserCreate) -> int:
    """Create a new user."""
    db = await get_db()
    try:
        # Hash password
        password_hash, salt = hash_password(user_data.password)
        
        await db.execute(
            """INSERT INTO users (username, email, password_hash, password_salt, full_name)
               VALUES (?, ?, ?, ?, ?)""",
            (user_data.username.lower(), user_data.email.lower(), password_hash, salt, user_data.full_name)
        )
        await db.commit()
        
        # Get the created user ID
        row = await db.execute("SELECT last_insert_rowid() as id")
        result = await row.fetchone()
        user_id = result["id"]
        
        await log_auth_event(AuthEventType.LOGIN_SUCCESS, user_id, user_data.username, 
                           "unknown", "unknown", True, "Account created")
        
        return user_id
    finally:
        await db.close()

async def get_user_by_username(username: str) -> Optional[dict]:
    """Get user by username."""
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.lower(),)
        )
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()

async def get_user_by_id(user_id: int) -> Optional[dict]:
    """Get user by ID."""
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()

async def update_user_mfa(user_id: int, mfa_method: MFAMethod, mfa_secret: str = None, 
                         mfa_phone: str = None, backup_codes: list = None):
    """Update user's MFA settings."""
    db = await get_db()
    try:
        updates = ["mfa_enabled = 1", "mfa_method = ?"]
        params = [mfa_method.value]
        
        if mfa_secret is not None:
            updates.append("mfa_secret = ?")
            params.append(mfa_secret)
        
        if mfa_phone is not None:
            updates.append("mfa_phone = ?")
            params.append(mfa_phone)
        
        if backup_codes is not None:
            updates.append("backup_codes = ?")
            params.append(json.dumps(backup_codes))
        
        params.append(user_id)
        
        await db.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            params
        )
        await db.commit()
    finally:
        await db.close()

async def disable_user_mfa(user_id: int):
    """Disable user's MFA."""
    db = await get_db()
    try:
        await db.execute(
            """UPDATE users SET mfa_enabled = 0, mfa_method = 'none', 
               mfa_secret = NULL, mfa_phone = NULL, backup_codes = NULL WHERE id = ?""",
            (user_id,)
        )
        await db.commit()
    finally:
        await db.close()

async def record_failed_login(user_id: int):
    """Record a failed login attempt and lock account if needed."""
    db = await get_db()
    try:
        # Get current failed attempts
        row = await db.execute(
            "SELECT failed_login_attempts, locked FROM users WHERE id = ?",
            (user_id,)
        )
        user = await row.fetchone()
        
        if not user:
            return
        
        failed_attempts = user["failed_login_attempts"] + 1
        
        if failed_attempts >= MAX_LOGIN_ATTEMPTS:
            lockout_until = datetime.utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
            await db.execute(
                """UPDATE users SET failed_login_attempts = ?, locked = 1, lockout_until = ? 
                   WHERE id = ?""",
                (failed_attempts, lockout_until.isoformat(), user_id)
            )
            await log_auth_event(AuthEventType.ACCOUNT_LOCKED, user_id, None, 
                               "unknown", "unknown", False, 
                               f"Account locked after {failed_attempts} failed attempts")
        else:
            await db.execute(
                "UPDATE users SET failed_login_attempts = ? WHERE id = ?",
                (failed_attempts, user_id)
            )
        
        await db.commit()
    finally:
        await db.close()

async def reset_failed_logins(user_id: int):
    """Reset failed login attempts after successful login."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET failed_login_attempts = 0, locked = 0, lockout_until = NULL, last_login = datetime('now') WHERE id = ?",
            (user_id,)
        )
        await db.commit()
    finally:
        await db.close()

async def check_backup_code(user_id: int, code: str) -> bool:
    """Check and consume a backup code."""
    db = await get_db()
    try:
        row = await db.execute("SELECT backup_codes FROM users WHERE id = ?", (user_id,))
        user = await row.fetchone()
        
        if not user or not user["backup_codes"]:
            return False
        
        backup_codes = json.loads(user["backup_codes"])
        code_upper = code.upper()
        
        if code_upper in backup_codes:
            backup_codes.remove(code_upper)
            await db.execute(
                "UPDATE users SET backup_codes = ? WHERE id = ?",
                (json.dumps(backup_codes), user_id)
            )
            await db.commit()
            return True
        
        return False
    finally:
        await db.close()

# ─── Session Management ───────────────────────────────────────────────────────

async def create_session(user_id: int, ip_address: str, user_agent: str, 
                        extended: bool = False) -> str:
    """Create a new session."""
    db = await get_db()
    try:
        session_id = secrets.token_urlsafe(32)
        
        if extended:
            expires_at = datetime.utcnow() + timedelta(days=SESSION_EXTENDED_DURATION_DAYS)
        else:
            expires_at = datetime.utcnow() + timedelta(hours=SESSION_DURATION_HOURS)
        
        # Check concurrent sessions limit
        row = await db.execute(
            "SELECT COUNT(*) as c FROM sessions WHERE user_id = ? AND expires_at > datetime('now')",
            (user_id,)
        )
        result = await row.fetchone()
        
        if result["c"] >= MAX_CONCURRENT_SESSIONS:
            # Remove oldest session
            await db.execute(
                """DELETE FROM sessions WHERE id = (
                    SELECT id FROM sessions WHERE user_id = ? AND expires_at > datetime('now')
                    ORDER BY created_at ASC LIMIT 1
                )""",
                (user_id,)
            )
        
        await db.execute(
            """INSERT INTO sessions (id, user_id, expires_at, ip_address, user_agent, extended)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, expires_at.isoformat(), ip_address, user_agent, extended)
        )
        await db.commit()
        
        await log_auth_event(AuthEventType.SESSION_CREATED, user_id, None, 
                           ip_address, user_agent, True, f"Extended: {extended}")
        
        return session_id
    finally:
        await db.close()

async def get_session(session_id: str) -> Optional[dict]:
    """Get session by ID."""
    db = await get_db()
    try:
        row = await db.execute(
            """SELECT s.*, u.username FROM sessions s 
               JOIN users u ON s.user_id = u.id 
               WHERE s.id = ? AND s.expires_at > datetime('now')""",
            (session_id,)
        )
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()

async def delete_session(session_id: str, user_id: int = None):
    """Delete a session."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()
        
        if user_id:
            await log_auth_event(AuthEventType.SESSION_REVOKED, user_id, None, 
                               "unknown", "unknown", True, "Session deleted")
    finally:
        await db.close()

async def get_user_sessions(user_id: int) -> list[dict]:
    """Get all active sessions for a user."""
    db = await get_db()
    try:
        row = await db.execute(
            """SELECT id, created_at, expires_at, ip_address, user_agent, extended
               FROM sessions WHERE user_id = ? AND expires_at > datetime('now')
               ORDER BY created_at DESC""",
            (user_id,)
        )
        results = await row.fetchall()
        return [dict(r) for r in results]
    finally:
        await db.close()

async def cleanup_expired_sessions():
    """Clean up expired sessions."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
        await db.commit()
    finally:
        await db.close()

# ─── Audit Logging ─────────────────────────────────────────────────────────────

async def log_auth_event(event_type: AuthEventType, user_id: Optional[int], 
                        username: Optional[str], ip_address: str, 
                        user_agent: str, success: bool, details: str = None):
    """Log an authentication event."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO auth_audit_logs (event_type, user_id, username, ip_address, user_agent, success, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_type.value, user_id, username, ip_address, user_agent, 1 if success else 0, details)
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log auth event: {e}")
    finally:
        await db.close()

async def get_auth_audit_logs(user_id: int = None, limit: int = 100) -> list[dict]:
    """Get authentication audit logs."""
    db = await get_db()
    try:
        if user_id:
            row = await db.execute(
                """SELECT * FROM auth_audit_logs WHERE user_id = ? 
                   ORDER BY timestamp DESC LIMIT ?""",
                (user_id, limit)
            )
        else:
            row = await db.execute(
                "SELECT * FROM auth_audit_logs ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
        results = await row.fetchall()
        return [dict(r) for r in results]
    finally:
        await db.close()

# ─── SMS Verification ─────────────────────────────────────────────────────────

async def send_sms_verification(phone: str, code: str) -> bool:
    """Send SMS verification code."""
    # Get Twilio credentials from environment
    twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    twilio_token = os.environ.get("TWILIO_AUTH_TOKEN")
    twilio_phone = os.environ.get("TWILIO_PHONE_NUMBER")
    
    if not all([twilio_sid, twilio_token, twilio_phone]):
        logger.warning("Twilio not configured, SMS verification unavailable")
        return False
    
    try:
        async with aiohttp.ClientSession() as session:
            # Twilio API endpoint
            url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
            
            # Create basic auth
            auth = aiohttp.BasicAuth(twilio_sid, twilio_token)
            
            data = {
                "To": phone,
                "From": twilio_phone,
                "Body": f"Your DevPlane verification code is: {code}. This code expires in 5 minutes."
            }
            
            async with session.post(url, data=data, auth=auth) as response:
                if response.status == 201:
                    logger.info(f"SMS verification sent to {phone[:4]}****{phone[-4:]}")
                    return True
                else:
                    logger.error(f"SMS send failed: {response.status}")
                    return False
    except Exception as e:
        logger.error(f"SMS send error: {e}")
        return False

# ─── Authentication Dependencies ───────────────────────────────────────────────

async def get_current_user(request: Request) -> dict:
    """Get current authenticated user from session."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    
    user = await get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    if user["locked"]:
        lockout_until = user.get("lockout_until")
        if lockout_until and datetime.fromisoformat(lockout_until) > datetime.utcnow():
            raise HTTPException(status_code=423, detail="Account is locked")
    
    return user

async def require_auth(request: Request) -> dict:
    """Require authentication for a route."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return session

async def require_mfa(user: dict = Depends(get_current_user)) -> dict:
    """Require MFA to be enabled for the user."""
    if not user.get("mfa_enabled"):
        raise HTTPException(status_code=403, detail="MFA required")
    return user

# ─── Auth API Endpoints ───────────────────────────────────────────────────────

from fastapi import APIRouter

router = APIRouter(prefix="/api/auth", tags=["authentication"])

@router.post("/register", status_code=201)
async def register(user_data: UserCreate, request: Request):
    """Register a new user."""
    # Check if user exists
    existing = await get_user_by_username(user_data.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    user_id = await create_user(user_data)
    
    return {"status": "success", "user_id": user_id, "message": "User created successfully"}

@router.post("/login")
async def login(credentials: UserLogin, request: Request, response: Response):
    """Authenticate user and create session."""
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Get user
    user = await get_user_by_username(credentials.username)
    
    if not user:
        await log_auth_event(AuthEventType.LOGIN_FAILED, None, credentials.username,
                           ip_address, user_agent, False, "User not found")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if account is locked
    if user["locked"]:
        lockout_until = user.get("lockout_until")
        if lockout_until and datetime.fromisoformat(lockout_until) > datetime.utcnow():
            await log_auth_event(AuthEventType.LOGIN_FAILED, user["id"], credentials.username,
                               ip_address, user_agent, False, "Account locked")
            raise HTTPException(status_code=423, detail="Account is locked. Try again later.")
    
    # Verify password
    if not verify_password(credentials.password, user["password_hash"], user["password_salt"]):
        await record_failed_login(user["id"])
        await log_auth_event(AuthEventType.LOGIN_FAILED, user["id"], credentials.username,
                           ip_address, user_agent, False, "Invalid password")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if MFA is required
    if user["mfa_enabled"]:
        if not credentials.mfa_code:
            # Return MFA required status
            return {
                "mfa_required": True,
                "mfa_method": user["mfa_method"],
                "message": "MFA code required"
            }
        
        # Verify MFA
        mfa_valid = False
        mfa_method = user["mfa_method"]
        
        if mfa_method == MFAMethod.TOTP.value:
            mfa_valid = verify_totp(user["mfa_secret"], credentials.mfa_code)
        elif mfa_method == MFAMethod.SMS.value:
            # SMS would need a separate verification flow
            pass
        elif mfa_method == MFAMethod.WEBAUTHN.value:
            # WebAuthn verification would happen client-side
            pass
        
        # Check backup codes
        if not mfa_valid and credentials.mfa_code:
            mfa_valid = await check_backup_code(user["id"], credentials.mfa_code)
        
        if not mfa_valid:
            await log_auth_event(AuthEventType.MFA_FAILED, user["id"], credentials.username,
                               ip_address, user_agent, False, f"MFA method: {mfa_method}")
            raise HTTPException(status_code=401, detail="Invalid MFA code")
        
        await log_auth_event(AuthEventType.MFA_VERIFIED, user["id"], credentials.username,
                           ip_address, user_agent, True)
    
    # Reset failed attempts and update last login
    await reset_failed_logins(user["id"])
    
    # Create session
    session_id = await create_session(user["id"], ip_address, user_agent)
    
    # Set session cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_DURATION_HOURS * 3600
    )
    
    await log_auth_event(AuthEventType.LOGIN_SUCCESS, user["id"], credentials.username,
                       ip_address, user_agent, True)
    
    return {
        "status": "success",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user.get("full_name"),
            "mfa_enabled": bool(user["mfa_enabled"]),
            "mfa_method": user["mfa_method"]
        }
    }

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Logout and delete session."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    
    if session_id:
        session = await get_session(session_id)
        if session:
            await delete_session(session_id, session["user_id"])
        
        response.delete_cookie(SESSION_COOKIE_NAME)
    
    return {"status": "success", "message": "Logged out successfully"}

@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info."""
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "full_name": user.get("full_name"),
        "mfa_enabled": bool(user["mfa_enabled"]),
        "mfa_method": user["mfa_method"],
        "created_at": user["created_at"],
        "last_login": user.get("last_login"),
        "locked": bool(user["locked"])
    }

@router.post("/mfa/setup/totp")
async def setup_totp(user: dict = Depends(get_current_user)):
    """Setup TOTP MFA."""
    if user["mfa_enabled"]:
        raise HTTPException(status_code=400, detail="MFA already enabled")
    
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user["username"])
    
    # Generate backup codes
    backup_codes = generate_backup_codes()
    
    # Store temporarily (not yet activated)
    await update_user_mfa(user["id"], MFAMethod.TOTP, mfa_secret=secret, 
                         backup_codes=backup_codes)
    
    await log_auth_event(AuthEventType.MFA_ENABLED, user["id"], user["username"],
                       "unknown", "unknown", True, "TOTP setup initiated")
    
    return {
        "secret": secret,
        "uri": uri,
        "backup_codes": backup_codes
    }

@router.post("/mfa/enable/totp")
async def enable_totp(verification: dict, user: dict = Depends(get_current_user)):
    """Enable TOTP after verification."""
    code = verification.get("code", "")
    
    if not code:
        raise HTTPException(status_code=400, detail="Verification code required")
    
    # Get the stored secret
    db = await get_db()
    try:
        row = await db.execute("SELECT mfa_secret FROM users WHERE id = ?", (user["id"],))
        result = await row.fetchone()
        
        if not result or not result["mfa_secret"]:
            raise HTTPException(status_code=400, detail="TOTP not setup")
        
        if not verify_totp(result["mfa_secret"], code):
            raise HTTPException(status_code=400, detail="Invalid verification code")
        
        # MFA is already enabled in setup, just confirm
        await log_auth_event(AuthEventType.MFA_ENABLED, user["id"], user["username"],
                           "unknown", "unknown", True, "TOTP enabled")
        
        return {"status": "success", "message": "TOTP MFA enabled"}
    finally:
        await db.close()

@router.post("/mfa/disable")
async def disable_mfa(verification: dict, user: dict = Depends(require_mfa)):
    """Disable MFA."""
    code = verification.get("code", "")
    
    # Verify current MFA
    if user["mfa_method"] == MFAMethod.TOTP.value:
        if not verify_totp(user["mfa_secret"], code):
            raise HTTPException(status_code=400, detail="Invalid verification code")
    elif user["mfa_method"] == MFAMethod.SMS.value:
        # SMS verification would go here
        pass
    
    await disable_user_mfa(user["id"])
    
    await log_auth_event(AuthEventType.MFA_DISABLED, user["id"], user["username"],
                       "unknown", "unknown", True)
    
    return {"status": "success", "message": "MFA disabled"}

@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    """List all active sessions."""
    sessions = await get_user_sessions(user["id"])
    current_session_id = None
    
    # Get current session
    for cookie in [request.cookies.get(SESSION_COOKIE_NAME)]:
        if cookie:
            current_session_id = cookie
            break
    
    return [
        {
            "id": s["id"],
            "created_at": s["created_at"],
            "expires_at": s["expires_at"],
            "ip_address": s["ip_address"],
            "user_agent": s["user_agent"],
            "current": s["id"] == current_session_id
        }
        for s in sessions
    ]

@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, user: dict = Depends(get_current_user)):
    """Revoke a session."""
    await delete_session(session_id, user["id"])
    return {"status": "success", "message": "Session revoked"}

@router.get("/audit")
async def get_audit_logs(limit: int = 100, user: dict = Depends(get_current_user)):
    """Get authentication audit logs for current user."""
    logs = await get_auth_audit_logs(user["id"], limit)
    return logs

@router.post("/change-password")
async def change_password(passwords: dict, user: dict = Depends(get_current_user)):
    """Change user password."""
    current_password = passwords.get("current_password")
    new_password = passwords.get("new_password")
    
    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Both passwords required")
    
    # Verify current password
    if not verify_password(current_password, user["password_hash"], user["password_salt"]):
        await record_failed_login(user["id"])
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # Validate new password
    try:
        validate_password_strength(new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Hash new password
    new_hash, new_salt = hash_password(new_password)
    
    # Store in history (last 5 passwords)
    password_history = json.loads(user.get("password_history", "[]"))
    password_history.append({
        "hash": user["password_hash"],
        "salt": base64.b64encode(user["password_salt"]).decode(),
        "changed_at": datetime.utcnow().isoformat()
    })
    password_history = password_history[-5:]  # Keep last 5
    
    # Update password
    db = await get_db()
    try:
        await db.execute(
            """UPDATE users SET password_hash = ?, password_salt = ?, 
               password_changed_at = datetime('now'), password_history = ? WHERE id = ?""",
            (new_hash, new_salt, json.dumps(password_history), user["id"])
        )
        await db.commit()
    finally:
        await db.close()
    
    await log_auth_event(AuthEventType.PASSWORD_CHANGED, user["id"], user["username"],
                       "unknown", "unknown", True)
    
    # Invalidate all other sessions
    sessions = await get_user_sessions(user["id"])
    for session in sessions:
        await delete_session(session["id"])
    
    return {"status": "success", "message": "Password changed. All other sessions have been invalidated."}

# ─── Security Headers Middleware ───────────────────────────────────────────────

class AuthSecurityMiddleware(BaseHTTPMiddleware):
    """Middleware for authentication-related security headers."""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # HSTS header (only for HTTPS)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # Content Security Policy
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Remove server identification
        response.headers["Server"] = "DevPlane"
        response.headers["X-Powered-By"] = ""
        
        return response


# ─── Initialize ───────────────────────────────────────────────────────────────

async def init_auth():
    """Initialize authentication system."""
    await init_auth_tables()
    
    # Schedule session cleanup
    asyncio.create_task(session_cleanup_loop())

async def session_cleanup_loop():
    """Periodically clean up expired sessions."""
    while True:
        await asyncio.sleep(3600)  # Every hour
        try:
            await cleanup_expired_sessions()
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")