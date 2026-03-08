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

-- Role-based model registry (5-way fallback per role)
CREATE TABLE IF NOT EXISTS role_models (
    role TEXT PRIMARY KEY,
    models_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT DEFAULT (datetime('now'))
);

-- GPU compute jobs (Vast.ai, RunPod, Modal, Lambda, DO)
CREATE TABLE IF NOT EXISTS gpu_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE,
    provider TEXT NOT NULL DEFAULT 'digitalocean',
    script_hash TEXT,
    status TEXT DEFAULT 'pending',
    gpu_type TEXT DEFAULT '',
    cost_per_hour REAL DEFAULT 0.0,
    total_cost REAL DEFAULT 0.0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Visual Workflow Orchestration
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    nodes TEXT NOT NULL DEFAULT '[]',
    edges TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    config TEXT DEFAULT '{}'
);

-- User Profiles for Personal Agent
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Token Cache Persistence
CREATE TABLE IF NOT EXISTS token_cache (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    model TEXT,
    tokens_saved INTEGER DEFAULT 0,
    cost_saved REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT
);

-- Agent Swarm Executions
CREATE TABLE IF NOT EXISTS swarm_executions (
    id TEXT PRIMARY KEY,
    swarm_name TEXT,
    consensus_type TEXT,
    final_output TEXT,
    individual_responses TEXT,
    execution_time_ms REAL,
    total_tokens INTEGER,
    total_cost_usd REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ═══ MCP Agent Registry & Cross-IDE Queue ═══

-- Registered external agents (Kilo Code, Cursor, etc.)
CREATE TABLE IF NOT EXISTS agent_workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ide_name TEXT NOT NULL,
    agent_name TEXT NOT NULL UNIQUE,
    description TEXT,
    input_schema TEXT DEFAULT '{}',
    is_active INTEGER DEFAULT 1,
    last_ping TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);

-- Cross-IDE Task Queue (Antigravity -> Kilo Code)
CREATE TABLE IF NOT EXISTS devplane_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result_json TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

-- ═══ Secrets Manager (Vault) ═══

-- Ephemeral, encrypted secrets
CREATE TABLE IF NOT EXISTS devplane_secrets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_droplets_status ON droplets(status);
CREATE INDEX IF NOT EXISTS idx_model_perf_slug ON model_performance(model_slug);
CREATE INDEX IF NOT EXISTS idx_gpu_jobs_status ON gpu_jobs(status);
CREATE INDEX IF NOT EXISTS idx_workflows_active ON workflows(is_active);
CREATE INDEX IF NOT EXISTS idx_token_cache_expires ON token_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_devplane_tasks_status ON devplane_tasks(status);

-- ═══ UNIFIED AGENTIC MESH CONFIGURATION ═══

-- Mesh global configuration
CREATE TABLE IF NOT EXISTS mesh_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    execution_mode TEXT DEFAULT 'tournament' CHECK(execution_mode IN ('tournament', 'mesh', 'agent')),
    mcp_servers_enabled TEXT DEFAULT '[]',
    default_tier TEXT DEFAULT 'mid',
    max_iterations INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 60,
    config_json TEXT DEFAULT '{}',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Mesh role configuration (per-mesh overrides)
CREATE TABLE IF NOT EXISTS mesh_role_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mesh_config_id INTEGER NOT NULL REFERENCES mesh_configs(id) ON DELETE CASCADE,
    role_name TEXT NOT NULL,
    model_slug TEXT,
    iteration_limit INTEGER,
    timeout_seconds INTEGER DEFAULT 60,
    config_json TEXT DEFAULT '{}',
    UNIQUE(mesh_config_id, role_name)
);

-- MCP server registry and status
CREATE TABLE IF NOT EXISTS mcp_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    server_type TEXT NOT NULL CHECK(server_type IN ('llamaindex', 'haystack', 'crewai', 'pydanticai', 'semantickernel', 'custom')),
    endpoint TEXT,
    status TEXT DEFAULT 'offline' CHECK(status IN ('online', 'offline', 'error')),
    enabled INTEGER DEFAULT 1,
    last_ping TEXT,
    tools_json TEXT DEFAULT '[]',
    config_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Tournament bracket results
CREATE TABLE IF NOT EXISTS tournament_brackets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    tier_results TEXT DEFAULT '[]',
    judge_selection TEXT,
    winner_tier TEXT,
    execution_time_ms REAL,
    cost_per_tier TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Mesh routing rules (for !mesh_route command)
CREATE TABLE IF NOT EXISTS mesh_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    mcp_server TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Visual mesh node positions
CREATE TABLE IF NOT EXISTS mesh_visualization (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_type TEXT NOT NULL,
    node_id TEXT NOT NULL,
    position_x REAL DEFAULT 0,
    position_y REAL DEFAULT 0,
    config_json TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Memory configuration
CREATE TABLE IF NOT EXISTS memory_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    embedding_model TEXT DEFAULT 'text-embedding-ada-002',
    embedding_dimension INTEGER DEFAULT 1536,
    qdrant_url TEXT DEFAULT 'http://localhost:6333',
    qdrant_collection TEXT DEFAULT 'devplane_memories',
    max_memory_items INTEGER DEFAULT 1000,
    config_json TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Optimizer configuration
CREATE TABLE IF NOT EXISTS optimizer_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complexity_threshold REAL DEFAULT 0.5,
    scoring_weights_json TEXT DEFAULT '{"accuracy": 0.4, "cost": 0.3, "speed": 0.3}',
    max_iterations INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 30,
    config_json TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Tool configuration
CREATE TABLE IF NOT EXISTS tool_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    timeout_seconds INTEGER DEFAULT 30,
    permissions_json TEXT DEFAULT '[]',
    config_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- LangChain dynamic tools
CREATE TABLE IF NOT EXISTS langchain_tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    schema_json TEXT,
    handler_type TEXT,
    handler_config_json TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mesh_configs_active ON mesh_configs(is_active);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_status ON mcp_servers(status);
CREATE INDEX IF NOT EXISTS idx_mesh_routes_keyword ON mesh_routes(keyword);
CREATE INDEX IF NOT EXISTS idx_tournament_brackets_run ON tournament_brackets(run_id);
"""


async def _seed_defaults(db: aiosqlite.Connection):
    """Seed default project, chain, tiers, and providers."""
    logger.info("Seeding default configuration...")

    # Default project
    await db.execute("""
        INSERT OR IGNORE INTO projects (id, name, description, daily_budget, weekly_budget, monthly_budget, is_default)
        VALUES (1, 'Default Project', 'Main workspace', 4.0, 4.0, 4.0, 1)
    """)
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

    # Seed default mesh configuration
    await db.execute("""
        INSERT OR IGNORE INTO mesh_configs (id, name, execution_mode, mcp_servers_enabled, default_tier, max_iterations, timeout_seconds)
        VALUES (1, 'Default Mesh', 'tournament', '["llamaindex", "haystack", "crewai", "pydanticai", "semantickernel"]', 'mid', 3, 60)
    """)

    # Seed default mesh role configuration
    mesh_config_id = 1
    role_configs = [
        ('architect', 'openrouter/anthropic/claude-sonnet-4', 3, 60),
        ('worker', 'deepseek/deepseek-chat', 3, 60),
        ('critic', 'openrouter/anthropic/claude-sonnet-4', 3, 60),
    ]
    for role_name, model_slug, iteration_limit, timeout_seconds in role_configs:
        await db.execute("""
            INSERT OR REPLACE INTO mesh_role_config (mesh_config_id, role_name, model_slug, iteration_limit, timeout_seconds)
            VALUES (?, ?, ?, ?, ?)
        """, (mesh_config_id, role_name, model_slug, iteration_limit, timeout_seconds))

    # Seed default memory configuration
    await db.execute("""
        INSERT OR IGNORE INTO memory_config (id, embedding_model, embedding_dimension, qdrant_url, qdrant_collection, max_memory_items)
        VALUES (1, 'text-embedding-ada-002', 1536, 'http://localhost:6333', 'devplane_memories', 1000)
    """)

    # Seed default optimizer configuration
    await db.execute("""
        INSERT OR IGNORE INTO optimizer_config (id, complexity_threshold, scoring_weights_json, max_iterations, timeout_seconds)
        VALUES (1, 0.5, '{"accuracy": 0.4, "cost": 0.3, "speed": 0.3}', 3, 30)
    """)

    # Seed default tool configuration (core tools)
    core_tools = [
        ('search_web', 'Web Search', 1, 30, '[]'),
        ('execute_command', 'Execute Command', 1, 30, '[]'),
        ('read_file', 'Read File', 1, 30, '[]'),
        ('write_file', 'Write File', 1, 30, '[]'),
        ('list_files', 'List Files', 1, 30, '[]'),
        ('apply_diff', 'Apply Diff', 1, 30, '[]'),
        ('delete_file', 'Delete File', 1, 30, '[]'),
        ('codebase_search', 'Codebase Search', 1, 30, '[]'),
        ('search_files', 'Search Files', 1, 30, '[]'),
    ]
    for tool_name, display_name, enabled, timeout, permissions in core_tools:
        await db.execute(
            "INSERT OR IGNORE INTO tool_config (tool_name, display_name, enabled, timeout_seconds, permissions_json) VALUES (?, ?, ?, ?, ?)",
            (tool_name, display_name, enabled, timeout, permissions)
        )

    # Seed example LangChain dynamic tools
    langchain_tools = [
        {
            'name': 'echo_tool',
            'description': 'Echoes back the input text.',
            'schema_json': '{"type": "object", "properties": {"text": {"type": "string", "description": "Text to echo"}}, "required": ["text"]}',
            'handler_type': 'python_function',
            'handler_config_json': '{"module": "devplane.tools.example", "function": "echo"}',
            'enabled': 0  # disabled by default, need to implement module
        },
        {
            'name': 'http_placeholder',
            'description': 'Placeholder for an HTTP endpoint tool.',
            'schema_json': '{"type": "object", "properties": {"url": {"type": "string", "description": "URL to call"}}, "required": ["url"]}',
            'handler_type': 'http_endpoint',
            'handler_config_json': '{"url": "https://api.example.com/tool", "method": "POST"}',
            'enabled': 0
        }
    ]
    for tool in langchain_tools:
        await db.execute(
            """INSERT OR IGNORE INTO langchain_tools
               (name, description, schema_json, handler_type, handler_config_json, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tool['name'], tool['description'], tool['schema_json'], tool['handler_type'],
             tool['handler_config_json'], tool['enabled'])
        )

    # Seed MCP servers
    mcp_servers = [
        ("llamaindex", "LlamaIndex", "llamaindex"),
        ("haystack", "Haystack", "haystack"),
        ("crewai", "CrewAI", "crewai"),
        ("pydanticai", "PydanticAI", "pydanticai"),
        ("semantickernel", "Semantic Kernel", "semantickernel"),
    ]
    for name, display, server_type in mcp_servers:
        await db.execute(
            "INSERT OR IGNORE INTO mcp_servers (name, display_name, server_type, status, enabled, tools_json) VALUES (?, ?, ?, 'offline', 1, '[]')",
            (name, display, server_type)
        )

    # Seed default mesh routes for !mesh_route command
    mesh_routes = [
        ("search", "haystack", 1),
        ("find", "haystack", 2),
        ("document", "llamaindex", 1),
        ("index", "llamaindex", 2),
        ("validate", "pydanticai", 1),
        ("schema", "pydanticai", 2),
        ("enterprise", "semantickernel", 1),
        ("logic", "semantickernel", 2),
        ("crew", "crewai", 1),
        ("agent", "crewai", 2),
    ]
    for keyword, server, priority in mesh_routes:
        await db.execute(
            "INSERT OR IGNORE INTO mesh_routes (keyword, mcp_server, priority) VALUES (?, ?, ?)",
            (keyword, server, priority)
        )

    # Seed mesh visualization nodes
    mesh_nodes = [
        ("component", "planner", 100, 100, '{"label": "Planner", "icon": "📋"}'),
        ("component", "executor", 300, 100, '{"label": "Executor", "icon": "⚙️"}'),
        ("component", "reviewer", 500, 100, '{"label": "Reviewer", "icon": "✅"}'),
        ("component", "judge", 700, 100, '{"label": "Judge", "icon": "🏆"}'),
        ("mcp_server", "llamaindex", 100, 300, '{"label": "LlamaIndex", "icon": "📚"}'),
        ("mcp_server", "haystack", 250, 300, '{"label": "Haystack", "icon": "🔍"}'),
        ("mcp_server", "crewai", 400, 300, '{"label": "CrewAI", "icon": "👔"}'),
        ("mcp_server", "pydanticai", 550, 300, '{"label": "PydanticAI", "icon": "🛡️"}'),
        ("mcp_server", "semantickernel", 700, 300, '{"label": "Semantic Kernel", "icon": "🌉"}'),
    ]
    for node_type, node_id, x, y, config in mesh_nodes:
        await db.execute(
            "INSERT OR IGNORE INTO mesh_visualization (node_type, node_id, position_x, position_y, config_json) VALUES (?, ?, ?, ?, ?)",
            (node_type, node_id, x, y, config)
        )

    await db.commit()
    logger.info(f"Seeded default project (id={project_id}), chain (id={chain_id}), 3 tiers, 8 providers, mesh config, MCP servers")


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
