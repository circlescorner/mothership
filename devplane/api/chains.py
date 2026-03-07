"""API router — Chain configuration and execution endpoints."""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import asyncio
from devplane.db import get_db, get_default_project_id
from devplane.chain.engine import run_tournament

router = APIRouter(prefix="/api/chains", tags=["chains"])


class ChainUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tournament_mode: Optional[bool] = None
    parallel_tiers: Optional[list[str]] = None
    escalation_enabled: Optional[bool] = None
    escalation_max: Optional[int] = None
    quality_threshold: Optional[float] = None


class TierUpdate(BaseModel):
    planner_model: Optional[str] = None
    executor_model: Optional[str] = None
    reviewer_model: Optional[str] = None
    judge_model: Optional[str] = None
    max_cost_per_run: Optional[float] = None
    enabled: Optional[bool] = None


class StepUpdate(BaseModel):
    label: Optional[str] = None
    system_prompt: Optional[str] = None
    model_slug: Optional[str] = None
    timeout_seconds: Optional[int] = None


class RunRequest(BaseModel):
    prompt: str
    project_id: int = 0


# ─── Chain Config CRUD ────────────────────────────────────────────────────────

@router.get("")
async def list_chains(project_id: int = 0):
    if project_id == 0:
        project_id = await get_default_project_id()
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM chains WHERE project_id = ?", (project_id,))
        chains = [dict(r) for r in await rows.fetchall()]
        for c in chains:
            c["parallel_tiers"] = json.loads(c["parallel_tiers"]) if c["parallel_tiers"] else []
        return chains
    finally:
        await db.close()


@router.get("/{chain_id}")
async def get_chain(chain_id: int):
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM chains WHERE id = ?", (chain_id,))
        chain = await row.fetchone()
        if not chain:
            raise HTTPException(404, "Chain not found")
        result = dict(chain)
        result["parallel_tiers"] = json.loads(result["parallel_tiers"]) if result["parallel_tiers"] else []

        # Get steps
        steps_rows = await db.execute("SELECT * FROM chain_steps WHERE chain_id = ? ORDER BY step_order", (chain_id,))
        result["steps"] = [dict(s) for s in await steps_rows.fetchall()]
        return result
    finally:
        await db.close()


@router.put("/{chain_id}")
async def update_chain(chain_id: int, data: ChainUpdate):
    db = await get_db()
    try:
        sets = []
        values = []
        dump = data.model_dump(exclude_none=True)
        for key, value in dump.items():
            if key == "parallel_tiers":
                sets.append("parallel_tiers = ?")
                values.append(json.dumps(value))
            else:
                sets.append(f"{key} = ?")
                values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            values.append(chain_id)
            await db.execute(f"UPDATE chains SET {', '.join(sets)} WHERE id = ?", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Tier CRUD ────────────────────────────────────────────────────────────────

@router.get("/tiers/{project_id}")
async def list_tiers(project_id: int):
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM tiers WHERE project_id = ? ORDER BY level", (project_id,))
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


@router.put("/tiers/{tier_id}")
async def update_tier(tier_id: int, data: TierUpdate):
    db = await get_db()
    try:
        sets = []
        values = []
        for key, value in data.model_dump(exclude_none=True).items():
            sets.append(f"{key} = ?")
            values.append(value)
        if sets:
            values.append(tier_id)
            await db.execute(f"UPDATE tiers SET {', '.join(sets)} WHERE id = ?", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Step CRUD ────────────────────────────────────────────────────────────────

@router.put("/steps/{step_id}")
async def update_step(step_id: int, data: StepUpdate):
    db = await get_db()
    try:
        sets = []
        values = []
        for key, value in data.model_dump(exclude_none=True).items():
            sets.append(f"{key} = ?")
            values.append(value)
        if sets:
            values.append(step_id)
            await db.execute(f"UPDATE chain_steps SET {', '.join(sets)} WHERE id = ?", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()


# ─── Chain Execution ──────────────────────────────────────────────────────────

@router.post("/run")
async def run_chain(data: RunRequest):
    """Execute a chain and return the result."""
    project_id = data.project_id or await get_default_project_id()
    result = await run_tournament(data.prompt, project_id)
    return result


@router.post("/run/stream")
async def run_chain_stream(data: RunRequest):
    """Execute a chain with real-time SSE updates."""
    project_id = data.project_id or await get_default_project_id()
    event_queue = asyncio.Queue()

    async def event_callback(step_type, status, data_dict):
        await event_queue.put({
            "step": step_type,
            "status": status,
            "data": data_dict,
        })

    async def generate():
        task = asyncio.create_task(
            run_tournament(data.prompt, project_id, event_callback)
        )

        while not task.done():
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'step': 'heartbeat', 'status': 'alive', 'data': {}})}\n\n"

        # Drain remaining events
        while not event_queue.empty():
            event = event_queue.get_nowait()
            yield f"data: {json.dumps(event)}\n\n"

        result = task.result()
        yield f"data: {json.dumps({'step': 'final', 'status': 'complete', 'data': result})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
