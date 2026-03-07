"""API router — Project management and run history endpoints."""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from devplane.db import get_db, get_default_project_id

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    daily_budget: float = 5.0
    weekly_budget: float = 25.0
    monthly_budget: float = 100.0


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active_chain_id: Optional[int] = None
    daily_budget: Optional[float] = None
    weekly_budget: Optional[float] = None
    monthly_budget: Optional[float] = None


@router.get("")
async def list_projects():
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM projects ORDER BY is_default DESC, name")
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


@router.get("/{project_id}")
async def get_project(project_id: int):
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        result = await row.fetchone()
        if not result:
            raise HTTPException(404, "Project not found")
        return dict(result)
    finally:
        await db.close()


@router.post("")
async def create_project(data: ProjectCreate):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO projects (name, description, daily_budget, weekly_budget, monthly_budget) VALUES (?, ?, ?, ?, ?)",
            (data.name, data.description, data.daily_budget, data.weekly_budget, data.monthly_budget)
        )
        await db.commit()
        row = await db.execute("SELECT last_insert_rowid()")
        pid = (await row.fetchone())[0]
        return {"id": pid, "status": "created"}
    finally:
        await db.close()


@router.put("/{project_id}")
async def update_project(project_id: int, data: ProjectUpdate):
    db = await get_db()
    try:
        sets = []
        values = []
        for key, value in data.model_dump(exclude_none=True).items():
            sets.append(f"{key} = ?")
            values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            values.append(project_id)
            await db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Run History ──────────────────────────────────────────────────────────────

@router.get("/{project_id}/runs")
async def list_runs(project_id: int, limit: int = 20):
    db = await get_db()
    try:
        rows = await db.execute(
            "SELECT id, prompt, final_output, winning_tier, total_cost, total_duration_ms, status, created_at FROM runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit)
        )
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


@router.get("/runs/{run_id}")
async def get_run(run_id: int):
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        result = await row.fetchone()
        if not result:
            raise HTTPException(404, "Run not found")
        run = dict(result)
        run["steps"] = json.loads(run.get("steps_json", "[]"))
        return run
    finally:
        await db.close()
