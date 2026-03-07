"""API Credit Tracker — enforces hard budget limits before any LLM call.

Call `check_budget()` before making an API call. If it returns False,
the call should be skipped. After a call completes, call `record_call()`.
"""

import logging
from datetime import datetime, timedelta
from devplane.db import get_db, get_spending, record_usage
from typing import Optional

logger = logging.getLogger("devplane.credits")


async def check_budget(provider_name: str, project_id: int = 0) -> tuple[bool, str]:
    """Check if a call is allowed under current budget limits.
    
    Returns (allowed, reason). If not allowed, reason explains why.
    """
    db = await get_db()
    try:
        # Get project budget limits
        row = await db.execute(
            "SELECT daily_budget, weekly_budget, monthly_budget FROM projects WHERE id = ?",
            (project_id,)
        )
        project = await row.fetchone()
        if not project:
            row = await db.execute("SELECT daily_budget, weekly_budget, monthly_budget FROM projects WHERE is_default = 1")
            project = await row.fetchone()

        if project:
            daily = await get_spending("daily")
            if project["daily_budget"] > 0 and daily >= project["daily_budget"]:
                return False, f"Daily budget exhausted (${daily:.2f} / ${project['daily_budget']:.2f})"

            weekly = await get_spending("weekly")
            if project["weekly_budget"] > 0 and weekly >= project["weekly_budget"]:
                return False, f"Weekly budget exhausted (${weekly:.2f} / ${project['weekly_budget']:.2f})"

            monthly = await get_spending("monthly")
            if project["monthly_budget"] > 0 and monthly >= project["monthly_budget"]:
                return False, f"Monthly budget exhausted (${monthly:.2f} / ${project['monthly_budget']:.2f})"

        # Check per-provider budget
        prov_row = await db.execute(
            "SELECT monthly_budget FROM providers WHERE name = ?",
            (provider_name,)
        )
        prov = await prov_row.fetchone()
        if prov and prov["monthly_budget"] > 0:
            prov_monthly = await get_spending("monthly", provider=provider_name)
            if prov_monthly >= prov["monthly_budget"]:
                return False, f"Provider '{provider_name}' monthly budget exhausted (${prov_monthly:.2f} / ${prov['monthly_budget']:.2f})"

        return True, "ok"
    finally:
        await db.close()


async def record_call(provider_name: str, model_slug: str, input_tokens: int,
                      output_tokens: int, cost: float, project_id: int = 0,
                      run_id: Optional[int] = None):
    """Record a completed LLM call for credit tracking."""
    await record_usage(provider_name, model_slug, input_tokens, output_tokens,
                       cost, project_id, run_id)
    logger.info(f"Recorded: {provider_name}/{model_slug} — ${cost:.4f} "
                f"({input_tokens} in, {output_tokens} out)")


async def get_credit_summary(project_id: int = 0) -> dict:
    """Get aggregated spending summary for the dashboard."""
    db = await get_db()
    try:
        # Project budgets
        row = await db.execute(
            "SELECT daily_budget, weekly_budget, monthly_budget FROM projects WHERE id = ?",
            (project_id,)
        )
        project = await row.fetchone()
        if not project:
            row = await db.execute("SELECT daily_budget, weekly_budget, monthly_budget FROM projects WHERE is_default = 1")
            project = await row.fetchone()

        daily_budget = project["daily_budget"] if project else 5.0
        weekly_budget = project["weekly_budget"] if project else 25.0
        monthly_budget = project["monthly_budget"] if project else 100.0

        # Current spending
        daily_spent = await get_spending("daily")
        weekly_spent = await get_spending("weekly")
        monthly_spent = await get_spending("monthly")

        # Per-provider spending this month
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = await db.execute(
            "SELECT provider_name, SUM(cost) as total FROM usage WHERE created_at >= ? GROUP BY provider_name",
            (month_start.isoformat(),)
        )
        by_provider = {}
        async for r in rows:
            by_provider[r["provider_name"]] = round(r["total"], 4)

        # Provider limits
        prov_rows = await db.execute("SELECT name, monthly_budget FROM providers WHERE monthly_budget > 0")
        provider_limits = {}
        async for r in prov_rows:
            provider_limits[r["name"]] = r["monthly_budget"]

        return {
            "total_today": round(daily_spent, 4),
            "total_this_week": round(weekly_spent, 4),
            "total_this_month": round(monthly_spent, 4),
            "budget_daily": daily_budget,
            "budget_weekly": weekly_budget,
            "budget_monthly": monthly_budget,
            "by_provider": by_provider,
            "provider_limits": provider_limits,
        }
    finally:
        await db.close()
