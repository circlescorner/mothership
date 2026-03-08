"""Role-Based Model Registry — 5-way fallback per pipeline role.

Every pipeline step (architect, worker, critic, fast, planner, executor,
reviewer, judge) gets 5 alternative models. On failure, the system
automatically tries the next model in the fallback chain.

Integrates with credits.check_budget and optimizer.record_step_performance.
"""

import logging
import time
from typing import Optional
from litellm import acompletion

logger = logging.getLogger("devplane.roles")


# ─── Default Role Registry ───────────────────────────────────────────────────
# Each role maps to an ordered list of 5 model slugs (best → cheapest fallback)

DEFAULT_ROLES = {
    # ── Best token/$ SOTA coding models (2026) ──────────────────────────────
    # 5 providers: OpenRouter, DeepSeek, Groq, Gemini, TogetherAI
    # + Kilo Code proxy & OpenCoder integration via OpenRouter
    "architect": [
        "openrouter/anthropic/claude-sonnet-4",          # Premium SOTA architect
        "deepseek/deepseek-chat",                        # $0.14/1M — near-frontier
        "gemini/gemini-2.0-flash",                       # Free tier
        "openrouter/qwen/qwen3-coder-next",              # Best coding value via OR
        "groq/llama-3.3-70b-versatile",                  # Free fallback
    ],
    "worker": [
        "deepseek/deepseek-chat",                        # Best $/token coder
        "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",  # Dedicated code model
        "groq/llama-3.3-70b-versatile",                  # Free speed
        "gemini/gemini-2.0-flash",                       # Free
        "openrouter/opencoder/opencoder-8b",             # OpenCoder via OR
    ],
    "critic": [
        "openrouter/anthropic/claude-sonnet-4",          # Best reviewer
        "gemini/gemini-2.0-flash",                       # Free
        "deepseek/deepseek-chat",                        # Cheap + smart
        "groq/llama-3.3-70b-versatile",                  # Free speed
        "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",  # Code specialist
    ],
    "fast": [
        "groq/llama-3.3-70b-versatile",                  # Fastest inference
        "cerebras/llama3.3-70b",                         # Hardware-accelerated
        "gemini/gemini-2.0-flash",                       # Free + fast
        "deepseek/deepseek-chat",                        # Cheap fallback
        "fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct",
    ],
    # Aliases that map to the same logical roles for chain engine compatibility
    "planner": [
        "deepseek/deepseek-chat",                        # Best planning value
        "gemini/gemini-2.0-flash",                       # Free
        "openrouter/qwen/qwen3-coder-next",              # Code-aware planner
        "groq/llama-3.3-70b-versatile",                  # Free speed
        "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",  # Code specialist
    ],
    "executor": [
        "deepseek/deepseek-chat",                        # Best execution value
        "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",  # Dedicated coder
        "groq/llama-3.3-70b-versatile",                  # Free speed
        "gemini/gemini-2.0-flash",                       # Free
        "openrouter/opencoder/opencoder-8b",             # OpenCoder fallback
    ],
    "reviewer": [
        "gemini/gemini-2.0-flash",                       # Free review
        "deepseek/deepseek-chat",                        # Cheap + thorough
        "openrouter/anthropic/claude-sonnet-4",          # Premium review
        "groq/llama-3.3-70b-versatile",                  # Free speed
        "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",  # Code specialist
    ],
    "judge": [
        "openrouter/anthropic/claude-sonnet-4",          # Best judgment
        "deepseek/deepseek-chat",                        # Cheap + smart
        "gemini/gemini-2.0-flash",                       # Free
        "groq/llama-3.3-70b-versatile",                  # Free speed
        "together_ai/Qwen/Qwen2.5-Coder-32B-Instruct",  # Code specialist
    ],
    # Personal agent - high quality for trusted assistant
    "personal": [
        "openrouter/openai/o1",                          # Best reasoning
        "openrouter/anthropic/claude-sonnet-4",          # Best overall
        "deepseek/deepseek-reasoner",                    # Reasoning specialist
        "gemini/gemini-1.5-pro",                         # Multimodal
        "groq/llama-3.3-70b-versatile",                  # Fast fallback
    ],
}

# In-memory cache (overrides loaded from DB at startup)
_role_overrides: dict[str, list[str]] = {}


# ─── Registry API ────────────────────────────────────────────────────────────

def get_models_for_role(role: str) -> list[str]:
    """Get the ordered list of 5 fallback models for a role."""
    if role in _role_overrides:
        return _role_overrides[role]
    return DEFAULT_ROLES.get(role, DEFAULT_ROLES["worker"])


def get_model_for_role(role: str, attempt: int = 0) -> str:
    """Get the model slug for a specific fallback attempt (0-4)."""
    models = get_models_for_role(role)
    idx = min(attempt, len(models) - 1)
    return models[idx]


def set_role_models(role: str, models: list[str]):
    """Override the model list for a role (persists in memory, call save_to_db to persist)."""
    _role_overrides[role] = models[:5]  # Max 5


def get_all_roles() -> dict[str, list[str]]:
    """Get the full role registry (with overrides applied)."""
    result = {}
    for role in DEFAULT_ROLES:
        result[role] = get_models_for_role(role)
    # Include any custom roles
    for role in _role_overrides:
        if role not in result:
            result[role] = _role_overrides[role]
    return result


# ─── Smart Caller with Fallback ──────────────────────────────────────────────

async def call_with_fallback(
    role: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    timeout: int = 60,
    project_id: int = 0,
    run_id: int = 0,
) -> dict:
    """Call an LLM with automatic 5-way fallback.

    Tries each model in the role's fallback chain. On success, records
    performance metrics. On all failures, returns an error dict.

    Returns:
        dict with keys: content, model, cost, duration_ms, tokens_in, tokens_out
    """
    from devplane.credits import check_budget, record_call
    from devplane.chain.optimizer import record_step_performance

    models = get_models_for_role(role)
    last_error = None

    for attempt, model in enumerate(models):
        # Extract provider name for budget check
        provider = model.split("/")[0]

        # Budget check
        allowed, reason = await check_budget(provider, project_id)
        if not allowed:
            logger.warning(f"[{role}] Budget blocked for {provider}: {reason}")
            continue

        start = time.time()
        try:
            logger.info(f"[{role}] Attempt {attempt + 1}/5 → {model}")
            response = await acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )

            duration_ms = int((time.time() - start) * 1000)
            content = response.choices[0].message.content or ""
            usage = response.usage
            tokens_in = usage.prompt_tokens if usage else 0
            tokens_out = usage.completion_tokens if usage else 0

            # Estimate cost from response
            cost = 0.0
            try:
                if hasattr(response, "_hidden_params") and response._hidden_params:
                    cost = response._hidden_params.get("response_cost", 0.0) or 0.0
            except Exception:
                cost = 0.0  # Fallback if _hidden_params is unavailable

            # Record usage
            await record_call(provider, model, tokens_in, tokens_out, cost, project_id, run_id)

            # Record performance for optimizer
            await record_step_performance(model, role, cost, duration_ms, quality=0.8)

            logger.info(f"[{role}] ✅ {model} — {duration_ms}ms, ${cost:.4f}")

            return {
                "content": content,
                "model": model,
                "cost": cost,
                "duration_ms": duration_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "attempt": attempt + 1,
            }

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            last_error = str(e)
            logger.warning(f"[{role}] ❌ {model} failed ({duration_ms}ms): {last_error}")
            # Record failed attempt
            await record_step_performance(model, role, 0, duration_ms, quality=0.0)
            continue

    # All 5 failed
    error_msg = f"All 5 models failed for role '{role}'. Last error: {last_error}"
    logger.error(error_msg)
    return {
        "content": f"Error: {error_msg}",
        "model": "none",
        "cost": 0.0,
        "duration_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "attempt": len(models),
        "error": error_msg,
    }


# ─── DB Persistence ──────────────────────────────────────────────────────────

async def load_from_db():
    """Load role overrides from the database (called at startup)."""
    from devplane.db import get_db
    import json

    db = await get_db()
    try:
        rows = await db.execute("SELECT role, models_json FROM role_models")
        async for row in rows:
            try:
                models = json.loads(row["models_json"])
                if isinstance(models, list) and len(models) > 0:
                    _role_overrides[row["role"]] = models
            except (json.JSONDecodeError, KeyError):
                pass
        if _role_overrides:
            logger.info(f"Loaded {len(_role_overrides)} role overrides from DB")
    except Exception:
        # Table might not exist yet
        pass
    finally:
        await db.close()


async def save_to_db():
    """Save current role overrides to the database."""
    from devplane.db import get_db
    import json

    db = await get_db()
    try:
        for role, models in _role_overrides.items():
            await db.execute(
                "INSERT OR REPLACE INTO role_models (role, models_json) VALUES (?, ?)",
                (role, json.dumps(models))
            )
        await db.commit()
        logger.info(f"Saved {len(_role_overrides)} role overrides to DB")
    finally:
        await db.close()
