"""API router — Configuration endpoints for roles, memory, optimizer, tools, and MCP servers."""

import json
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from devplane.db import get_db
from devplane.auth import require_auth

logger = logging.getLogger("devplane.api.config")

router = APIRouter(prefix="/api/config", tags=["config"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class RoleModelsUpdate(BaseModel):
    models: List[str]

class MemoryConfigUpdate(BaseModel):
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    qdrant_url: Optional[str] = None
    qdrant_collection: Optional[str] = None
    max_memory_items: Optional[int] = None
    config_json: Optional[Dict[str, Any]] = None

class OptimizerConfigUpdate(BaseModel):
    complexity_threshold: Optional[float] = None
    scoring_weights_json: Optional[str] = None
    max_iterations: Optional[int] = None
    timeout_seconds: Optional[int] = None
    config_json: Optional[Dict[str, Any]] = None

class ToolConfigUpdate(BaseModel):
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    permissions_json: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None

class MCPServerCreate(BaseModel):
    display_name: str
    server_type: str
    endpoint: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None

class MCPServerSync(BaseModel):
    pass  # no fields needed, just triggers sync


# ─── Role-Model Configuration Endpoints ──────────────────────────────────────

@router.get("/roles")
async def get_role_models(request: Request):
    """Get current role-model mappings."""
    await require_auth(request)
    db = await get_db()
    try:
        rows = await db.execute("SELECT role, models_json FROM role_models ORDER BY role")
        roles = {}
        for row in await rows.fetchall():
            roles[row["role"]] = json.loads(row["models_json"]) if row["models_json"] else []
        return roles
    finally:
        await db.close()

@router.put("/roles/{role}")
async def update_role_models(request: Request, role: str, data: RoleModelsUpdate):
    """Update model list for a role."""
    await require_auth(request)
    db = await get_db()
    try:
        models_json = json.dumps(data.models)
        await db.execute(
            "INSERT OR REPLACE INTO role_models (role, models_json, updated_at) VALUES (?, ?, datetime('now'))",
            (role, models_json)
        )
        await db.commit()
        return {"status": "updated", "role": role, "models": data.models}
    finally:
        await db.close()

@router.post("/roles")
async def create_custom_role(request: Request, data: RoleModelsUpdate):
    """Add a new custom role (optional)."""
    await require_auth(request)
    # For simplicity, we treat PUT as upsert, so POST is same as PUT but requires role in body
    # We'll need a role field in request body.
    # Let's define a separate model.
    # For now, we'll skip; we can implement later.
    raise HTTPException(501, "Not implemented yet")

@router.delete("/roles/{role}")
async def delete_custom_role(request: Request, role: str):
    """Delete a custom role."""
    await require_auth(request)
    db = await get_db()
    try:
        await db.execute("DELETE FROM role_models WHERE role = ?", (role,))
        await db.commit()
        return {"status": "deleted", "role": role}
    finally:
        await db.close()


# ─── Memory Configuration Endpoints ───────────────────────────────────────────

@router.get("/memory")
async def get_memory_config(request: Request):
    """Get current memory configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM memory_config WHERE id = 1")
        config = await row.fetchone()
        if not config:
            # Return defaults
            return {
                "embedding_model": "text-embedding-ada-002",
                "embedding_dimension": 1536,
                "qdrant_url": "http://localhost:6333",
                "qdrant_collection": "devplane_memories",
                "max_memory_items": 1000,
                "config_json": {}
            }
        result = dict(config)
        result["config_json"] = json.loads(result.get("config_json") or "{}")
        return result
    finally:
        await db.close()

@router.put("/memory")
async def update_memory_config(request: Request, data: MemoryConfigUpdate):
    """Update memory configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        for key, value in dump.items():
            if key == "config_json":
                sets.append(f"{key} = ?")
                values.append(json.dumps(value))
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            # Ensure row exists
            await db.execute("INSERT OR IGNORE INTO memory_config (id) VALUES (1)")
            await db.execute(f"UPDATE memory_config SET {', '.join(sets)} WHERE id = 1", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Optimizer Configuration Endpoints ───────────────────────────────────────

@router.get("/optimizer")
async def get_optimizer_config(request: Request):
    """Get optimizer thresholds and scoring weights."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM optimizer_config WHERE id = 1")
        config = await row.fetchone()
        if not config:
            return {
                "complexity_threshold": 0.5,
                "scoring_weights_json": '{"accuracy": 0.4, "cost": 0.3, "speed": 0.3}',
                "max_iterations": 3,
                "timeout_seconds": 30,
                "config_json": {}
            }
        result = dict(config)
        result["scoring_weights_json"] = result.get("scoring_weights_json") or '{}'
        result["config_json"] = json.loads(result.get("config_json") or "{}")
        return result
    finally:
        await db.close()

@router.put("/optimizer")
async def update_optimizer_config(request: Request, data: OptimizerConfigUpdate):
    """Update optimizer configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        for key, value in dump.items():
            if key == "scoring_weights_json" or key == "config_json":
                sets.append(f"{key} = ?")
                values.append(json.dumps(value) if isinstance(value, dict) else value)
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            await db.execute("INSERT OR IGNORE INTO optimizer_config (id) VALUES (1)")
            await db.execute(f"UPDATE optimizer_config SET {', '.join(sets)} WHERE id = 1", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Tool Configuration Endpoints ────────────────────────────────────────────

@router.get("/tools")
async def list_tool_configs(request: Request):
    """List all tools with enabled status, timeouts, permissions."""
    await require_auth(request)
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM tool_config ORDER BY tool_name")
        tools = []
        for row in await rows.fetchall():
            tool = dict(row)
            tool["permissions_json"] = json.loads(tool.get("permissions_json") or "[]")
            tool["config_json"] = json.loads(tool.get("config_json") or "{}")
            tools.append(tool)
        return tools
    finally:
        await db.close()

@router.put("/tools/{tool_name}")
async def update_tool_config(request: Request, tool_name: str, data: ToolConfigUpdate):
    """Update tool configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        for key, value in dump.items():
            if key == "permissions_json" or key == "config_json":
                sets.append(f"{key} = ?")
                values.append(json.dumps(value) if isinstance(value, dict) else value)
            elif key == "enabled":
                sets.append(f"{key} = ?")
                values.append(1 if value else 0)
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            values.append(tool_name)
            await db.execute(
                f"UPDATE tool_config SET {', '.join(sets)} WHERE tool_name = ?",
                values
            )
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── MCP Server Registration Endpoints ───────────────────────────────────────

@router.post("/mcp_servers")
async def register_mcp_server(request: Request, data: MCPServerCreate):
    """Register a new MCP server."""
    await require_auth(request)
    db = await get_db()
    try:
        # Validate server_type enum? Not needed.
        config_json = json.dumps(data.config_json or {})
        await db.execute(
            "INSERT INTO mcp_servers (name, display_name, server_type, endpoint, config_json, status, enabled, tools_json) VALUES (?, ?, ?, ?, ?, 'offline', 1, '[]')",
            (data.display_name.lower().replace(' ', '_'), data.display_name, data.server_type, data.endpoint, config_json)
        )
        await db.commit()
        return {"status": "created", "name": data.display_name.lower().replace(' ', '_')}
    except Exception as e:
        logger.error(f"Failed to register MCP server: {e}")
        raise HTTPException(500, f"Registration failed: {e}")
    finally:
        await db.close()

@router.post("/mcp_servers/{server_name}/sync")
async def sync_mcp_server_tools(request: Request, server_name: str):
    """Fetch tools from the server and update tools_json."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM mcp_servers WHERE name = ?", (server_name,))
        server = await row.fetchone()
        if not server:
            raise HTTPException(404, f"MCP server '{server_name}' not found")
        # TODO: Implement actual MCP server sync (call endpoint, fetch tools)
        # For now, just update with placeholder
        tools = [{"name": "placeholder", "description": "Tool sync not implemented"}]
        tools_json = json.dumps(tools)
        await db.execute(
            "UPDATE mcp_servers SET tools_json = ?, updated_at = datetime('now') WHERE name = ?",
            (tools_json, server_name)
        )
        await db.commit()
        return {"status": "synced", "tools_count": len(tools)}
    finally:
        await db.close()

@router.delete("/mcp_servers/{server_name}")
async def delete_mcp_server(request: Request, server_name: str):
    """Delete a custom MCP server."""
    await require_auth(request)
    db = await get_db()
    try:
        await db.execute("DELETE FROM mcp_servers WHERE name = ?", (server_name,))
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()