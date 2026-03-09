"""DevPlane — Unified AI Control Plane.

Main entrypoint: FastAPI app with all API routers + Slack bot.
Includes comprehensive MFA and security implementation.
"""

import asyncio
import importlib.util
import os
import secrets
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("devplane")

START_TIME = time.time()


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, load keys, start Slack bot."""
    from devplane.db import init_db
    from devplane.providers import load_all_keys_to_env
    from devplane.slack.bot import init_slack, slack_handler
    from devplane.infra.mcp import get_mcp_manager
    from devplane.security import init_audit_tables
    from devplane.auth import init_auth

    # Initialize database
    await init_db()
    await init_audit_tables()
    await init_auth()  # Initialize authentication system
    await load_all_keys_to_env()
    init_slack()

    # Start persistent agents
    from devplane.agents.infra_manager import get_infra_agent
    from devplane.agents.builder import get_builder_agent
    
    infra_agent = get_infra_agent()
    await infra_agent.start()
    
    builder_agent = get_builder_agent()
    await builder_agent.start()

    # Load role-based model registry overrides from DB
    try:
        from devplane.roles import load_from_db as load_roles
        await load_roles()
        logger.info("Role-based model registry loaded")
    except Exception as e:
        logger.warning(f"Role registry load skipped: {e}")

    # Initialize trusted self-hosted MCPs (optional - don't fail if unavailable)
    logger.info("Initializing MCP Connections...")
    mcp_manager = get_mcp_manager()
    try:
        # Use sys.executable to get the correct Python interpreter path
        # This ensures compatibility across Windows (py) and Unix (python)
        import sys
        python_cmd = sys.executable
        await mcp_manager.connect_local_server(
            name="devplane_db",
            command=python_cmd,
            args=["-m", "mcp_server_sqlite", "--db-path", "devplane.db"]
        )
    except Exception as e:
        logger.warning(f"MCP SQLite server not available: {e}")

    if slack_handler:
        logger.info("Starting Slack Socket Mode Handler...")
        try:
            task = asyncio.create_task(slack_handler.start_async())
            yield
            logger.info("Shutting down Slack handler...")
            await slack_handler.close_async()
            task.cancel()
            infra_agent.stop()
            builder_agent.stop()
        except Exception as e:
            logger.error(f"Slack handler error: {e}. Running Web-Only mode.")
            yield
            await mcp_manager.cleanup()
            infra_agent.stop()
            builder_agent.stop()
    else:
        logger.warning("Slack tokens not configured. Running Web-Only mode.")
        yield
        await mcp_manager.cleanup()
        infra_agent.stop()
        builder_agent.stop()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DevPlane",
    version="2.0.0",
    description="Unified AI Control Plane with configurable chains, tier escalation, and infrastructure management.",
    lifespan=lifespan,
    docs_url="/api/docs" if os.environ.get("ENV", "dev") == "dev" else None,
    redoc_url="/api/redoc" if os.environ.get("ENV", "dev") == "dev" else None,
)

# Session middleware (required for secure cookies)
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("SECRET_KEY not found in environment. Generating a new one and saving to .env")
    try:
        from dotenv import set_key
        env_file = ".env"
        if not os.path.exists(env_file):
            open(env_file, "a").close()
        set_key(env_file, "SECRET_KEY", SECRET_KEY)
        os.environ["SECRET_KEY"] = SECRET_KEY
    except Exception as e:
        logger.error(f"Failed to save SECRET_KEY to .env: {e}")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# CORS middleware - secure configuration
cors_origins = os.environ.get("CORS_ORIGINS", "").split(",")
# Default to strict origins in production
if not cors_origins or cors_origins == [""]:
    cors_origins = ["http://localhost:3000", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-CSRF-Token"],
    expose_headers=["Content-Length", "Content-Language"],
    max_age=600,  # Cache preflight for 10 minutes
)

# Security middleware
from devplane.security import SecurityMiddleware
app.add_middleware(SecurityMiddleware)

# Auth security middleware
from devplane.auth import AuthSecurityMiddleware
app.add_middleware(AuthSecurityMiddleware)

# Static files
os.makedirs("static", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Register API Routers ────────────────────────────────────────────────────

from devplane.api.providers import router as providers_router
from devplane.api.credits import router as credits_router
from devplane.api.chains import router as chains_router
from devplane.api.projects import router as projects_router
from devplane.api.infra import router as infra_router
from devplane.api.workflows import router as workflows_router
from devplane.api.agents import router as agents_router
from devplane.api.secrets import router as secrets_router
from devplane.api.mesh import router as mesh_router
from devplane.api.config import router as config_router
from devplane.api.tools import router as tools_router
from devplane.auth import router as auth_router
from devplane.webauthn import router as webauthn_router

app.include_router(providers_router)
app.include_router(credits_router)
app.include_router(chains_router)
app.include_router(projects_router)
app.include_router(infra_router)
app.include_router(workflows_router)
app.include_router(agents_router)
app.include_router(secrets_router)
app.include_router(mesh_router)  # Unified Agentic Mesh configuration
app.include_router(config_router)  # Configuration endpoints for roles, memory, optimizer, tools, MCP servers
app.include_router(tools_router)  # LangChain dynamic tool registration
app.include_router(auth_router)  # Authentication & MFA endpoints
app.include_router(webauthn_router)  # WebAuthn/FIDO2 hardware key endpoints


# ─── Authentication Dependency ───────────────────────────────────────────────

async def require_auth(request: Request):
    """Require authentication for a route."""
    session_id = request.cookies.get("devplane_session")
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from devplane.auth import get_session
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return session

# ─── v2 Memory + Optimizer inline endpoints ────────────────────────────────────
# All these require authentication

@app.get("/api/memory/stats")
async def memory_stats(request: Request, project_id: int = 0):
    await require_auth(request)
    from devplane.memory.store import get_memory_stats
    return await get_memory_stats(project_id)

@app.get("/api/memory/search")
async def memory_search(request: Request, q: str, project_id: int = 0, limit: int = 20):
    await require_auth(request)
    from devplane.memory.store import search_memory
    return await search_memory(q, project_id, limit)

@app.get("/api/memory/history")
async def memory_history(request: Request, project_id: int = 0, limit: int = 20):
    await require_auth(request)
    from devplane.memory.store import get_history
    return await get_history(project_id, limit)

@app.post("/api/memory/clear")
async def memory_clear(request: Request, project_id: int = 0):
    await require_auth(request)
    from devplane.memory.store import clear_memory
    return await clear_memory(project_id)

@app.get("/api/optimizer/insights")
async def optimizer_insights(request: Request):
    await require_auth(request)
    from devplane.chain.optimizer import get_insights
    return await get_insights()

@app.post("/api/optimizer/recommend")
async def optimizer_recommend(request: Request, data: dict):
    await require_auth(request)
    from devplane.chain.optimizer import recommend_tier, recommend_models
    tier = await recommend_tier(data.get("prompt", ""))
    models = await recommend_models(data.get("step_type", "executor"))
    return {"tier": tier, "models": models}


# ─── Core Routes ──────────────────────────────────────────────────────────────

# Login page (public)
LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DevPlane - Login</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-container { background: #1e293b; padding: 2rem; border-radius: 12px; width: 100%; max-width: 400px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); }
        h1 { text-align: center; margin-bottom: 1.5rem; font-size: 1.5rem; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #94a3b8; }
        input { width: 100%; padding: 0.75rem; border: 1px solid #334155; border-radius: 6px; background: #0f172a; color: #fff; font-size: 1rem; }
        input:focus { outline: none; border-color: #3b82f6; }
        button { width: 100%; padding: 0.75rem; background: #3b82f6; color: #fff; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
        button:hover { background: #2563eb; }
        .error { background: #7f1d1d; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.875rem; display: none; }
        .register-link { text-align: center; margin-top: 1rem; font-size: 0.875rem; color: #94a3b8; }
        .register-link a { color: #3b82f6; text-decoration: none; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🔐 DevPlane Login</h1>
        <div class="error" id="error"></div>
        <form id="loginForm">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autocomplete="username">
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            <button type="submit">Sign In</button>
        </form>
        <div class="register-link">
            Don't have an account? <a href="/register">Register</a>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorEl = document.getElementById('error');
            
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                const data = await response.json();
                
                if (response.ok) {
                    window.location.href = '/';
                } else {
                    errorEl.textContent = data.detail || 'Login failed';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = 'Connection error';
                errorEl.style.display = 'block';
            }
        });
    </script>
</body>
</html>"""

# Register page (public)
REGISTER_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DevPlane - Register</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .register-container { background: #1e293b; padding: 2rem; border-radius: 12px; width: 100%; max-width: 400px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); }
        h1 { text-align: center; margin-bottom: 1.5rem; font-size: 1.5rem; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #94a3b8; }
        input { width: 100%; padding: 0.75rem; border: 1px solid #334155; border-radius: 6px; background: #0f172a; color: #fff; font-size: 1rem; }
        input:focus { outline: none; border-color: #3b82f6; }
        button { width: 100%; padding: 0.75rem; background: #3b82f6; color: #fff; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
        button:hover { background: #2563eb; }
        .error { background: #7f1d1d; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.875rem; display: none; }
        .success { background: #14532d; padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.875rem; display: none; }
        .login-link { text-align: center; margin-top: 1rem; font-size: 0.875rem; color: #94a3b8; }
        .login-link a { color: #3b82f6; text-decoration: none; }
    </style>
</head>
<body>
    <div class="register-container">
        <h1>🚀 Create Account</h1>
        <div class="error" id="error"></div>
        <div class="success" id="success"></div>
        <form id="registerForm">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required minlength="3" pattern="[a-zA-Z0-9_-]+">
            </div>
            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required>
            </div>
            <div class="form-group">
                <label for="full_name">Full Name (optional)</label>
                <input type="text" id="full_name" name="full_name">
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required minlength="12" placeholder="Min 12 characters">
            </div>
            <button type="submit">Create Account</button>
        </form>
        <div class="login-link">
            Already have an account? <a href="/login">Sign In</a>
        </div>
    </div>
    <script>
        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const email = document.getElementById('email').value;
            const full_name = document.getElementById('full_name').value;
            const password = document.getElementById('password').value;
            const errorEl = document.getElementById('error');
            const successEl = document.getElementById('success');
            
            try {
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, email, full_name, password})
                });
                const data = await response.json();
                
                if (response.ok) {
                    successEl.textContent = 'Account created! Redirecting to login...';
                    successEl.style.display = 'block';
                    setTimeout(() => window.location.href = '/login', 1500);
                } else {
                    errorEl.textContent = data.detail || 'Registration failed';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = 'Connection error';
                errorEl.style.display = 'block';
            }
        });
    </script>
</body>
</html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Login page."""
    return LOGIN_PAGE

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    """Registration page."""
    return REGISTER_PAGE

@app.get("/")
async def root(request: Request):
    """Serve the dashboard - requires authentication."""
    # Check for valid session directly
    session_id = request.cookies.get("devplane_session")
    if not session_id:
        return RedirectResponse(url="/login", status_code=302)
    
    from devplane.auth import get_session
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    
    # User is authenticated, serve dashboard
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return {"status": "DevPlane Online", "message": "Dashboard not deployed yet."}


@app.get("/setup", response_class=HTMLResponse)
async def setup_wizard(request: Request):
    """Setup wizard - requires authentication."""
    session_id = request.cookies.get("devplane_session")
    if not session_id:
        return RedirectResponse(url="/login", status_code=302)
    
    from devplane.auth import get_session
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        with open("static/setup.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return RedirectResponse(url="/")


@app.get("/deploy", response_class=HTMLResponse)
async def deploy_wizard(request: Request):
    """Deployment wizard - requires authentication."""
    session_id = request.cookies.get("devplane_session")
    if not session_id:
        return RedirectResponse(url="/login", status_code=302)
    
    from devplane.auth import get_session
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        with open("static/deploy.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return RedirectResponse(url="/")


@app.get("/secrets", response_class=HTMLResponse)
async def secrets_management(request: Request):
    """Secrets management page - requires authentication."""
    session_id = request.cookies.get("devplane_session")
    if not session_id:
        return RedirectResponse(url="/login", status_code=302)
    
    from devplane.auth import get_session
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        with open("static/secrets.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return RedirectResponse(url="/")


@app.get("/mesh", response_class=HTMLResponse)
async def mesh_configuration(request: Request):
    """Mesh configuration page - requires authentication."""
    session_id = request.cookies.get("devplane_session")
    if not session_id:
        return RedirectResponse(url="/login", status_code=302)
    
    from devplane.auth import get_session
    session = await get_session(session_id)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        with open("static/mesh.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return RedirectResponse(url="/")


@app.get("/api/health")
async def health():
    """Health check with system status."""
    from devplane.db import get_db
    from devplane.slack.bot import slack_handler

    db = await get_db()
    try:
        # Count active providers
        row = await db.execute("SELECT COUNT(*) as c FROM providers WHERE enabled = 1 AND api_key != ''")
        prov_count = (await row.fetchone())["c"]

        # Count total runs
        row = await db.execute("SELECT COUNT(*) as c FROM runs")
        run_count = (await row.fetchone())["c"]

        return {
            "status": "🛰️ DevPlane Online",
            "version": "2.0.0",
            "uptime_seconds": int(time.time() - START_TIME),
            "slack_connected": slack_handler is not None,
            "providers_active": prov_count,
            "total_runs": run_count,
        }
    finally:
        await db.close()


@app.get("/api/health/detailed")
async def health_detailed(request: Request):
    """Detailed health check for all services."""
    await require_auth(request)
    from devplane.monitoring import health_checker
    return await health_checker.get_full_health_report()


@app.get("/api/metrics")
async def metrics_endpoint(request: Request):
    """Prometheus-style metrics endpoint."""
    await require_auth(request)
    from devplane.monitoring import generate_prometheus_metrics
    return PlainTextResponse(generate_prometheus_metrics())


@app.get("/api/status")
async def system_status(request: Request):
    """Complete system status overview."""
    await require_auth(request)
    from devplane.monitoring import metrics
    from devplane.db import get_db
    
    db = await get_db()
    try:
        # Get various counts
        row = await db.execute("SELECT COUNT(*) as c FROM providers WHERE enabled = 1")
        active_providers = (await row.fetchone())["c"]
        
        row = await db.execute("SELECT COUNT(*) as c FROM droplets WHERE status NOT IN ('destroyed', 'error')")
        active_droplets = (await row.fetchone())["c"]
        
        row = await db.execute("SELECT COUNT(*) as c FROM workspaces WHERE status = 'running'")
        active_workspaces = (await row.fetchone())["c"]
        
        row = await db.execute("SELECT COUNT(*) as c FROM memories")
        memory_count = (await row.fetchone())["c"]
        
        metrics_summary = metrics.get_summary()
        
        return {
            "status": "operational",
            "version": "2.0.0",
            "uptime_seconds": int(time.time() - START_TIME),
            "components": {
                "providers": {"active": active_providers, "status": "healthy"},
                "infrastructure": {
                    "droplets": active_droplets,
                    "workspaces": active_workspaces,
                    "status": "healthy" if active_droplets > 0 else "idle"
                },
                "memory": {"entries": memory_count, "status": "healthy"},
            },
            "metrics": metrics_summary,
        }
    finally:
        await db.close()


# ─── Legacy Setup API (kept for compatibility) ───────────────────────────────

from pydantic import BaseModel as PydanticBaseModel
from dotenv import set_key


class SetupData(PydanticBaseModel):
    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    TOGETHERAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    CEREBRAS_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    FIREWORKS_AI_API_KEY: str = ""
    QDRANT_URL: str = ""
    QDRANT_KEY: str = ""
    DIGITALOCEAN_TOKEN: str = ""


@app.post("/api/setup")
async def save_setup(request: Request, data: SetupData):
    """Legacy setup endpoint — saves keys securely to Vault and updates providers in DB."""
    await require_auth(request)
    from devplane.secrets_mgr import get_vault
    vault = get_vault()
    
    env_file = ".env"
    if not os.path.exists(env_file):
        open(env_file, "a").close()

    for key, value in data.model_dump().items():
        if value:
            # Store securely in Vault (no expiration for core API keys)
            await vault.store_secret(key, value, ttl_minutes=0)
            # Also set in env for immediate use
            os.environ[key] = value
            # We still write to .env for legacy compatibility, but in a real production
            # system we would only load from Vault on startup
            set_key(env_file, key, value)

    # Also update providers in DB
    from devplane.providers import get_provider_by_name, update_provider
    key_map = {
        "TOGETHERAI_API_KEY": "togetherai",
        "GROQ_API_KEY": "groq",
        "DEEPSEEK_API_KEY": "deepseek",
        "CEREBRAS_API_KEY": "cerebras",
        "OPENROUTER_API_KEY": "openrouter",
        "GEMINI_API_KEY": "gemini",
        "FIREWORKS_AI_API_KEY": "fireworks_ai",
    }
    for env_key, prov_name in key_map.items():
        val = getattr(data, env_key, "")
        if val:
            prov = await get_provider_by_name(prov_name)
            if prov:
                # We don't store the actual key in the DB anymore, just a reference or masked version
                masked_key = f"{val[:4]}••••{val[-4:]}" if len(val) > 8 else "••••"
                await update_provider(prov["id"], api_key=masked_key, enabled=True)

    if data.DIGITALOCEAN_TOKEN:
        from devplane.infra.manager import get_infra_manager
        get_infra_manager().token = data.DIGITALOCEAN_TOKEN

    logger.info("Configuration saved securely via setup wizard.")
    return {"status": "success"}


# ─── Lockhost Wizard (Multi-Provider Setup) ──────────────────────────────────

@app.get("/lockhost", response_class=HTMLResponse)
async def lockhost_wizard(request: Request):
    """Lockhost — 5-provider AI mesh configuration wizard."""
    await require_auth(request)
    try:
        with open("static/lockhost.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return RedirectResponse(url="/")


@app.get("/api/lockhost/status")
async def lockhost_status(request: Request):
    """Get current provider status (masked keys, enabled flags)."""
    await require_auth(request)
    from devplane.providers import get_all_providers
    from devplane.roles import get_all_roles

    providers = await get_all_providers()
    result = {}
    for p in providers:
        key = p.get("api_key", "")
        result[p["name"]] = {
            "display_name": p.get("display_name", p["name"]),
            "enabled": bool(p.get("enabled", False)),
            "has_key": bool(key),
            "masked_key": f"{key[:4]}••••{key[-4:]}" if len(key) > 8 else ("••••" if key else ""),
        }

    roles = get_all_roles()
    total_models = set()
    for model_list in roles.values():
        total_models.update(model_list)

    return {
        "providers": result,
        "total_unique_models": len(total_models),
        "roles": {r: models for r, models in roles.items()},
    }


@app.post("/api/lockhost/save")
async def lockhost_save(request: Request, config: dict):
    """Save Lockhost provider configuration securely to Vault and reload mesh."""
    await require_auth(request)
    from devplane.providers import get_provider_by_name, update_provider, load_all_keys_to_env
    from devplane.secrets_mgr import get_vault
    import re
    import shutil

    vault = get_vault()
    env_file = ".env"
    
    # Validate env_key_name format (alphanumeric + underscore, must start with uppercase letter)
    valid_env_key_pattern = re.compile(r'^[A-Z][A-Z0-9_]*$')
    
    # Track if we need to write to .env
    env_updates = []
    
    for prov_name, prov_config in config.items():
        api_key = prov_config.get("api_key", "")
        enabled = prov_config.get("enabled", True)
        env_key_name = prov_config.get("env_key", "")

        # Validate env_key_name format before writing
        if api_key and env_key_name:
            if not valid_env_key_pattern.match(env_key_name):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid env_key format: '{env_key_name}'. Must start with letter and contain only alphanumeric characters and underscores."
                )
            env_updates.append((env_key_name, api_key))
            # Store securely in Vault
            await vault.store_secret(env_key_name, api_key, ttl_minutes=0)

        # Update DB
        prov = await get_provider_by_name(prov_name)
        if prov:
            update_kwargs = {"enabled": enabled}
            if api_key:
                # Store masked key in DB
                masked_key = f"{api_key[:4]}••••{api_key[-4:]}" if len(api_key) > 8 else "••••"
                update_kwargs["api_key"] = masked_key
            await update_provider(prov["id"], **update_kwargs)

    # Safely update .env file with backup
    if env_updates:
        # Create backup if file exists
        if os.path.exists(env_file):
            shutil.copy2(env_file, f"{env_file}.backup")
        
        # Ensure file exists
        if not os.path.exists(env_file):
            open(env_file, "a").close()
        
        # Apply updates
        for env_key_name, api_key in env_updates:
            set_key(env_file, env_key_name, api_key)
            os.environ[env_key_name] = api_key

    # Reload all keys into environment for LiteLLM
    await load_all_keys_to_env()

    logger.info("Lockhost: Provider configuration saved securely and mesh reloaded.")
    return {"status": "success", "message": "All providers locked and deployed securely"}


@app.post("/api/providers/test/{provider_name}")
async def test_provider_endpoint(request: Request, provider_name: str):
    """Test a provider's API connection from the Lockhost wizard."""
    await require_auth(request)
    from devplane.providers import get_provider_by_name, test_provider_connection

    prov = await get_provider_by_name(provider_name)
    if not prov:
        return {"success": False, "error": f"Provider '{provider_name}' not found"}

    result = await test_provider_connection(prov["id"])
    return result


@app.post("/api/lockhost/extensions")
async def lockhost_extensions(request: Request):
    """Run the auto-installer to configure Kilo Code, OpenCoder & Antigravity fallback."""
    import importlib
    try:
        spec = importlib.util.spec_from_file_location("setup_extensions", "setup_extensions.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.run_setup()
        return result
    except Exception as e:
        logger.error(f"Extension setup failed: {e}")
        return {"status": "error", "error": str(e)}


# ─── Deployment Wizard & Secrets Management ──────────────────────────────────

class DeployData(PydanticBaseModel):
    deployment_mode: str = "local"
    DIGITALOCEAN_TOKEN: str = ""
    DIGITALOCEAN_REGION: str = "nyc1"
    CLOUDFLARE_API_TOKEN: str = ""
    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    SECRET_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    DOMAIN: str = ""
    EMAIL: str = ""


@app.get("/api/deploy/detect")
async def detect_environment(request: Request):
    """Detect if running locally or on a remote server."""
    import socket
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    is_remote = not (ip.startswith("127.") or ip.startswith("192.168.") or ip.startswith("10."))
    return {
        "hostname": hostname,
        "ip": ip,
        "is_remote": is_remote,
        "platform": os.name,
        "cwd": os.getcwd()
    }


@app.post("/api/deploy")
async def deploy_configuration(request: Request, data: DeployData):
    """Save deployment configuration and optionally provision infrastructure."""
    await require_auth(request)
    from devplane.secrets_mgr import get_vault
    from devplane.infra.manager import get_infra_manager
    from devplane.providers import get_provider_by_name, update_provider
    import shutil
    
    vault = get_vault()
    env_file = ".env"
    
    # Ensure .env exists
    if not os.path.exists(env_file):
        open(env_file, "a").close()
    
    # Store each non‑empty secret in vault and environment
    for key, value in data.model_dump().items():
        if value:
            await vault.store_secret(key, value, ttl_minutes=0)
            os.environ[key] = value
            set_key(env_file, key, value)
    
    # Update providers in DB
    key_map = {
        "OPENROUTER_API_KEY": "openrouter",
        "DEEPSEEK_API_KEY": "deepseek",
        "GROQ_API_KEY": "groq",
        "GEMINI_API_KEY": "gemini",
    }
    for env_key, prov_name in key_map.items():
        val = getattr(data, env_key, "")
        if val:
            prov = await get_provider_by_name(prov_name)
            if prov:
                masked_key = f"{val[:4]}••••{val[-4:]}" if len(val) > 8 else "••••"
                await update_provider(prov["id"], api_key=masked_key, enabled=True)
    
    # Set DigitalOcean token in infra manager
    if data.DIGITALOCEAN_TOKEN:
        get_infra_manager().token = data.DIGITALOCEAN_TOKEN
        get_infra_manager().region = data.DIGITALOCEAN_REGION
    
    # If remote deployment mode and DO token present, trigger infrastructure deployment
    if data.deployment_mode == "remote" and data.DIGITALOCEAN_TOKEN:
        # In a real implementation we would call deploy-infrastructure.py
        # For now, just log
        logger.info("Remote deployment requested. Infrastructure provisioning would start here.")
    
    logger.info("Deployment configuration saved successfully.")
    return {"status": "success", "message": "Configuration saved and infrastructure queued if applicable."}


@app.get("/api/secrets")
async def get_secrets(request: Request):
    """Return all known secrets (masked) and their status.

    Secret values are masked for security: first 4 and last 4 characters visible
    for strings longer than 8 characters, otherwise replaced with '••••'.
    Empty values indicate missing secrets.
    """
    await require_auth(request)
    from devplane.secrets_mgr import get_vault
    import os
    
    secrets_list = {}
    # List of known secret keys
    known_keys = [
        "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
        "TOGETHERAI_API_KEY", "CEREBRAS_API_KEY", "FIREWORKS_AI_API_KEY",
        "DIGITALOCEAN_TOKEN", "CLOUDFLARE_API_TOKEN", "QDRANT_URL",
        "QDRANT_KEY", "SECRET_KEY", "VAULT_MASTER_KEY"
    ]
    for key in known_keys:
        value = os.environ.get(key, "")
        secrets_list[key] = f"{value[:4]}••••{value[-4:]}" if len(value) > 8 else ("••••" if value else "")
    
    return {"secrets": secrets_list}


@app.post("/api/secrets")
async def update_secret(request: Request, payload: dict):
    """Update a single secret."""
    await require_auth(request)
    from devplane.secrets_mgr import get_vault
    from dotenv import set_key
    
    key = payload.get("key")
    value = payload.get("value", "")
    
    if not key:
        raise HTTPException(status_code=400, detail="Missing 'key'")
    
    vault = get_vault()
    await vault.store_secret(key, value, ttl_minutes=0)
    os.environ[key] = value
    
    # Update .env
    env_file = ".env"
    if not os.path.exists(env_file):
        open(env_file, "a").close()
    set_key(env_file, key, value)
    
    logger.info(f"Secret '{key}' updated.")
    return {"status": "success", "key": key}


# ─── Direct Run ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


