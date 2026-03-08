"""API router — Unified Agentic Mesh configuration and visualization."""

import json
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from devplane.db import get_db
from devplane.auth import require_auth

logger = logging.getLogger("devplane.api.mesh")

def safe_json_loads(s, default=None):
    """Safely parse JSON string, returning default on failure."""
    if not s:
        return default if default is not None else ([] if isinstance(default, list) else {})
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON: {s[:50]}")
        return default if default is not None else ([] if isinstance(default, list) else {})

router = APIRouter(prefix="/api/mesh", tags=["mesh"])


# ─── Request Models ───────────────────────────────────────────────────────────

class MeshConfigUpdate(BaseModel):
    name: Optional[str] = None
    execution_mode: Optional[str] = None
    mcp_servers_enabled: Optional[List[str]] = None
    default_tier: Optional[str] = None
    max_iterations: Optional[int] = None
    timeout_seconds: Optional[int] = None
    config_json: Optional[Dict[str, Any]] = None


class MCPServerUpdate(BaseModel):
    endpoint: Optional[str] = None
    enabled: Optional[bool] = None
    config_json: Optional[Dict[str, Any]] = None


class MeshRouteUpdate(BaseModel):
    keyword: Optional[str] = None
    mcp_server: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class MeshVisualizationUpdate(BaseModel):
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    config_json: Optional[Dict[str, Any]] = None


class MeshRoleConfigUpdate(BaseModel):
    role_name: Optional[str] = None
    model_slug: Optional[str] = None
    iteration_limit: Optional[int] = None
    timeout_seconds: Optional[int] = None
    config_json: Optional[Dict[str, Any]] = None


# ─── Mesh Configuration Endpoints ─────────────────────────────────────────────

@router.get("/config")
async def get_mesh_config(request: Request):
    """Get the current mesh configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM mesh_configs WHERE is_active = 1 LIMIT 1")
        config = await row.fetchone()
        if not config:
            # Create default if not exists
            await db.execute("""
                INSERT INTO mesh_configs (name, execution_mode, mcp_servers_enabled, default_tier, max_iterations, timeout_seconds)
                VALUES ('Default Mesh', 'tournament', '["llamaindex", "haystack", "crewai", "pydanticai", "semantickernel"]', 'mid', 3, 60)
            """)
            await db.commit()
            row = await db.execute("SELECT * FROM mesh_configs WHERE is_active = 1 LIMIT 1")
            config = await row.fetchone()
        
        result = dict(config)
        result["mcp_servers_enabled"] = safe_json_loads(result.get("mcp_servers_enabled"), default=[])
        result["config_json"] = safe_json_loads(result.get("config_json"), default={})
        
        # Fetch role configurations
        role_rows = await db.execute(
            "SELECT * FROM mesh_role_config WHERE mesh_config_id = ? ORDER BY role_name",
            (result["id"],)
        )
        role_configs = []
        async for role_row in role_rows:
            role = dict(role_row)
            role["config_json"] = safe_json_loads(role.get("config_json"), default={})
            role_configs.append(role)
        result["role_configs"] = role_configs
        
        return result
    finally:
        await db.close()


@router.put("/config")
async def update_mesh_config(request: Request, data: MeshConfigUpdate):
    """Update the mesh configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        
        for key, value in dump.items():
            if key == "mcp_servers_enabled" or key == "config_json":
                sets.append(f"{key} = ?")
                values.append(json.dumps(value))
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        
        if sets:
            sets.append("updated_at = datetime('now')")
            await db.execute(f"UPDATE mesh_configs SET {', '.join(sets)} WHERE is_active = 1", values)
            await db.commit()
        
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Mesh Role Configuration Endpoints ───────────────────────────────────────

@router.get("/config/roles")
async def list_mesh_role_configs(request: Request):
    """List all role configurations for the active mesh config."""
    await require_auth(request)
    db = await get_db()
    try:
        # Get active mesh config id
        row = await db.execute("SELECT id FROM mesh_configs WHERE is_active = 1 LIMIT 1")
        config = await row.fetchone()
        if not config:
            raise HTTPException(404, "No active mesh configuration found")
        mesh_config_id = config["id"]
        
        rows = await db.execute(
            "SELECT * FROM mesh_role_config WHERE mesh_config_id = ? ORDER BY role_name",
            (mesh_config_id,)
        )
        roles = []
        async for row in rows:
            role = dict(row)
            role["config_json"] = safe_json_loads(role.get("config_json"), default={})
            roles.append(role)
        return roles
    finally:
        await db.close()


@router.get("/config/roles/{role_name}")
async def get_mesh_role_config(request: Request, role_name: str):
    """Get a specific role configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT * FROM mesh_role_config WHERE mesh_config_id = (SELECT id FROM mesh_configs WHERE is_active = 1 LIMIT 1) AND role_name = ?",
            (role_name,)
        )
        role = await row.fetchone()
        if not role:
            raise HTTPException(404, f"Role configuration '{role_name}' not found")
        result = dict(role)
        result["config_json"] = safe_json_loads(result.get("config_json"), default={})
        return result
    finally:
        await db.close()


@router.put("/config/roles/{role_name}")
async def update_mesh_role_config(request: Request, role_name: str, data: MeshRoleConfigUpdate):
    """Update or create a role configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        # Get active mesh config id
        row = await db.execute("SELECT id FROM mesh_configs WHERE is_active = 1 LIMIT 1")
        config = await row.fetchone()
        if not config:
            raise HTTPException(404, "No active mesh configuration found")
        mesh_config_id = config["id"]
        
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
            # Check if exists
            check = await db.execute(
                "SELECT 1 FROM mesh_role_config WHERE mesh_config_id = ? AND role_name = ?",
                (mesh_config_id, role_name)
            )
            exists = await check.fetchone()
            if exists:
                # Update
                values.append(mesh_config_id)
                values.append(role_name)
                await db.execute(
                    f"UPDATE mesh_role_config SET {', '.join(sets)} WHERE mesh_config_id = ? AND role_name = ?",
                    values
                )
            else:
                # Insert
                sets.append("mesh_config_id")
                sets.append("role_name")
                values.append(mesh_config_id)
                values.append(role_name)
                await db.execute(
                    f"INSERT INTO mesh_role_config ({', '.join(sets)}) VALUES ({', '.join(['?'] * len(values))})",
                    values
                )
            await db.commit()
        
        return {"status": "updated" if exists else "created"}
    finally:
        await db.close()


@router.delete("/config/roles/{role_name}")
async def delete_mesh_role_config(request: Request, role_name: str):
    """Delete a role configuration."""
    await require_auth(request)
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM mesh_role_config WHERE mesh_config_id = (SELECT id FROM mesh_configs WHERE is_active = 1 LIMIT 1) AND role_name = ?",
            (role_name,)
        )
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()


# ─── MCP Server Endpoints ─────────────────────────────────────────────────────

@router.get("/servers")
async def list_mcp_servers(request: Request):
    """List all MCP servers and their status."""
    await require_auth(request)
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM mcp_servers ORDER BY display_name")
        servers = []
        for row in await rows.fetchall():
            server = dict(row)
            server["tools_json"] = safe_json_loads(server.get("tools_json"), default=[])
            server["config_json"] = safe_json_loads(server.get("config_json"), default={})
            servers.append(server)
        return servers
    finally:
        await db.close()


@router.get("/servers/{server_name}")
async def get_mcp_server(request: Request, server_name: str):
    """Get a specific MCP server."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM mcp_servers WHERE name = ?", (server_name,))
        server = await row.fetchone()
        if not server:
            raise HTTPException(404, f"MCP server '{server_name}' not found")
        
        result = dict(server)
        result["tools_json"] = safe_json_loads(result.get("tools_json"), default=[])
        result["config_json"] = safe_json_loads(result.get("config_json"), default={})
        return result
    finally:
        await db.close()


@router.put("/servers/{server_name}")
async def update_mcp_server(request: Request, server_name: str, data: MCPServerUpdate):
    """Update an MCP server configuration."""
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
            elif key == "enabled":
                sets.append(f"{key} = ?")
                values.append(1 if value else 0)
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        
        if sets:
            sets.append("updated_at = datetime('now')")
            values.append(server_name)
            await db.execute(f"UPDATE mcp_servers SET {', '.join(sets)} WHERE name = ?", values)
            await db.commit()
        
        return {"status": "updated"}
    finally:
        await db.close()


@router.post("/servers/{server_name}/test")
async def test_mcp_server(request: Request, server_name: str):
    """Test connection to an MCP server."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM mcp_servers WHERE name = ?", (server_name,))
        server = await row.fetchone()
        if not server:
            raise HTTPException(404, f"MCP server '{server_name}' not found")
        
        # For now, return a mock test result
        # In production, this would actually test the MCP server connection
        return {
            "server": server_name,
            "status": "online",
            "message": f"MCP server '{server['display_name']}' is configured",
            "tools_count": len(safe_json_loads(server.get("tools_json"), default=[]))
        }
    finally:
        await db.close()


# ─── Mesh Routes Endpoints ───────────────────────────────────────────────────

@router.get("/routes")
async def list_mesh_routes(request: Request):
    """List all mesh routing rules."""
    await require_auth(request)
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM mesh_routes ORDER BY priority DESC, keyword")
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


@router.put("/routes/{route_id}")
async def update_mesh_route(request: Request, route_id: int, data: MeshRouteUpdate):
    """Update a mesh routing rule."""
    await require_auth(request)
    db = await get_db()
    try:
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        
        for key, value in dump.items():
            if key == "is_active":
                sets.append(f"{key} = ?")
                values.append(1 if value else 0)
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        
        if sets:
            values.append(route_id)
            await db.execute(f"UPDATE mesh_routes SET {', '.join(sets)} WHERE id = ?", values)
            await db.commit()
        
        return {"status": "updated"}
    finally:
        await db.close()


@router.post("/routes")
async def create_mesh_route(request: Request, data: MeshRouteUpdate):
    """Create a new mesh routing rule."""
    await require_auth(request)
    db = await get_db()
    try:
        if not data.keyword or not data.mcp_server:
            raise HTTPException(400, "keyword and mcp_server are required")
        
        cursor = await db.execute(
            "INSERT INTO mesh_routes (keyword, mcp_server, priority, is_active) VALUES (?, ?, ?, 1)",
            (data.keyword, data.mcp_server, data.priority or 0)
        )
        await db.commit()
        
        return {"id": cursor.lastrowid, "status": "created"}
    finally:
        await db.close()


@router.delete("/routes/{route_id}")
async def delete_mesh_route(request: Request, route_id: int):
    """Delete a mesh routing rule."""
    await require_auth(request)
    db = await get_db()
    try:
        await db.execute("DELETE FROM mesh_routes WHERE id = ?", (route_id,))
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()


# ─── Visualization Endpoints ─────────────────────────────────────────────────

@router.get("/visualize")
async def get_mesh_visualization(request: Request):
    """Get mesh visualization data for the dashboard."""
    await require_auth(request)
    db = await get_db()
    try:
        # Get all visualization nodes
        rows = await db.execute("SELECT * FROM mesh_visualization")
        nodes = []
        for row in await rows.fetchall():
            node = dict(row)
            node["config_json"] = safe_json_loads(node.get("config_json"), default={})
            nodes.append(node)
        
        # Get mesh config
        config_row = await db.execute("SELECT * FROM mesh_configs WHERE is_active = 1 LIMIT 1")
        config = await config_row.fetchone()
        
        # Get MCP servers status
        servers_row = await db.execute("SELECT name, display_name, status, enabled FROM mcp_servers")
        servers = [dict(r) for r in await servers_row.fetchall()]
        
        return {
            "nodes": nodes,
            "config": {
                "execution_mode": config["execution_mode"] if config else "tournament",
                "default_tier": config["default_tier"] if config else "mid",
                "max_iterations": config["max_iterations"] if config else 3,
            } if config else {},
            "servers": servers,
            "edges": [
                {"from": "planner", "to": "executor"},
                {"from": "executor", "to": "reviewer"},
                {"from": "reviewer", "to": "judge"},
            ]
        }
    finally:
        await db.close()


@router.put("/visualize/{node_id}")
async def update_visualization_node(request: Request, node_id: str, data: MeshVisualizationUpdate):
    """Update a visualization node position."""
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
            values.append(node_id)
            await db.execute(f"UPDATE mesh_visualization SET {', '.join(sets)} WHERE node_id = ?", values)
            await db.commit()
        
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Tournament History Endpoints ────────────────────────────────────────────

@router.get("/tournaments")
async def list_tournaments(request: Request, limit: int = 20):
    """List tournament history."""
    await require_auth(request)
    db = await get_db()
    try:
        rows = await db.execute("""
            SELECT tb.*, r.prompt, r.winning_tier, r.total_cost, r.status
            FROM tournament_brackets tb
            LEFT JOIN runs r ON tb.run_id = r.id
            ORDER BY tb.created_at DESC
            LIMIT ?
        """, (limit,))
        tournaments = []
        for row in await rows.fetchall():
            t = dict(row)
            t["tier_results"] = safe_json_loads(t.get("tier_results"), default=[])
            t["cost_per_tier"] = safe_json_loads(t.get("cost_per_tier"), default={})
            tournaments.append(t)
        return tournaments
    finally:
        await db.close()


@router.get("/tournaments/{tournament_id}")
async def get_tournament(request: Request, tournament_id: int):
    """Get a specific tournament bracket."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("""
            SELECT tb.*, r.prompt, r.winning_tier, r.total_cost, r.status
            FROM tournament_brackets tb
            LEFT JOIN runs r ON tb.run_id = r.id
            WHERE tb.id = ?
        """, (tournament_id,))
        tournament = await row.fetchone()
        if not tournament:
            raise HTTPException(404, "Tournament not found")
        
        result = dict(tournament)
        result["tier_results"] = safe_json_loads(result.get("tier_results"), default=[])
        result["cost_per_tier"] = safe_json_loads(result.get("cost_per_tier"), default={})
        return result
    finally:
        await db.close()


# ─── Mesh Routing Helper ─────────────────────────────────────────────────────

async def route_to_mcp_server(query: str) -> List[str]:
    """Route a query to appropriate MCP servers based on keywords."""
    db = await get_db()
    try:
        query_lower = query.lower()
        matched_servers = []
        
        rows = await db.execute("""
            SELECT mcp_server, keyword FROM mesh_routes 
            WHERE is_active = 1 ORDER BY priority DESC
        """)
        
        for row in await rows.fetchall():
            if row["keyword"].lower() in query_lower:
                if row["mcp_server"] not in matched_servers:
                    matched_servers.append(row["mcp_server"])
        
        # Always include crewai for orchestration
        if "crewai" not in matched_servers:
            matched_servers.append("crewai")
            
        return matched_servers
    finally:
        await db.close()
