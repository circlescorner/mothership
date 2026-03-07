"""SQLite database layer — stores ALL DevPlane config, usage, and history.

Uses aiosqlite for async access. All config lives in the DB, not in YAML files.
The dashboard reads/writes here. No SSH file editing needed.
"""

import aiosqlite
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("devplane.db")

DB_PATH = os.environ.get("DEVPLANE_DB_PATH", "devplane.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Create all tables if they don't exist. Called at startup."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)
        await db.commit()

        # Seed default project if none exists
        row = await db.execute("SELECT COUNT(*) as c FROM projects")
        count = (await row.fetchone())["c"]
        if count == 0:
            await _seed_defaults(db)

        logger.info(f"Database initialized at {DB_PATH}")
    finally:
        await db.close()


SCHEMA_SQL = """
-- Providers (OpenRouter, Groq, DeepSeek, etc.)
CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    api_key TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    monthly_budget REAL DEFAULT 0.0,
    base_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Models available per provider
CREATE TABLE IF NOT EXISTS provider_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    input_cost_per_1k REAL DEFAULT 0.0,
    output_cost_per_1k REAL DEFAULT 0.0,
    max_tokens INTEGER DEFAULT 4096,
    enabled INTEGER DEFAULT 1
);

-- Projects
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    active_chain_id INTEGER,
    daily_budget REAL DEFAULT 5.0,
    weekly_budget REAL DEFAULT 25.0,
    monthly_budget REAL DEFAULT 100.0,
    is_default INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Chain configurations
CREATE TABLE IF NOT EXISTS chains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    tournament_mode INTEGER DEFAULT 1,
    parallel_tiers TEXT DEFAULT '["cheap","mid","premium"]',
    escalation_enabled INTEGER DEFAULT 1,
    escalation_max INTEGER DEFAULT 2,
    quality_threshold REAL DEFAULT 0.7,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Steps within a chain
CREATE TABLE IF NOT EXISTS chain_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL REFERENCES chains(id) ON DELETE CASCADE,
    step_type TEXT NOT NULL,
    label TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    model_slug TEXT DEFAULT '',
    timeout_seconds INTEGER DEFAULT 60,
    step_order INTEGER DEFAULT 0
);

-- Tier configurations per project
CREATE TABLE IF NOT EXISTS tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    planner_model TEXT DEFAULT '',
    executor_model TEXT DEFAULT '',
    reviewer_model TEXT DEFAULT '',
    judge_model TEXT DEFAULT '',
    max_cost_per_run REAL DEFAULT 0.10,
    enabled INTEGER DEFAULT 1
);

-- Run history
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    chain_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    final_output TEXT DEFAULT '',
    winning_tier TEXT DEFAULT '',
    total_cost REAL DEFAULT 0.0,
    total_duration_ms INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    steps_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);

-- API usage records (individual LLM calls)
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_name TEXT NOT NULL,
    model_slug TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0.0,
    project_id INTEGER DEFAULT 0,
    run_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Index for fast spending queries
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage(provider_name);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);

-- ═══ v2 Tables ═══

-- Managed droplets (VMs, GPUs, workers)
CREATE TABLE IF NOT EXISTS droplets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    droplet_id INTEGER UNIQUE,
    name TEXT NOT NULL,
    size TEXT NOT NULL,
    image TEXT DEFAULT 'ubuntu-22-04-x64',
    region TEXT DEFAULT 'nyc1',
    status TEXT DEFAULT 'creating',
    droplet_type TEXT DEFAULT 'worker',
    vpc_ip TEXT,
    public_ip TEXT,
    cost_per_hour REAL DEFAULT 0.0,
    tags TEXT DEFAULT '[]',
    ttl_minutes INTEGER DEFAULT 0,
    expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Kasm workspaces
CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT UNIQUE,
    template TEXT NOT NULL,
    name TEXT NOT NULL,
    droplet_id INTEGER,
    status TEXT DEFAULT 'creating',
    connect_url TEXT,
    user_email TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    destroyed_at TEXT
);

-- Persistent AI memory
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER DEFAULT 0,
    content TEXT NOT NULL,
    role TEXT DEFAULT 'assistant',
    embedding_id TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Model performance tracking
CREATE TABLE IF NOT EXISTS model_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_slug TEXT NOT NULL,
    step_type TEXT NOT NULL,
    avg_cost REAL DEFAULT 0.0,
    avg_duration_ms REAL DEFAULT 0.0,
    avg_quality REAL DEFAULT 0.0,
    total_runs INTEGER DEFAULT 0,
    last_used TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_droplets_status ON droplets(status);
CREATE INDEX IF NOT EXISTS idx_model_perf_slug ON model_performance(model_slug);
"""


async def _seed_defaults(db: aiosqlite.Connection):
    """Seed default project, chain, tiers, and providers."""
    logger.info("Seeding default configuration...")

    # Default project
    await db.execute(
        "INSERT INTO projects (name, description, is_default, daily_budget, weekly_budget, monthly_budget) VALUES (?, ?, 1, 5.0, 25.0, 100.0)",
        ("Default Project", "Main DevPlane project")
    )
    project_id = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]

    # Default chain
    await db.execute(
        "INSERT INTO chains (project_id, name, description, tournament_mode) VALUES (?, ?, ?, 1)",
        (project_id, "5-Stack Tournament", "Run all tiers in parallel, judge picks the best")
    )
    chain_id = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]

    # Update project to use this chain
    await db.execute("UPDATE projects SET active_chain_id = ? WHERE id = ?", (chain_id, project_id))

    # Default chain steps
    steps = [
        ("planner", "Planner", "You are a concise planner. Break down the user request into 3 execution steps.", 30, 0),
        ("executor", "Executor", "Execute the following plan precisely.", 60, 1),
        ("reviewer", "Reviewer", "You are a reviewer. Polish the provided execution output. Fix errors and format cleanly. Output ONLY the polished response.", 30, 2),
        ("judge", "Judge", "You are an elite judge evaluating AI pipeline outputs. Choose the most accurate, comprehensive answer. Output the winning stack's name in bold, followed by its complete response.", 45, 3),
    ]
    for step_type, label, prompt, timeout, order in steps:
        await db.execute(
            "INSERT INTO chain_steps (chain_id, step_type, label, system_prompt, timeout_seconds, step_order) VALUES (?, ?, ?, ?, ?, ?)",
            (chain_id, step_type, label, prompt, timeout, order)
        )

    # Default tiers
    tiers = [
        ("cheap", "groq/llama-3.3-70b-versatile", "cerebras/llama3.3-70b", "groq/llama-3.1-8b-instant", "groq/llama-3.3-70b-versatile", 0.01),
        ("mid", "gemini/gemini-2.0-flash", "deepseek/deepseek-chat", "gemini/gemini-2.0-flash", "deepseek/deepseek-chat", 0.05),
        ("premium", "openrouter/anthropic/claude-3.5-sonnet", "openrouter/openai/gpt-4o", "openrouter/anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat", 0.50),
    ]
    for level, planner, executor, reviewer, judge, max_cost in tiers:
        await db.execute(
            "INSERT INTO tiers (project_id, level, planner_model, executor_model, reviewer_model, judge_model, max_cost_per_run) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, level, planner, executor, reviewer, judge, max_cost)
        )

    # Default providers
    providers = [
        ("openrouter", "OpenRouter"),
        ("groq", "Groq"),
        ("deepseek", "DeepSeek"),
        ("cerebras", "Cerebras"),
        ("gemini", "Google Gemini"),
        ("fireworks_ai", "Fireworks AI"),
        ("togetherai", "TogetherAI"),
        ("openai", "OpenAI"),
    ]
    for name, display in providers:
        # Try to pull key from env
        env_key = f"{name.upper()}_API_KEY"
        if name == "gemini":
            env_key = "GEMINI_API_KEY"
        elif name == "openai":
            env_key = "OPENAI_API_KEY"
        api_key = os.environ.get(env_key, "")
        enabled = 1 if api_key else 0
        await db.execute(
            "INSERT INTO providers (name, display_name, api_key, enabled) VALUES (?, ?, ?, ?)",
            (name, display, api_key, enabled)
        )

    await db.commit()
    logger.info(f"Seeded default project (id={project_id}), chain (id={chain_id}), 3 tiers, 8 providers")


# ─── Query Helpers ────────────────────────────────────────────────────────────

async def get_default_project_id() -> int:
    db = await get_db()
    try:
        row = await db.execute("SELECT id FROM projects WHERE is_default = 1 LIMIT 1")
        result = await row.fetchone()
        return result["id"] if result else 1
    finally:
        await db.close()


async def get_spending(period: str = "daily", provider: Optional[str] = None) -> float:
    """Get total spending for a period. period: 'daily', 'weekly', 'monthly'."""
    now = datetime.utcnow()
    if period == "daily":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        since = now - timedelta(days=now.weekday())
        since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "monthly":
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)

    db = await get_db()
    try:
        query = "SELECT COALESCE(SUM(cost), 0) as total FROM usage WHERE created_at >= ?"
        params = [since.isoformat()]
        if provider:
            query += " AND provider_name = ?"
            params.append(provider)
        row = await db.execute(query, params)
        result = await row.fetchone()
        return result["total"]
    finally:
        await db.close()


async def record_usage(provider_name: str, model_slug: str, input_tokens: int,
                       output_tokens: int, cost: float, project_id: int = 0,
                       run_id: Optional[int] = None):
    """Record a single LLM API call."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO usage (provider_name, model_slug, input_tokens, output_tokens, cost, project_id, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (provider_name, model_slug, input_tokens, output_tokens, cost, project_id, run_id)
        )
        await db.commit()
    finally:
        await db.close()
