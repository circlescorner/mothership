"""API router — LangChain dynamic tool registration."""

import json
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from devplane.db import get_db
from devplane.auth import require_auth
from devplane.models import LangchainTool

logger = logging.getLogger("devplane.api.tools")

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class LangchainToolCreate(BaseModel):
    """Payload for creating a new LangChain tool."""
    name: str
    description: Optional[str] = None
    schema_json: str = "{}"
    handler_type: str
    handler_config_json: str = "{}"
    enabled: bool = True

class LangchainToolUpdate(BaseModel):
    """Payload for updating an existing LangChain tool."""
    name: Optional[str] = None
    description: Optional[str] = None
    schema_json: Optional[str] = None
    handler_type: Optional[str] = None
    handler_config_json: Optional[str] = None
    enabled: Optional[bool] = None


# ─── Helper Functions ─────────────────────────────────────────────────────────

def validate_json(json_str: str, field_name: str) -> None:
    """Validate that a string is valid JSON."""
    try:
        json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"{field_name} is not valid JSON: {e}")


# ─── CRUD Endpoints ───────────────────────────────────────────────────────────

@router.get("")
async def list_langchain_tools(request: Request):
    """List all registered LangChain tools."""
    await require_auth(request)
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM langchain_tools ORDER BY name")
        tools = []
        for row in await rows.fetchall():
            tool = dict(row)
            # Parse JSON fields for convenience
            tool["schema_json"] = json.loads(tool.get("schema_json") or "{}")
            tool["handler_config_json"] = json.loads(tool.get("handler_config_json") or "{}")
            tools.append(tool)
        return tools
    finally:
        await db.close()

@router.post("")
async def create_langchain_tool(request: Request, data: LangchainToolCreate):
    """Register a new LangChain tool."""
    await require_auth(request)
    # Validate JSON fields
    validate_json(data.schema_json, "schema_json")
    validate_json(data.handler_config_json, "handler_config_json")
    
    db = await get_db()
    try:
        # Check for duplicate name
        existing = await db.execute("SELECT id FROM langchain_tools WHERE name = ?", (data.name,))
        if await existing.fetchone():
            raise HTTPException(status_code=409, detail=f"Tool with name '{data.name}' already exists")
        
        await db.execute(
            """
            INSERT INTO langchain_tools (name, description, schema_json, handler_type, handler_config_json, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (data.name, data.description, data.schema_json, data.handler_type, data.handler_config_json, 1 if data.enabled else 0)
        )
        await db.commit()
        
        # Fetch the created tool
        row = await db.execute("SELECT * FROM langchain_tools WHERE name = ?", (data.name,))
        tool = dict(await row.fetchone())
        tool["schema_json"] = json.loads(tool.get("schema_json") or "{}")
        tool["handler_config_json"] = json.loads(tool.get("handler_config_json") or "{}")
        return tool
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create tool: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
    finally:
        await db.close()

@router.get("/{tool_id}")
async def get_langchain_tool(request: Request, tool_id: int):
    """Get a specific LangChain tool by ID."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM langchain_tools WHERE id = ?", (tool_id,))
        tool = await row.fetchone()
        if not tool:
            raise HTTPException(status_code=404, detail=f"Tool with ID {tool_id} not found")
        result = dict(tool)
        result["schema_json"] = json.loads(result.get("schema_json") or "{}")
        result["handler_config_json"] = json.loads(result.get("handler_config_json") or "{}")
        return result
    finally:
        await db.close()

@router.put("/{tool_id}")
async def update_langchain_tool(request: Request, tool_id: int, data: LangchainToolUpdate):
    """Update a LangChain tool."""
    await require_auth(request)
    db = await get_db()
    try:
        # Check existence
        row = await db.execute("SELECT id FROM langchain_tools WHERE id = ?", (tool_id,))
        if not await row.fetchone():
            raise HTTPException(status_code=404, detail=f"Tool with ID {tool_id} not found")
        
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        for key, value in dump.items():
            if key == "schema_json" or key == "handler_config_json":
                validate_json(value, key)
                sets.append(f"{key} = ?")
                values.append(value)
            elif key == "enabled":
                sets.append(f"{key} = ?")
                values.append(1 if value else 0)
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        
        if sets:
            sets.append("updated_at = datetime('now')")
            values.append(tool_id)
            await db.execute(
                f"UPDATE langchain_tools SET {', '.join(sets)} WHERE id = ?",
                values
            )
            await db.commit()
        
        # Return updated tool
        row = await db.execute("SELECT * FROM langchain_tools WHERE id = ?", (tool_id,))
        tool = dict(await row.fetchone())
        tool["schema_json"] = json.loads(tool.get("schema_json") or "{}")
        tool["handler_config_json"] = json.loads(tool.get("handler_config_json") or "{}")
        return tool
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update tool: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
    finally:
        await db.close()

@router.delete("/{tool_id}")
async def delete_langchain_tool(request: Request, tool_id: int):
    """Delete a LangChain tool."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT id FROM langchain_tools WHERE id = ?", (tool_id,))
        if not await row.fetchone():
            raise HTTPException(status_code=404, detail=f"Tool with ID {tool_id} not found")
        
        await db.execute("DELETE FROM langchain_tools WHERE id = ?", (tool_id,))
        await db.commit()
        return {"status": "deleted", "id": tool_id}
    finally:
        await db.close()

@router.post("/{tool_id}/enable")
async def toggle_langchain_tool_enable(request: Request, tool_id: int, enabled: bool = True):
    """Enable or disable a LangChain tool."""
    await require_auth(request)
    db = await get_db()
    try:
        row = await db.execute("SELECT id FROM langchain_tools WHERE id = ?", (tool_id,))
        if not await row.fetchone():
            raise HTTPException(status_code=404, detail=f"Tool with ID {tool_id} not found")
        
        await db.execute(
            "UPDATE langchain_tools SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
            (1 if enabled else 0, tool_id)
        )
        await db.commit()
        return {"status": "updated", "id": tool_id, "enabled": enabled}
    finally:
        await db.close()