"""API router — Credit and budget management endpoints."""

from fastapi import APIRouter
from devplane.credits import get_credit_summary
from devplane.db import get_db

router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.get("/summary")
async def credit_summary(project_id: int = 0):
    """Get aggregated spending summary."""
    if project_id == 0:
        from devplane.db import get_default_project_id
        project_id = await get_default_project_id()
    return await get_credit_summary(project_id)


@router.get("/history")
async def usage_history(limit: int = 50, provider: str = ""):
    """Get recent usage records."""
    db = await get_db()
    try:
        query = "SELECT * FROM usage ORDER BY created_at DESC LIMIT ?"
        params = [limit]
        if provider:
            query = "SELECT * FROM usage WHERE provider_name = ? ORDER BY created_at DESC LIMIT ?"
            params = [provider, limit]
        rows = await db.execute(query, params)
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


@router.put("/budget")
async def update_budget(daily: float = None, weekly: float = None,
                        monthly: float = None, project_id: int = 0):
    """Update project budget limits."""
    if project_id == 0:
        from devplane.db import get_default_project_id
        project_id = await get_default_project_id()

    db = await get_db()
    try:
        sets = []
        values = []
        if daily is not None:
            sets.append("daily_budget = ?")
            values.append(daily)
        if weekly is not None:
            sets.append("weekly_budget = ?")
            values.append(weekly)
        if monthly is not None:
            sets.append("monthly_budget = ?")
            values.append(monthly)
        if sets:
            values.append(project_id)
            await db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", values)
            await db.commit()
        return {"status": "updated"}
    finally:
        await db.close()
