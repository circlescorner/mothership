"""DevPlane MCP Server — expose DevPlane as an MCP server for AI IDEs.

Allows Antigravity, PyCharm, VS Code, and other MCP-compatible editors
to invoke DevPlane tools directly: run chains, search memory, deploy, etc.
"""

import os
import json
import logging
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

logger = logging.getLogger("devplane.mcp_server")

server = Server("devplane")


# ─── Tool Definitions ────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools():
    return [
        # Agent Inter-op Tools
        Tool(
            name="ask_kilo_code",
            description="Send a complex coding or heavy lifting task to the Mothership 'worker' role (typically powered by DeepSeek V3 or Qwen 2.5 Coder 32B)",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The coding task or question"},
                    "context": {"type": "string", "description": "Additional context or code snippets (optional)"}
                },
                "required": ["prompt"]
            }
        ),
        Tool(
            name="ask_continue_dev",
            description="Send a rapid autocomplete, refactor, or debugging question to the Mothership 'fast' role (typically powered by LLaMA 3.3 or Cerebras)",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The debugging issue or fast autocomplete prompt"},
                    "context": {"type": "string", "description": "Surrounding code or context (optional)"}
                },
                "required": ["prompt"]
            }
        ),
        Tool(
            name="ask_antigravity",
            description="Consult the Mothership 'architect' role (typically powered by Claude Sonnet 4 or DeepSeek V3) for architectural decisions, system design, or review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The architectural question or design request"},
                    "context": {"type": "string", "description": "Project context or existing architectural decisions (optional)"}
                },
                "required": ["prompt"]
            }
        ),
        
        # Core AI Tools
        Tool(
            name="vibe_code",
            description="Run the God-Mode Mesh pipeline (Architect → Worker → Critic) to generate production code for a task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The coding task to accomplish"},
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="run_chain",
            description="Run the DevPlane AI chain (tournament, mesh, or agent mode).",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The prompt to process"},
                    "mode": {"type": "string", "enum": ["tournament", "mesh", "agent"], "default": "tournament"},
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="search_memory",
            description="Search DevPlane's persistent AI memory for relevant past context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_providers",
            description="List all configured AI providers and their status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_roles",
            description="Get the current role-based model registry with 5-way fallbacks.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="health_check",
            description="Check DevPlane system health and status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        
        # Provider Management Tools
        Tool(
            name="get_provider",
            description="Get details of a specific AI provider by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider_id": {"type": "integer", "description": "Provider ID"},
                },
                "required": ["provider_id"],
            },
        ),
        Tool(
            name="test_provider",
            description="Test connection to an AI provider.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider_id": {"type": "integer", "description": "Provider ID to test"},
                },
                "required": ["provider_id"],
            },
        ),
        Tool(
            name="update_provider",
            description="Update an AI provider's configuration.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider_id": {"type": "integer", "description": "Provider ID"},
                    "api_key": {"type": "string", "description": "New API key (optional)"},
                    "enabled": {"type": "boolean", "description": "Enable/disable provider"},
                    "monthly_budget": {"type": "number", "description": "Monthly budget limit"},
                },
                "required": ["provider_id"],
            },
        ),
        
        # Credits & Budget Tools
        Tool(
            name="get_credit_summary",
            description="Get spending summary for credits and budget tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID (default: 0)"},
                },
            },
        ),
        Tool(
            name="get_usage_history",
            description="Get recent usage history records.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50},
                    "provider": {"type": "string", "description": "Filter by provider name"},
                },
            },
        ),
        Tool(
            name="update_budget",
            description="Update project budget limits.",
            inputSchema={
                "type": "object",
                "properties": {
                    "daily": {"type": "number", "description": "Daily budget limit"},
                    "weekly": {"type": "number", "description": "Weekly budget limit"},
                    "monthly": {"type": "number", "description": "Monthly budget limit"},
                    "project_id": {"type": "integer", "description": "Project ID (default: 0)"},
                },
            },
        ),
        
        # Chain Management Tools
        Tool(
            name="list_chains",
            description="List all configured chains for a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID (default: 0)"},
                },
            },
        ),
        Tool(
            name="get_chain",
            description="Get details of a specific chain including steps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Chain ID"},
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="list_tiers",
            description="List all tiers for a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID"},
                },
                "required": ["project_id"],
            },
        ),
        
        # Project Management Tools
        Tool(
            name="list_projects",
            description="List all projects.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_project",
            description="Get details of a specific project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="create_project",
            description="Create a new project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "description": {"type": "string", "description": "Project description"},
                },
                "required": ["name"],
            },
        ),
        
        # Memory Management Tools
        Tool(
            name="get_memory_history",
            description="Get memory history for a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID (default: 0)"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="get_memory_stats",
            description="Get memory statistics for a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID (default: 0)"},
                },
            },
        ),
        Tool(
            name="clear_memory",
            description="Clear memory for a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID (default: 0)"},
                },
            },
        ),
        
        # Optimizer Tools
        Tool(
            name="get_optimizer_insights",
            description="Get performance insights and recommendations from the optimizer.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_model_recommendations",
            description="Get model recommendations for a specific step type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "step_type": {"type": "string", "description": "Step type (e.g., planner, executor, reviewer)"},
                },
                "required": ["step_type"],
            },
        ),
        
        # Infrastructure Management Tools
        Tool(
            name="infra_status",
            description="Get infrastructure status summary including active droplets, workspaces, and cost estimates.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_droplets",
            description="List all DigitalOcean droplets managed by DevPlane.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_droplet",
            description="Get details of a specific droplet by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "droplet_id": {"type": "integer", "description": "The DigitalOcean droplet ID"},
                },
                "required": ["droplet_id"],
            },
        ),
        Tool(
            name="create_droplet",
            description="Create a new DigitalOcean droplet. Valid sizes: s-1vcpu-1gb, s-1vcpu-2gb, s-2vcpu-4gb, s-4vcpu-8gb, s-8vcpu-16gb, gpu-h100x1-80gb, gpu-h100x8-640gb",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Droplet name (optional, auto-generated if empty)"},
                    "size": {"type": "string", "description": "Droplet size slug (default: s-2vcpu-4gb)"},
                    "droplet_type": {"type": "string", "description": "Type tag: worker, gpu, workspace (default: worker)"},
                    "ttl_minutes": {"type": "integer", "description": "Auto-destroy after N minutes (0 = never, default: 0)"},
                },
            },
        ),
        Tool(
            name="create_worker",
            description="Create an ephemeral worker droplet with auto-expiry. Good for temporary compute tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ttl_minutes": {"type": "integer", "description": "Minutes until auto-destroy (default: 30)"},
                    "size": {"type": "string", "description": "Droplet size (default: s-2vcpu-4gb)"},
                },
            },
        ),
        Tool(
            name="destroy_droplet",
            description="Destroy a DigitalOcean droplet by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "droplet_id": {"type": "integer", "description": "The DigitalOcean droplet ID to destroy"},
                },
                "required": ["droplet_id"],
            },
        ),
        Tool(
            name="list_droplet_sizes",
            description="List all available DigitalOcean droplet sizes with pricing.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_workspace_templates",
            description="List available Kasm workspace templates for browser-based development.",
            inputSchema={"type": "object", "properties": {}},
        ),
        
        # Cloudflare DNS Tools
        Tool(
            name="cloudflare_status",
            description="Get Cloudflare configuration and zone status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_dns_records",
            description="List all DNS records in Cloudflare.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="create_dns_record",
            description="Create a new DNS record in Cloudflare.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Record name (e.g., 'api' for api.example.com)"},
                    "content": {"type": "string", "description": "Record content (IP address or CNAME target)"},
                    "record_type": {"type": "string", "enum": ["A", "AAAA", "CNAME", "TXT", "MX"], "default": "A"},
                    "proxied": {"type": "boolean", "description": "Proxy through Cloudflare (default: true)"},
                },
                "required": ["name", "content"],
            },
        ),
        Tool(
            name="delete_dns_record",
            description="Delete a DNS record from Cloudflare by record ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "The Cloudflare DNS record ID to delete"},
                },
                "required": ["record_id"],
            },
        ),
        
        # GPU Compute Tools
        Tool(
            name="list_gpu_providers",
            description="List available GPU compute providers and their status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="find_cheapest_gpu",
            description="Find the cheapest available GPU with minimum VRAM requirement.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_vram_gb": {"type": "integer", "description": "Minimum VRAM in GB (default: 24)"},
                },
            },
        ),
        
        # Deployment Automation Tools
        Tool(
            name="deploy_to_droplet",
            description="Deploy an application to a new DigitalOcean droplet. Optionally specify git repo and startup script.",
            inputSchema={
                "type": "object",
                "properties": {
                    "droplet_name": {"type": "string", "description": "Name for the deployment droplet (optional, auto-generated)"},
                    "size": {"type": "string", "description": "Droplet size (default: s-2vcpu-4gb)"},
                    "git_repo": {"type": "string", "description": "Git repository URL to clone (optional)"},
                    "branch": {"type": "string", "description": "Git branch to checkout (default: main)"},
                    "startup_script": {"type": "string", "description": "Custom startup script to run (optional)"},
                    "ttl_minutes": {"type": "integer", "description": "Auto-destroy after N minutes (default: 0 = never)"},
                },
            },
        ),
        Tool(
            name="run_ssh_command",
            description="Run a shell command on an active DigitalOcean droplet via SSH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "droplet_id": {"type": "integer", "description": "The DigitalOcean droplet ID"},
                    "command": {"type": "string", "description": "The shell command to execute"},
                },
                "required": ["droplet_id", "command"],
            },
        ),
        Tool(
            name="create_sandbox",
            description="Create a firewalled sandbox droplet for running untrusted code.",
            inputSchema={
                "type": "object",
                "properties": {
                    "size": {"type": "string", "description": "Droplet size (default: s-1vcpu-2gb)"},
                    "ttl_minutes": {"type": "integer", "description": "Auto-destroy after N minutes (default: 0 = never)"},
                    "system_type": {"type": "string", "enum": ["basic", "docker", "kubernetes"], "default": "basic", "description": "System type to install (basic, docker, kubernetes)"},
                },
            },
        ),
        Tool(
            name="run_sandbox_script",
            description="Run a script in a sandbox droplet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "droplet_id": {"type": "integer", "description": "The DigitalOcean droplet ID"},
                    "script_content": {"type": "string", "description": "The script content to execute"},
                    "lang": {"type": "string", "enum": ["python", "bash"], "default": "python", "description": "Script language"},
                },
                "required": ["droplet_id", "script_content"],
            },
        ),
        Tool(
            name="destroy_sandbox",
            description="Destroy a sandbox droplet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "droplet_id": {"type": "integer", "description": "The DigitalOcean droplet ID"},
                },
                "required": ["droplet_id"],
            },
        ),
    ]

    # Dynamically inject IDE-specific agent workflows from the registry
    from devplane.db import get_db
    try:
        db = await get_db()
        rows = await db.execute("SELECT * FROM agent_workflows WHERE is_active = 1")
        for row in await rows.fetchall():
            try:
                schema = json.loads(row["input_schema"] or "{}")
                # Fix schema structure if missing wrapper
                if "type" not in schema:
                    schema = {"type": "object", "properties": schema}
                    
                tools.append(
                    Tool(
                        name=row["agent_name"].replace(" ", "_").lower(),
                        description=f"[{row['ide_name']}] {row['description']}",
                        inputSchema=schema
                    )
                )
            except Exception as e:
                logger.error(f"Failed to parse schema for agent {row['agent_name']}: {e}")
    except Exception as e:
        logger.error(f"Failed to load dynamic agent tools: {e}")
    finally:
        if 'db' in locals() and db:
            await db.close()
            
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        # ── Check for Dynamic Cross-IDE Agent Tools First ──
        from devplane.db import get_db
        db_check = await get_db()
        try:
            row = await db_check.execute("SELECT * FROM agent_workflows WHERE REPLACE(LOWER(agent_name), ' ', '_') = ?", (name,))
            agent_record = await row.fetchone()
        finally:
            await db_check.close()
            
        if agent_record:
            # Route to Cross-IDE execution bridge (Database Polling Queue)
            import asyncio
            import json
            payload = json.dumps(arguments)
            db = await get_db()
            try:
                # Insert task
                cursor = await db.execute(
                    "INSERT INTO devplane_tasks (agent_name, payload_json, status) VALUES (?, ?, 'pending')",
                    (agent_record["agent_name"], payload)
                )
                await db.commit()
                task_id = cursor.lastrowid
                
                # Wait for result (timeout 120s for complex agents)
                for _ in range(120):
                    await asyncio.sleep(1)
                    poll = await db.execute("SELECT status, result_json, error_message FROM devplane_tasks WHERE id = ?", (task_id,))
                    res = await poll.fetchone()
                    if res["status"] == "completed":
                        return [TextContent(type="text", text=res["result_json"] or "Success")]
                    elif res["status"] == "error":
                        return [TextContent(type="text", text=f"Agent Error: {res['error_message']}")]
                        
                # If we get here, it timed out
                await db.execute("UPDATE devplane_tasks SET status = 'timeout' WHERE id = ?", (task_id,))
                await db.commit()
                return [TextContent(type="text", text=f"Error: Task assigned to {agent_record['ide_name']} '{agent_record['agent_name']}' agent timed out after 120 seconds. Make sure the target IDE is running and connected.")]
            finally:
                await db.close()

        # ── Standard Native Tools ──
        if name in ["ask_kilo_code", "ask_continue_dev", "ask_antigravity"]:
            from devplane.roles import call_with_fallback, load_from_db
            from devplane.db import init_db
            from devplane.providers import load_all_keys_to_env
            
            prompt = arguments.get("prompt")
            if not prompt:
                return [TextContent(type="text", text="Error: Missing 'prompt' argument")]
                
            context = arguments.get("context", "")
            
            role_map = {
                "ask_kilo_code": "worker",
                "ask_continue_dev": "fast",
                "ask_antigravity": "architect"
            }
            
            role = role_map[name]
            
            system_prompt = (
                f"You are the {role} AI agent within the Mothership DevPlane mesh. "
                "You are being invoked via the Model Context Protocol (MCP) by a peer AI extension "
                "(like Antigravity, Kilo Code, or Continue.dev). Help them accomplish their task by "
                "providing specialized expertise."
            )
            
            user_content = prompt
            if context:
                user_content = f"[Context]\n{context}\n\n[Task]\n{prompt}"
                
            await load_all_keys_to_env()
            await init_db()
            await load_from_db()
            
            result = await call_with_fallback(
                role=role,
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=0.2,
                project_id=0
            )
            
            response_text = result.get("content", f"Error: No content returned. Result: {result}")
            model_used = result.get("model", "unknown")
            cost = result.get("cost", 0.0)
            
            final_response = (
                f"🚀 [DevPlane Proxy via {model_used} | Role: {role} | Cost: ${cost:.5f}]\n\n"
                f"{response_text}"
            )
            return [TextContent(type="text", text=final_response)]

        elif name == "vibe_code":
            from devplane.chain.mesh import run_mesh
            result = await run_mesh(arguments["task"])
            return [TextContent(
                type="text",
                text=json.dumps({
                    "code": result.get("code", ""),
                    "plan": result.get("plan", ""),
                    "feedback": result.get("feedback", ""),
                    "iterations": result.get("iterations", 0),
                    "cost": result.get("total_cost", 0),
                }, indent=2)
            )]

        elif name == "run_chain":
            from devplane.chain.engine import run_tournament
            from devplane.db import get_default_project_id
            project_id = await get_default_project_id()
            mode = arguments.get("mode", "tournament")
            result = await run_tournament(arguments["prompt"], project_id, mode=mode)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "output": result.get("final_output", "")[:4000],
                    "tier": result.get("winning_tier", ""),
                    "cost": result.get("total_cost", 0),
                    "status": result.get("status", ""),
                }, indent=2)
            )]

        elif name == "search_memory":
            from devplane.memory.store import search_memory
            results = await search_memory(arguments["query"], limit=arguments.get("limit", 10))
            return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]

        elif name == "list_providers":
            from devplane.providers import get_all_providers
            providers = await get_all_providers()
            # Mask API keys
            for p in providers:
                if p.get("api_key"):
                    p["api_key"] = p["api_key"][:8] + "..."
            return [TextContent(type="text", text=json.dumps(providers, indent=2, default=str))]

        elif name == "get_roles":
            from devplane.roles import get_all_roles
            return [TextContent(type="text", text=json.dumps(get_all_roles(), indent=2))]

        elif name == "health_check":
            return [TextContent(type="text", text=json.dumps({
                "status": "DevPlane Online",
                "version": "2.0.0-godmode",
                "modes": ["tournament", "mesh", "agent"],
            }, indent=2))]

        # Provider Management Tools
        elif name == "get_provider":
            from devplane.providers import get_provider
            p = await get_provider(arguments["provider_id"])
            if p and p.get("api_key"):
                p["api_key"] = p["api_key"][:8] + "..."
            return [TextContent(type="text", text=json.dumps(p, indent=2, default=str))]

        elif name == "test_provider":
            from devplane.providers import test_provider_connection
            result = await test_provider_connection(arguments["provider_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "update_provider":
            from devplane.providers import update_provider
            kwargs = {k: v for k, v in arguments.items() if k != "provider_id" and v is not None}
            await update_provider(arguments["provider_id"], **kwargs)
            return [TextContent(type="text", text=json.dumps({"status": "updated"}, indent=2))]

        # Credits & Budget Tools
        elif name == "get_credit_summary":
            from devplane.credits import get_credit_summary
            from devplane.db import get_default_project_id
            project_id = arguments.get("project_id", 0) or await get_default_project_id()
            return [TextContent(type="text", text=json.dumps(await get_credit_summary(project_id), indent=2, default=str))]

        elif name == "get_usage_history":
            from devplane.db import get_db
            db = await get_db()
            try:
                limit = arguments.get("limit", 50)
                provider = arguments.get("provider", "")
                query = "SELECT * FROM usage ORDER BY created_at DESC LIMIT ?"
                params = [limit]
                if provider:
                    query = "SELECT * FROM usage WHERE provider_name = ? ORDER BY created_at DESC LIMIT ?"
                    params = [provider, limit]
                rows = await db.execute(query, params)
                return [TextContent(type="text", text=json.dumps([dict(r) for r in await rows.fetchall()], indent=2, default=str))]
            finally:
                await db.close()

        elif name == "update_budget":
            from devplane.db import get_db, get_default_project_id
            project_id = arguments.get("project_id", 0) or await get_default_project_id()
            db = await get_db()
            try:
                sets = []
                values = []
                for key in ["daily", "weekly", "monthly"]:
                    if key in arguments and arguments[key] is not None:
                        sets.append(f"{key}_budget = ?")
                        values.append(arguments[key])
                if sets:
                    values.append(project_id)
                    await db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", values)
                    await db.commit()
                return [TextContent(type="text", text=json.dumps({"status": "updated"}, indent=2))]
            finally:
                await db.close()

        # Chain Management Tools
        elif name == "list_chains":
            from devplane.db import get_db, get_default_project_id
            import json
            project_id = arguments.get("project_id", 0) or await get_default_project_id()
            db = await get_db()
            try:
                rows = await db.execute("SELECT * FROM chains WHERE project_id = ?", (project_id,))
                chains = [dict(r) for r in await rows.fetchall()]
                for c in chains:
                    c["parallel_tiers"] = json.loads(c["parallel_tiers"]) if c.get("parallel_tiers") else []
                return [TextContent(type="text", text=json.dumps(chains, indent=2, default=str))]
            finally:
                await db.close()

        elif name == "get_chain":
            from devplane.db import get_db
            import json
            db = await get_db()
            try:
                row = await db.execute("SELECT * FROM chains WHERE id = ?", (arguments["chain_id"],))
                chain = await row.fetchone()
                if not chain:
                    return [TextContent(type="text", text=json.dumps({"error": "Chain not found"}, indent=2))]
                result = dict(chain)
                result["parallel_tiers"] = json.loads(result["parallel_tiers"]) if result.get("parallel_tiers") else []
                steps_rows = await db.execute("SELECT * FROM chain_steps WHERE chain_id = ? ORDER BY step_order", (arguments["chain_id"],))
                result["steps"] = [dict(s) for s in await steps_rows.fetchall()]
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
            finally:
                await db.close()

        elif name == "list_tiers":
            from devplane.db import get_db
            db = await get_db()
            try:
                rows = await db.execute("SELECT * FROM tiers WHERE project_id = ? ORDER BY level", (arguments["project_id"],))
                return [TextContent(type="text", text=json.dumps([dict(r) for r in await rows.fetchall()], indent=2, default=str))]
            finally:
                await db.close()

        # Project Management Tools
        elif name == "list_projects":
            from devplane.db import get_db
            db = await get_db()
            try:
                rows = await db.execute("SELECT * FROM projects ORDER BY created_at DESC")
                return [TextContent(type="text", text=json.dumps([dict(r) for r in await rows.fetchall()], indent=2, default=str))]
            finally:
                await db.close()

        elif name == "get_project":
            from devplane.db import get_db
            db = await get_db()
            try:
                row = await db.execute("SELECT * FROM projects WHERE id = ?", (arguments["project_id"],))
                project = await row.fetchone()
                return [TextContent(type="text", text=json.dumps(dict(project) if project else {"error": "Project not found"}, indent=2, default=str))]
            finally:
                await db.close()

        elif name == "create_project":
            from devplane.db import get_db
            db = await get_db()
            try:
                cursor = await db.execute(
                    "INSERT INTO projects (name, description) VALUES (?, ?)",
                    (arguments["name"], arguments.get("description", ""))
                )
                await db.commit()
                return [TextContent(type="text", text=json.dumps({"id": cursor.lastrowid, "status": "created"}, indent=2))]
            finally:
                await db.close()

        # Memory Management Tools
        elif name == "get_memory_history":
            from devplane.memory.store import get_history
            project_id = arguments.get("project_id", 0) or 0
            limit = arguments.get("limit", 20)
            return [TextContent(type="text", text=json.dumps(await get_history(project_id, limit), indent=2, default=str))]

        elif name == "get_memory_stats":
            from devplane.memory.store import get_memory_stats
            project_id = arguments.get("project_id", 0) or 0
            return [TextContent(type="text", text=json.dumps(await get_memory_stats(project_id), indent=2, default=str))]

        elif name == "clear_memory":
            from devplane.memory.store import clear_memory
            project_id = arguments.get("project_id", 0) or 0
            return [TextContent(type="text", text=json.dumps(await clear_memory(project_id), indent=2, default=str))]

        # Optimizer Tools
        elif name == "get_optimizer_insights":
            from devplane.chain.optimizer import get_insights
            return [TextContent(type="text", text=json.dumps(await get_insights(), indent=2, default=str))]

        elif name == "get_model_recommendations":
            from devplane.chain.optimizer import recommend_models
            models = await recommend_models(arguments["step_type"])
            return [TextContent(type="text", text=json.dumps({"step_type": arguments["step_type"], "recommended_models": models}, indent=2))]

        # Infrastructure Management Tools
        elif name == "infra_status":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            return [TextContent(type="text", text=json.dumps(await mgr.get_infra_summary(), indent=2))]

        elif name == "list_droplets":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            droplets = await mgr.list_droplets()
            return [TextContent(type="text", text=json.dumps(droplets, indent=2, default=str))]

        elif name == "get_droplet":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            droplet = await mgr.get_droplet(arguments["droplet_id"])
            return [TextContent(type="text", text=json.dumps(droplet, indent=2, default=str))]

        elif name == "create_droplet":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            if not mgr.configured:
                return [TextContent(type="text", text=json.dumps({"error": "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN."}, indent=2))]
            result = await mgr.create_droplet(
                name=arguments.get("name", ""),
                size=arguments.get("size", "s-2vcpu-4gb"),
                droplet_type=arguments.get("droplet_type", "worker"),
                ttl_minutes=arguments.get("ttl_minutes", 0)
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "create_worker":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            if not mgr.configured:
                return [TextContent(type="text", text=json.dumps({"error": "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN."}, indent=2))]
            result = await mgr.create_worker(
                ttl_minutes=arguments.get("ttl_minutes", 30),
                size=arguments.get("size", "s-2vcpu-4gb")
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "destroy_droplet":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            if not mgr.configured:
                return [TextContent(type="text", text=json.dumps({"error": "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN."}, indent=2))]
            result = await mgr.destroy_droplet(arguments["droplet_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "list_droplet_sizes":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            sizes = mgr.get_size_catalog()
            return [TextContent(type="text", text=json.dumps(sizes, indent=2))]

        elif name == "list_workspace_templates":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            templates = mgr.get_workspace_templates()
            return [TextContent(type="text", text=json.dumps(templates, indent=2))]

        # Cloudflare DNS Tools
        elif name == "cloudflare_status":
            from devplane.infra.cloudflare import get_cloudflare_manager
            cf = get_cloudflare_manager()
            zone_info = await cf.get_zone_info() if cf.configured else {"error": "Not configured"}
            return [TextContent(type="text", text=json.dumps({
                "configured": cf.configured,
                "domain": cf.domain,
                "zone": zone_info,
            }, indent=2))]

        elif name == "list_dns_records":
            from devplane.infra.cloudflare import get_cloudflare_manager
            cf = get_cloudflare_manager()
            if not cf.configured:
                return [TextContent(type="text", text=json.dumps({"error": "Cloudflare not configured"}, indent=2))]
            records = await cf.list_dns_records()
            return [TextContent(type="text", text=json.dumps(records, indent=2, default=str))]

        elif name == "create_dns_record":
            from devplane.infra.cloudflare import get_cloudflare_manager
            cf = get_cloudflare_manager()
            if not cf.configured:
                return [TextContent(type="text", text=json.dumps({"error": "Cloudflare not configured"}, indent=2))]
            result = await cf.create_dns_record(
                arguments["name"],
                arguments["content"],
                arguments.get("record_type", "A"),
                arguments.get("proxied", True)
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "delete_dns_record":
            from devplane.infra.cloudflare import get_cloudflare_manager
            cf = get_cloudflare_manager()
            if not cf.configured:
                return [TextContent(type="text", text=json.dumps({"error": "Cloudflare not configured"}, indent=2))]
            result = await cf.delete_dns_record(arguments["record_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        # GPU Compute Tools
        elif name == "list_gpu_providers":
            from devplane.infra.gpu import get_gpu_arsenal
            arsenal = get_gpu_arsenal()
            return [TextContent(type="text", text=json.dumps({
                "configured": arsenal.configured,
                "providers": arsenal.list_providers(),
            }, indent=2))]

        elif name == "find_cheapest_gpu":
            from devplane.infra.gpu import get_gpu_arsenal
            arsenal = get_gpu_arsenal()
            result = await arsenal.find_cheapest_gpu(arguments.get("min_vram_gb", 24))
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        # Deployment Automation Tools
        elif name == "deploy_to_droplet":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            if not mgr.configured:
                return [TextContent(type="text", text=json.dumps({"error": "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN."}, indent=2))]
            
            import secrets
            droplet_name = arguments.get("droplet_name") or f"deploy-{secrets.token_hex(4)}"
            size = arguments.get("size", "s-2vcpu-4gb")
            git_repo = arguments.get("git_repo", "")
            branch = arguments.get("branch", "main")
            startup_script = arguments.get("startup_script", "")
            ttl_minutes = arguments.get("ttl_minutes", 0)
            
            # Build user_data script
            user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker root
systemctl enable docker

mkdir -p /srv/devplane
hostnamectl set-hostname {droplet_name}
"""
            
            if git_repo:
                user_data += f"""
# Install git and clone repository
apt-get install -y git
cd /srv/devplane
git clone {git_repo} .
git checkout {branch}
"""
            
            if startup_script:
                user_data += f"""
# Custom startup script
cat > /srv/devplane/startup.sh << 'EOF'
{startup_script}
EOF
chmod +x /srv/devplane/startup.sh
"""
            
            user_data += f"""
echo "Deployment droplet {droplet_name} ready"
"""
            
            result = await mgr.create_droplet(
                name=droplet_name,
                size=size,
                droplet_type="deploy",
                ttl_minutes=ttl_minutes,
                user_data=user_data
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "run_ssh_command":
            from devplane.infra.manager import get_infra_manager
            import paramiko
            import os
            
            mgr = get_infra_manager()
            if not mgr.configured:
                return [TextContent(type="text", text=json.dumps({"error": "DigitalOcean not configured."}, indent=2))]
                
            droplet = await mgr.get_droplet(arguments["droplet_id"])
            if not droplet or "error" in droplet:
                return [TextContent(type="text", text=json.dumps({"error": "Droplet not found."}, indent=2))]
                
            ip_address = None
            for network in droplet.get("networks", {}).get("v4", []):
                if network.get("type") == "public":
                    ip_address = network.get("ip_address")
                    break
                    
            if not ip_address:
                return [TextContent(type="text", text=json.dumps({"error": "Droplet does not have a public IP."}, indent=2))]
                
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                key_path = os.path.expanduser("~/.ssh/id_rsa")
                print(f"Connecting to {ip_address}...")
                client.connect(hostname=ip_address, username="root", key_filename=key_path, timeout=10)
                
                stdin, stdout, stderr = client.exec_command(arguments["command"], timeout=60)
                exit_code = stdout.channel.recv_exit_status()
                stdout_data = stdout.read().decode('utf-8', errors='replace')
                stderr_data = stderr.read().decode('utf-8', errors='replace')
                client.close()
                
                return [TextContent(type="text", text=json.dumps({
                    "exit_code": exit_code,
                    "stdout": stdout_data,
                    "stderr": stderr_data
                }, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({"error": f"SSH connection failed: {str(e)}"}, indent=2))]

        elif name == "create_sandbox":
            from devplane.infra.sandbox import get_sandbox_manager
            sandbox = get_sandbox_manager()
            result = await sandbox.create_firewalled_sandbox()
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "run_sandbox_script":
            from devplane.infra.sandbox import get_sandbox_manager
            sandbox = get_sandbox_manager()
            droplet_id = arguments.get("droplet_id")
            script_content = arguments.get("script_content")
            lang = arguments.get("lang", "python")
            # Need droplet IP
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            droplet = await mgr.get_droplet(droplet_id)
            if not droplet or "error" in droplet:
                return [TextContent(type="text", text=json.dumps({"error": "Droplet not found."}, indent=2))]
            ip_address = None
            for network in droplet.get("networks", {}).get("v4", []):
                if network.get("type") == "public":
                    ip_address = network.get("ip_address")
                    break
            if not ip_address:
                return [TextContent(type="text", text=json.dumps({"error": "Droplet does not have a public IP."}, indent=2))]
            result = await sandbox.execute_in_sandbox(ip_address, script_content, lang)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "destroy_sandbox":
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            result = await mgr.destroy_droplet(arguments["droplet_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error(f"MCP tool error ({name}): {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ─── Entry Point ─────────────────────────────────────────────────────────────

async def run_mcp_server():
    """Run the MCP server via stdio (for IDE connections)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
