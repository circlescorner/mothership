"""API router ∀ Agent Registry and Cross-IDE Task Queue."""

import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Any
from devplane.db import get_db

router = APIRouter(prefix="/api/agents", tags=["agents"])

class AgentRegistration(BaseModel):
    ide_name: str
    agent_name: str
    description: str
    input_schema: dict

class TaskResult(BaseModel):
    result_json: Optional[str] = None
    error_message: Optional[str] = None

@router.post("/register")
async def register_agent(req: Request, data: AgentRegistration):
    """Register a new external IDE agent to be exposed via MCP."""
    from devplane.auth import get_session
    # Basic auth check if session middleware active, else allow (for local testing)
    session_id = req.cookies.get("devplane_session")
    if session_id:
        session = await get_session(session_id)
        if not session:
            raise HTTPException(401, "Invalid session")
            
    db = await get_db()
    try:
        schema_json = json.dumps(data.input_schema)
        
        # Upsert logic
        row = await db.execute("SELECT id FROM agent_workflows WHERE agent_name = ?", (data.agent_name,))
        existing = await row.fetchone()
        
        if existing:
            await db.execute(
                "UPDATE agent_workflows SET ide_name=?, description=?, input_schema=?, is_active=1, last_ping=datetime('now') WHERE agent_name=?",
                (data.ide_name, data.description, schema_json, data.agent_name)
            )
        else:
            await db.execute(
                "INSERT INTO agent_workflows (ide_name, agent_name, description, input_schema) VALUES (?, ?, ?, ?)",
                (data.ide_name, data.agent_name, data.description, schema_json)
            )
        await db.commit()
        return {"status": "registered", "agent_name": data.agent_name}
    finally:
        await db.close()

@router.get("/poll/{agent_name}")
async def poll_tasks(agent_name: str):
    """IDE agent polls for pending tasks assigned to it via the MCP server."""
    db = await get_db()
    try:
        # Update last ping
        await db.execute("UPDATE agent_workflows SET last_ping = datetime('now') WHERE agent_name = ?", (agent_name,))
        await db.commit()
        
        # Find oldest pending task
        row = await db.execute(
            "SELECT id, payload_json FROM devplane_tasks WHERE agent_name = ? AND status = 'pending' ORDER BY created_at ASC LIMIT 1",
            (agent_name,)
        )
        task = await row.fetchone()
        
        if not task:
            return {"task": None}
            
        # Mark as processing
        await db.execute("UPDATE devplane_tasks SET status = 'processing' WHERE id = ?", (task["id"],))
        await db.commit()
        
        return {
            "task": {
                "id": task["id"],
                "arguments": json.loads(task["payload_json"])
            }
        }
    finally:
        await db.close()

@router.post("/result/{task_id}")
async def submit_result(task_id: int, data: TaskResult):
    """IDE agent submits the result of a completed task back to the queue."""
    db = await get_db()
    try:
        if data.error_message:
            await db.execute(
                "UPDATE devplane_tasks SET status = 'error', error_message = ?, completed_at = datetime('now') WHERE id = ?",
                (data.error_message, task_id)
            )
        else:
            await db.execute(
                "UPDATE devplane_tasks SET status = 'completed', result_json = ?, completed_at = datetime('now') WHERE id = ?",
                (data.result_json, task_id)
            )
        await db.commit()
        return {"status": "success"}
    finally:
        await db.close()

@router.get("/directory")
async def list_agents():
    """List all registered agents (for the dashboard UI)."""
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM agent_workflows ORDER BY last_ping DESC")
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()
