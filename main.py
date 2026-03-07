"""DevPlane — Unified AI Control Plane.

Main entrypoint: FastAPI app with all API routers + Slack bot.
"""

import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

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

    await init_db()
    await load_all_keys_to_env()
    init_slack()

    if slack_handler:
        logger.info("Starting Slack Socket Mode Handler...")
        try:
            task = asyncio.create_task(slack_handler.start_async())
            yield
            logger.info("Shutting down Slack handler...")
            await slack_handler.close_async()
            task.cancel()
        except Exception as e:
            logger.error(f"Slack handler error: {e}. Running Web-Only mode.")
            yield
    else:
        logger.warning("Slack tokens not configured. Running Web-Only mode.")
        yield


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="DevPlane", version="1.0.0", lifespan=lifespan)

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

app.include_router(providers_router)
app.include_router(credits_router)
app.include_router(chains_router)
app.include_router(projects_router)
app.include_router(infra_router)


# ─── v2 Memory + Optimizer inline endpoints ────────────────────────────────────

@app.get("/api/memory/stats")
async def memory_stats(project_id: int = 0):
    from devplane.memory.store import get_memory_stats
    return await get_memory_stats(project_id)

@app.get("/api/memory/search")
async def memory_search(q: str, project_id: int = 0, limit: int = 20):
    from devplane.memory.store import search_memory
    return await search_memory(q, project_id, limit)

@app.get("/api/memory/history")
async def memory_history(project_id: int = 0, limit: int = 20):
    from devplane.memory.store import get_history
    return await get_history(project_id, limit)

@app.post("/api/memory/clear")
async def memory_clear(project_id: int = 0):
    from devplane.memory.store import clear_memory
    return await clear_memory(project_id)

@app.get("/api/optimizer/insights")
async def optimizer_insights():
    from devplane.chain.optimizer import get_insights
    return await get_insights()

@app.post("/api/optimizer/recommend")
async def optimizer_recommend(data: dict):
    from devplane.chain.optimizer import recommend_tier, recommend_models
    tier = await recommend_tier(data.get("prompt", ""))
    models = await recommend_models(data.get("step_type", "executor"))
    return {"tier": tier, "models": models}


# ─── Core Routes ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Serve the dashboard or redirect to setup."""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return {"status": "DevPlane Online", "message": "Dashboard not deployed yet."}


@app.get("/setup", response_class=HTMLResponse)
async def setup_wizard():
    """Legacy setup wizard (kept for initial first-run)."""
    try:
        with open("static/setup.html", "r", encoding="utf-8") as f:
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
            "version": "1.0.0",
            "uptime_seconds": int(time.time() - START_TIME),
            "slack_connected": slack_handler is not None,
            "providers_active": prov_count,
            "total_runs": run_count,
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
async def save_setup(data: SetupData):
    """Legacy setup endpoint — saves keys to .env and updates providers in DB."""
    env_file = ".env"
    if not os.path.exists(env_file):
        open(env_file, "a").close()

    for key, value in data.model_dump().items():
        if value:
            set_key(env_file, key, value)
            os.environ[key] = value

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
                await update_provider(prov["id"], api_key=val, enabled=True)

    if data.DIGITALOCEAN_TOKEN:
        from devplane.infra.manager import get_infra_manager
        get_infra_manager().token = data.DIGITALOCEAN_TOKEN

    logger.info("Configuration saved via setup wizard.")
    return {"status": "success"}


# ─── Direct Run ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
