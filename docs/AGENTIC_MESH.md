# The Unified Agentic Mesh Architecture

DevPlane implements a unified "Agentic Mesh" architecture that leverages the Model Context Protocol (MCP) as a universal communication backbone to integrate AI frameworks, Slack tournament capabilities, and visual configuration through a single pane of glass.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DEVPLANE UNIFIED MESH                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   SLACK     │    │   DASHBOARD │    │   MCP IDE   │    │   REST API  │  │
│  │  INTERFACE  │    │    (WEB)    │    │  (EXT IDE)  │    │  (PROGRAM)  │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │          │
│         └──────────────────┼──────────────────┼──────────────────┘          │
│                            │                  │                              │
│                    ┌───────▼──────────────────▼───────┐                      │
│                    │      MCP HOST / GATEWAY          │                      │
│                    │  (Slack Bot + API + Dashboard)   │                      │
│                    └───────────────┬──────────────────┘                      │
│                                │                                              │
│         ┌──────────────────────┼──────────────────────┐                     │
│         │                      │                      │                     │
│  ┌──────▼──────┐    ┌──────────▼──────────┐   ┌──────▼──────┐              │
│  │   TOURNAMENT│    │      GOD-MODE       │   │    AGENT    │              │
│  │   ENGINE    │    │       MESH          │   │    MODE     │              │
│  └──────┬──────┘    └──────────┬──────────┘   └──────┬──────┘              │
│         │                      │                      │                      │
│         └──────────────────────┼──────────────────────┘                      │
│                                │                                              │
│                    ┌───────────▼───────────┐                                 │
│                    │   EXECUTION LAYER     │                                 │
│                    │  (LangGraph Pipeline) │                                 │
│                    └───────────┬───────────┘                                 │
│                                │                                             │
│  ══════════════════════════════╪══════════════════════════════════════════  │
│                    MCP SERVER LAYER (Tool Providers)                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐ │
│  │ LlamaIndex │ │  Haystack  │ │   CrewAI   │ │ PydanticAI │ │Semantic   │ │
│  │ (Retrieval)│ │  (Search)  │ │(Orchestrat)│ │ (Validate) │ │  Kernel   │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └───────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Execution Modes

The Agentic Mesh supports three primary execution modes, configurable via Slack, Dashboard, or API:

#### Tournament Mode (`!tournament`)
- Runs multiple **tiers** in parallel (cheap, mid, premium)
- A **judge** model evaluates and picks the best result
- Each tier has its own planner, executor, reviewer, and judge models
- **Use case**: When quality matters and you want the best answer regardless of cost

#### God-Mode Mesh (`!mesh`)
- Iterative **Architect → Worker → Critic** loop
- Up to 3 iterations of code generation and review
- **Use case**: Complex coding tasks requiring high-quality, production-ready code

#### Agent Mode (`!agent`)
- LangGraph-powered tool agent with persistent memory
- Uses tools for search, memory, infrastructure, and more
- **Use case**: Multi-step tasks requiring tool use and stateful conversation

### 2. MCP Server Integration

Each framework operates as an MCP Server exposing specialized tools:

| Framework | Role | MCP Tools | Use Case |
|-----------|------|-----------|----------|
| **LlamaIndex** | The Librarian | `search_docs`, `index_document`, `query_index` | Private documentation retrieval |
| **Haystack** | Search Specialist | `enterprise_search`, `build_pipeline`, `query_nlp` | Production-grade search |
| **CrewAI** | The Manager | `create_crew`, `kickoff_crew`, `add_agent` | Multi-agent orchestration |
| **PydanticAI** | The Validator | `validate_schema`, `validate_output`, `validate_input` | Type-safe validation |
| **Semantic Kernel** | Enterprise Bridge | `invoke_function`, `create_skill`, `execute_plan` | Legacy system integration |

### 3. Slack Tournament System

Slack serves as the primary conversational interface with these commands:

| Command | Description | Example |
|---------|-------------|---------|
| `!mesh_route <task>` | Route task to appropriate MCP servers | `!mesh_route search company docs for API` |
| `!mesh <task>` | Run God-Mode Mesh | `!mesh write a REST API` |
| `!tournament <task>` | Run Tournament Mode | `!tournament explain quantum computing` |
| `!agent <task>` | Run Agent Mode | `!agent find and fix all bugs in repo` |
| `!spinup worker` | Spin up ephemeral worker | `!spinup worker` |
| `!sleep` | Collapse workspaces (scale-to-zero) | `!sleep` |
| `!wake` | Restore workspaces from snapshots | `!wake` |
| `!status` | Check infrastructure status | `!status` |

### 4. Visual Configuration (DevPlane Dashboard)

The dashboard provides a "single pane of glass" for:

- **Chain Builder**: Configure execution pipelines (planner → executor → reviewer → judge)
- **Tier Configuration**: Set models for each quality tier
- **Mesh Visualization**: See how tasks flow through the system
- **Tournament Brackets**: View parallel tier execution and judge selection
- **Real-time Observability**: Live execution with Langfuse traces

### 5. Persistent Agents

Two background agents run continuously:

1. **Infra Manager**
   - Monitors infrastructure and budget
   - Executes scale-to-zero when budget hits 90%
   - Creates snapshots before destroying droplets

2. **Builder**
   - Builds and implements improvements to DevPlane
   - Can be invoked via Slack or API

## Configuration

### Database Schema

The mesh is fully configurable via SQLite:

```sql
-- Mesh configurations
CREATE TABLE mesh_configs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    execution_mode TEXT DEFAULT 'tournament',  -- tournament, mesh, agent
    mcp_servers_enabled TEXT DEFAULT '[]',     -- JSON array of server names
    default_tier TEXT DEFAULT 'mid',
    max_iterations INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 60,
    config_json TEXT DEFAULT '{}'
);

-- Tournament brackets
CREATE TABLE tournament_brackets (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES runs(id),
    tier_results TEXT DEFAULT '[]',  -- JSON of each tier's output
    judge_selection TEXT,
    winner_tier TEXT,
    execution_time_ms REAL
);

-- MCP server status
CREATE TABLE mcp_servers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    server_type TEXT NOT NULL,  -- llamaindex, haystack, crewai, pydanticai, semantickernel
    endpoint TEXT,
    status TEXT DEFAULT 'offline',  -- online, offline, error
    last_ping TEXT,
    tools_json TEXT DEFAULT '[]'
);
```

### Environment Variables

```bash
# MCP Server Configuration
LLAMAINDEX_ENABLED=true
HAYSTACK_ENABLED=true
CREWAI_ENABLED=true
PYDANTICAI_ENABLED=true
SEMANTIC_KERNEL_ENABLED=true

# Observability
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://localhost:3002

# Visualization (optional)
LANGFLOW_URL=http://localhost:7860
FLOWISE_URL=http://localhost:3001
```

## API Endpoints

### Mesh Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mesh/config` | Get mesh configuration |
| PUT | `/api/mesh/config` | Update mesh configuration |
| GET | `/api/mesh/servers` | List MCP server status |
| POST | `/api/mesh/servers/{name}/test` | Test MCP server connection |
| GET | `/api/mesh/visualize` | Get mesh visualization data |

### Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chains/run` | Run chain (tournament/mesh/agent) |
| POST | `/api/chains/run/stream` | Run with SSE streaming |
| GET | `/api/runs/{id}` | Get run result and steps |

### Tournament

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tournaments` | List tournament history |
| GET | `/api/tournaments/{id}` | Get tournament bracket details |

## Safety & Best Practices

### Rate Limiting
- API: 100 requests/minute per project
- Slack: 10 commands/minute per user
- MCP Tools: 50 calls/minute per tool

### Budget Protection
- Daily/weekly/monthly budgets enforced
- Auto-scale-to-zero at 90% budget
- Hard stop at 100% budget

### Input Validation
- All prompts sanitized for prompt injection
- PydanticAI validates all inputs/outputs
- MCP tools have strict schema definitions

### Security
- API keys masked in responses
- Secrets encrypted at rest
- SSH commands timeout-protected

## Observability

### Langfuse Integration
- Trace every node in the mesh
- View latency, cost, and quality metrics
- Debug with detailed span data

### Dashboard Metrics
- Total runs, success rate, average cost
- Per-tier performance comparison
- Model quality rankings

## Quick Start

1. **Configure Providers**: Add API keys in Dashboard → Providers
2. **Set Budgets**: Configure daily/weekly limits in Dashboard → Credits
3. **Test Execution**: Run `!tournament hello` in Slack
4. **View Results**: Check Dashboard → History for execution details
5. **Configure Mesh**: Adjust tiers and modes in Dashboard → Chains

## Advanced: Custom MCP Tools

Register custom MCP tools for your specific needs:

```python
from devplane.infra.mcp_server import server

@server.list_tools()
async def custom_tools():
    return [Tool(
        name="my_custom_tool",
        description="Custom tool description",
        inputSchema={"type": "object", "properties": {...}}
    )]
```
