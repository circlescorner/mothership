"""Security middleware and utilities for DevPlane.

Provides rate limiting, audit logging, input validation, and security headers.
Implements OWASP security guidelines and best practices.
"""

import logging
import time
import hashlib
import secrets
import re
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("devplane.security")

# ─── Rate Limiting ───────────────────────────────────────────────────────────

class RateLimiter:
    """Enhanced in-memory rate limiter with multiple tiers.
    
    Implements:
    - Per-IP rate limiting for general requests
    - Per-user rate limiting for authentication endpoints
    - Sliding window algorithm for accurate limiting
    - Separate limits for different endpoint categories
    
    WARNING: This is an in-memory rate limiter. When running with multiple
    workers (e.g., uvicorn --workers 4), each worker has its own rate limiter
    instance. For production multi-worker deployments, consider using Redis
    or another shared cache for distributed rate limiting.
    
    For single-worker deployments (default in Dockerfile), this works correctly.
    """
    
    def __init__(self, requests_per_minute: int = 60, burst_size: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self._requests: dict[str, list[float]] = {}
        self._auth_attempts: dict[str, list[float]] = {}  # For auth endpoints
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()
        
        # Auth-specific rate limits
        self.max_auth_attempts = 5  # Max login attempts per window
        self.auth_window = 300  # 5 minutes
        self.auth_lockout = 900  # 15 minutes lockout
        
        # Track locked out identifiers
        self._locked_out: dict[str, float] = {}
    
    def _cleanup_old_requests(self):
        """Remove entries older than 1 minute."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        # Clean general requests (keep last 60 seconds)
        cutoff = now - 60
        for ip in list(self._requests.keys()):
            self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]
            if not self._requests[ip]:
                del self._requests[ip]
        
        # Clean auth attempts (keep last 5 minutes)
        auth_cutoff = now - self.auth_window
        for ip in list(self._auth_attempts.keys()):
            self._auth_attempts[ip] = [t for t in self._auth_attempts[ip] if t > auth_cutoff]
            if not self._auth_attempts[ip]:
                del self._auth_attempts[ip]
        
        # Clean expired lockouts
        for ip in list(self._locked_out.keys()):
            if now > self._locked_out[ip]:
                del self._locked_out[ip]
        
        self._last_cleanup = now
    
    def is_allowed(self, identifier: str) -> bool:
        """Check if request is within rate limit."""
        self._cleanup_old_requests()
        
        # Check if locked out
        if identifier in self._locked_out:
            if time.time() < self._locked_out[identifier]:
                return False
            else:
                del self._locked_out[identifier]
        
        now = time.time()
        if identifier not in self._requests:
            self._requests[identifier] = []
        
        # Count requests in the last minute
        minute_ago = now - 60
        recent_requests = [t for t in self._requests[identifier] if t > minute_ago]
        
        if len(recent_requests) >= self.requests_per_minute:
            return False
        
        # Check burst
        if len([t for t in self._requests[identifier] if t > now - 1]) >= self.burst_size:
            return False
        
        self._requests[identifier].append(now)
        return True
    
    def check_auth_rate_limit(self, identifier: str) -> tuple[bool, int]:
        """Check rate limit for authentication endpoints.
        
        Returns: (is_allowed, remaining_attempts)
        """
        self._cleanup_old_requests()
        
        now = time.time()
        
        # Check if locked out
        if identifier in self._locked_out:
            if now < self._locked_out[identifier]:
                return False, 0
            else:
                del self._locked_out[identifier]
        
        if identifier not in self._auth_attempts:
            self._auth_attempts[identifier] = []
        
        # Count attempts in window
        window_start = now - self.auth_window
        attempts = [t for t in self._auth_attempts[identifier] if t > window_start]
        
        remaining = self.max_auth_attempts - len(attempts)
        
        if len(attempts) >= self.max_auth_attempts:
            # Lock out the identifier
            self._locked_out[identifier] = now + self.auth_lockout
            return False, 0
        
        self._auth_attempts[identifier].append(now)
        return True, max(0, remaining)
    
    def record_auth_attempt(self, identifier: str, success: bool):
        """Record an authentication attempt."""
        if success:
            # Clear attempts on successful login
            if identifier in self._auth_attempts:
                del self._auth_attempts[identifier]
        else:
            # Already recorded in check_auth_rate_limit
            pass
    
    def lock_out(self, identifier: str, duration_seconds: int = None):
        """Manually lock out an identifier."""
        if duration_seconds is None:
            duration_seconds = self.auth_lockout
        
        self._locked_out[identifier] = time.time() + duration_seconds

# Global rate limiter instance
_rate_limiter = RateLimiter()


# ─── Audit Logging ───────────────────────────────────────────────────────────

async def log_request(request: Request, response_status: int, user_id: Optional[str] = None):
    """Log API request for audit purposes."""
    from devplane.db import get_db
    
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    method = request.method
    
    # Hash IP for privacy
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO audit_logs (timestamp, method, path, ip_hash, user_id, status_code)
               VALUES (datetime('now'), ?, ?, ?, ?, ?)""",
            (method, path, ip_hash, user_id, response_status)
        )
        await db.commit()
    except Exception as e:
        # Audit logging failures are critical - log at ERROR level
        logger.error(f"CRITICAL: Audit logging failed: {e}")
    finally:
        await db.close()


# ─── Security Middleware ─────────────────────────────────────────────────────

class SecurityMiddleware(BaseHTTPMiddleware):
    """Middleware for security headers and request validation.
    
    Implements OWASP recommendations:
    - Rate limiting for brute force protection
    - Security headers (CSP, HSTS, X-Frame-Options, etc.)
    - Request validation
    - Audit logging
    """
    
    # Paths that require auth rate limiting
    AUTH_PATHS = ["/api/auth/login", "/api/auth/register", "/api/auth/mfa"]
    
    # Paths that skip rate limiting
    EXEMPT_PATHS = ["/api/health", "/api/health/detailed", "/health", "/api/docs", "/api/redoc", "/login", "/register"]
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        
        # Skip rate limiting for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            response = await call_next(request)
            return self._add_security_headers(request, response)
        
        # Check if this is an auth endpoint
        is_auth_endpoint = any(request.url.path.startswith(p) for p in self.AUTH_PATHS)
        
        if is_auth_endpoint:
            # Use stricter rate limiting for auth endpoints
            allowed, remaining = _rate_limiter.check_auth_rate_limit(client_ip)
            if not allowed:
                logger.warning(f"Auth rate limit exceeded for {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too many authentication attempts. Please try again later.",
                        "retry_after": 300
                    },
                    headers={"Retry-After": "300"}
                )
        else:
            # General rate limiting
            if not _rate_limiter.is_allowed(client_ip):
                logger.warning(f"Rate limit exceeded for {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded. Try again in a minute."}
                )
        
        # Process request
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"Request failed: {e}", exc_info=True)
            response = JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )
        
        # Add security headers
        response = self._add_security_headers(request, response)
        
        # Log request
        try:
            await log_request(request, response.status_code)
        except:
            pass
        
        return response
    
    def _add_security_headers(self, request: Request, response):
        """Add comprehensive security headers."""
        # Prevent content type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # XSS protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Referrer policy for privacy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions policy to restrict browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "vr=()"
        )
        
        # HSTS for HTTPS connections
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; "
                "includeSubDomains; "
                "preload"
            )
        
        # Content Security Policy
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' https: wss:; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Remove server identification
        response.headers["X-Powered-By"] = ""
        response.headers["Server"] = "DevPlane"
        
        return response


# ─── Input Validation ────────────────────────────────────────────────────────

def sanitize_input(text: str, max_length: int = 10000) -> str:
    """Sanitize user input to prevent injection attacks."""
    if not text:
        return ""
    
    # Trim whitespace
    text = text.strip()
    
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    
    # Remove null bytes
    text = text.replace("\x00", "")
    
    return text


def validate_api_key_format(key: str) -> bool:
    """Basic validation for API key format.
    
    Note: This is a lenient check that only validates basic structure.
    API keys from different providers have varying formats, so we avoid
    restrictive character whitelists that could reject valid keys.
    """
    if not key:
        return False
    if len(key) < 8:
        return False
    # Check for common API key patterns (alphanumeric with common special chars)
    # We allow most printable ASCII characters except control characters
    invalid_chars = set('\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f'
                       '\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f')
    return not any(c in invalid_chars for c in key[:100])


def validate_email(email: str) -> bool:
    """Validate email format."""
    if not email:
        return False
    # RFC 5322 simplified email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_username(username: str) -> bool:
    """Validate username format."""
    if not username:
        return False
    if len(username) < 3 or len(username) > 50:
        return False
    # Only allow alphanumeric, underscore, and hyphen
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', username))


def validate_phone(phone: str) -> bool:
    """Validate phone number format (E.164 format)."""
    if not phone:
        return False
    # E.164 format: + followed by 10-15 digits
    return bool(re.match(r'^\+[1-9]\d{9,14}$', phone))


def sanitize_html(text: str) -> str:
    """Sanitize HTML to prevent XSS attacks."""
    if not text:
        return ""
    
    # Remove script tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove event handlers
    text = re.sub(r'\s*on\w+\s*=\s*["\'].*?["\']', '', text, flags=re.IGNORECASE)
    
    # Remove javascript: URLs
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    
    # Remove data: URLs (can be used for XSS)
    text = re.sub(r'data:', '', text, flags=re.IGNORECASE)
    
    return text


def validate_url(url: str, allowed_schemes: list = None) -> bool:
    """Validate URL format and scheme."""
    if not url:
        return False
    
    if allowed_schemes is None:
        allowed_schemes = ['https', 'http']
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.scheme.lower() in allowed_schemes and parsed.netloc
    except Exception:
        return False


def check_sql_injection(text: str) -> bool:
    """Check for potential SQL injection patterns."""
    if not text:
        return False
    
    # Common SQL injection patterns
    patterns = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE|UNION)\b)",
        r"(--|#|/\*|\*/)",
        r"(\bOR\b.*\b=\b|\bAND\b.*\b=\b)",
        r"(';|\";|')",
    ]
    
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    
    return False


# ─── Database Schema Extension ───────────────────────────────────────────────

AUDIT_SCHEMA = """
-- Audit logging table
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    method TEXT,
    path TEXT,
    ip_hash TEXT,
    user_id TEXT,
    status_code INTEGER
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_path ON audit_logs(path);
"""


async def init_audit_tables():
    """Initialize audit logging tables."""
    from devplane.db import get_db
    db = await get_db()
    try:
        await db.executescript(AUDIT_SCHEMA)
        await db.commit()
        logger.info("Audit tables initialized")
    finally:
        await db.close()


# ─── API Key Generation ─────────────────────────────────────────────────────

def generate_api_key(prefix: str = "dp") -> str:
    """Generate a secure API key."""
    token = secrets.token_urlsafe(32)
    return f"{prefix}_{token}"


def generate_secret() -> str:
    """Generate a secure random secret."""
    return secrets.token_hex(32)
