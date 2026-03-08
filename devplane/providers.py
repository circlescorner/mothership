"""Provider registry — manages AI providers and their API keys.

All state lives in SQLite. Keys are loaded from DB at call time,
not from environment variables (except during initial seed).
"""

import os
import logging
from devplane.db import get_db

logger = logging.getLogger("devplane.providers")


async def get_all_providers() -> list[dict]:
    """Get all providers with their enabled status."""
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM providers ORDER BY name")
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


async def get_provider(provider_id: int) -> dict | None:
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM providers WHERE id = ?", (provider_id,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()


async def get_provider_by_name(name: str) -> dict | None:
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM providers WHERE name = ?", (name,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()


async def update_provider(provider_id: int, **kwargs) -> bool:
    """Update provider fields. Only non-None kwargs are updated."""
    db = await get_db()
    try:
        sets = []
        values = []
        for key, value in kwargs.items():
            if value is not None and key in ("api_key", "enabled", "monthly_budget", "display_name", "base_url"):
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return False
        sets.append("updated_at = datetime('now')")
        values.append(provider_id)
        await db.execute(f"UPDATE providers SET {', '.join(sets)} WHERE id = ?", values)
        await db.commit()

        # Also set env var if it's an API key update so LiteLLM can use it
        if "api_key" in kwargs and kwargs["api_key"]:
            prov = await get_provider(provider_id)
            if prov:
                _set_env_key(prov["name"], kwargs["api_key"])

        return True
    finally:
        await db.close()


async def create_provider(name: str, display_name: str, api_key: str = "",
                          monthly_budget: float = 0.0) -> int:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO providers (name, display_name, api_key, enabled, monthly_budget) VALUES (?, ?, ?, ?, ?)",
            (name, display_name, api_key, 1 if api_key else 0, monthly_budget)
        )
        await db.commit()
        row = await db.execute("SELECT last_insert_rowid()")
        result = await row.fetchone()
        if api_key:
            _set_env_key(name, api_key)
        return result[0]
    finally:
        await db.close()


async def delete_provider(provider_id: int) -> bool:
    db = await get_db()
    try:
        await db.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        await db.commit()
        return True
    finally:
        await db.close()


async def test_provider_connection(provider_id: int) -> dict:
    """Test if a provider's API key works by making a minimal call."""
    from litellm import acompletion
    import asyncio

    prov = await get_provider(provider_id)
    if not prov or not prov["api_key"]:
        return {"success": False, "error": "No API key configured"}

    # Ensure env var is set
    _set_env_key(prov["name"], prov["api_key"])

    # Pick a cheap/fast model for testing
    test_models = {
        "groq": "groq/llama-3.1-8b-instant",
        "cerebras": "cerebras/llama3.3-70b",
        "deepseek": "deepseek/deepseek-chat",
        "gemini": "gemini/gemini-2.0-flash",
        "openrouter": "openrouter/anthropic/claude-sonnet-4",
        "fireworks_ai": "fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct",
        "togetherai": "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",
        "openai": "openai/gpt-4o-mini",
    }
    model = test_models.get(prov["name"], f"{prov['name']}/test")

    try:
        response = await asyncio.wait_for(
            acompletion(
                model=model,
                messages=[{"role": "user", "content": "Say 'ok' and nothing else."}],
                max_tokens=5,
            ),
            timeout=15.0
        )
        return {"success": True, "model": model, "response": response.choices[0].message.content}
    except Exception as e:
        return {"success": False, "error": str(e), "model": model}


async def load_all_keys_to_env():
    """Load all provider API keys into environment variables for LiteLLM."""
    db = await get_db()
    try:
        rows = await db.execute("SELECT name, api_key FROM providers WHERE api_key != '' AND enabled = 1")
        async for r in rows:
            _set_env_key(r["name"], r["api_key"])
        logger.info("Loaded all provider API keys into environment")
    finally:
        await db.close()


def _set_env_key(provider_name: str, api_key: str):
    """Set the correct environment variable for a provider."""
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "fireworks_ai": "FIREWORKS_AI_API_KEY",
        "togetherai": "TOGETHERAI_API_KEY",
        "together_ai": "TOGETHERAI_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = env_map.get(provider_name)
    if env_var and api_key:
        os.environ[env_var] = api_key
