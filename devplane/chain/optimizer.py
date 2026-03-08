"""Chain Optimizer — learns from past runs to recommend optimal configurations.

Analyzes cost, speed, and quality metrics per model to suggest the best
tier and model assignments for each chain step.
"""

import json
import logging
from devplane.db import get_db

logger = logging.getLogger("devplane.chain.optimizer")


async def get_optimizer_config():
    """Fetch optimizer configuration from database."""
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM optimizer_config WHERE id = 1")
        config = await row.fetchone()
        if config:
            return {
                "complexity_threshold": config["complexity_threshold"] or 0.5,
                "scoring_weights_json": json.loads(config["scoring_weights_json"] or '{"accuracy": 0.4, "cost": 0.3, "speed": 0.3}'),
                "max_iterations": config["max_iterations"] or 3,
                "timeout_seconds": config["timeout_seconds"] or 30,
            }
    except Exception as e:
        logger.warning(f"Failed to fetch optimizer config: {e}")
    # Fallback defaults
    return {
        "complexity_threshold": 0.5,
        "scoring_weights_json": {"accuracy": 0.4, "cost": 0.3, "speed": 0.3},
        "max_iterations": 3,
        "timeout_seconds": 30,
    }


async def record_step_performance(model_slug: str, step_type: str,
                                   cost: float, duration_ms: int,
                                   quality: float = 0.0):
    """Record performance metrics for a model+step combination.
    
    Called after each chain step completes. Quality is 0-1 (0 = failed, 1 = perfect).
    """
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT id, avg_cost, avg_duration_ms, avg_quality, total_runs FROM model_performance WHERE model_slug = ? AND step_type = ?",
            (model_slug, step_type)
        )
        existing = await row.fetchone()

        if existing:
            n = existing["total_runs"]
            new_avg_cost = (existing["avg_cost"] * n + cost) / (n + 1)
            new_avg_dur = (existing["avg_duration_ms"] * n + duration_ms) / (n + 1)
            new_avg_qual = (existing["avg_quality"] * n + quality) / (n + 1) if quality > 0 else existing["avg_quality"]

            await db.execute("""
                UPDATE model_performance SET avg_cost=?, avg_duration_ms=?, avg_quality=?, total_runs=?, last_used=datetime('now')
                WHERE id=?
            """, (new_avg_cost, new_avg_dur, new_avg_qual, n + 1, existing["id"]))
        else:
            await db.execute("""
                INSERT INTO model_performance (model_slug, step_type, avg_cost, avg_duration_ms, avg_quality, total_runs)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (model_slug, step_type, cost, duration_ms, quality if quality > 0 else 0.5))

        await db.commit()
    finally:
        await db.close()


async def recommend_tier(prompt: str) -> dict:
    """Recommend the optimal tier based on prompt complexity.
    
    Simple heuristic: longer/more complex prompts → higher tier.
    Over time, learns from past results which tier works best.
    """
    config = await get_optimizer_config()
    complexity_threshold = config.get("complexity_threshold", 0.5)
    cheap_threshold = complexity_threshold * 0.8   # adjust as needed
    mid_threshold = complexity_threshold * 1.3
    
    words = len(prompt.split())
    has_code = any(kw in prompt.lower() for kw in ["code", "function", "class", "debug", "implement", "algorithm", "api"])
    has_analysis = any(kw in prompt.lower() for kw in ["analyze", "compare", "evaluate", "research", "explain in detail"])

    complexity_score = 0.3  # Base: cheap
    if words > 100:
        complexity_score += 0.2
    if words > 300:
        complexity_score += 0.2
    if has_code:
        complexity_score += 0.2
    if has_analysis:
        complexity_score += 0.15

    if complexity_score < cheap_threshold:
        tier = "cheap"
        reason = "Simple prompt — cheap tier should handle this well"
    elif complexity_score < mid_threshold:
        tier = "mid"
        reason = "Moderate complexity — mid tier recommended for balanced cost/quality"
    else:
        tier = "premium"
        reason = "Complex prompt — premium tier recommended for best results"

    return {
        "recommended_tier": tier,
        "complexity_score": round(complexity_score, 2),
        "reason": reason,
        "analysis": {
            "word_count": words,
            "has_code_keywords": has_code,
            "has_analysis_keywords": has_analysis,
        }
    }


async def recommend_models(step_type: str = "executor") -> list[dict]:
    """Recommend best models for a step type based on performance history."""
    db = await get_db()
    try:
        rows = await db.execute("""
            SELECT model_slug, avg_cost, avg_duration_ms, avg_quality, total_runs
            FROM model_performance
            WHERE step_type = ? AND total_runs >= 1
            ORDER BY avg_quality DESC, avg_cost ASC
            LIMIT 10
        """, (step_type,))

        models = [dict(r) for r in await rows.fetchall()]

        if not models:
            return [{
                "model_slug": "No data yet",
                "recommendation": "Run a few chains first to build performance data",
            }]

        for m in models:
            # Calculate efficiency score: quality per dollar
            m["efficiency_score"] = round(
                m["avg_quality"] / max(m["avg_cost"], 0.0001), 2
            )
            m["avg_cost"] = round(m["avg_cost"], 6)
            m["avg_duration_ms"] = round(m["avg_duration_ms"])
            m["avg_quality"] = round(m["avg_quality"], 3)

        return sorted(models, key=lambda x: x.get("efficiency_score", 0), reverse=True)
    finally:
        await db.close()


async def get_insights() -> dict:
    """Get performance insights for the dashboard."""
    db = await get_db()
    try:
        # Per-model stats
        rows = await db.execute("""
            SELECT model_slug, step_type, avg_cost, avg_duration_ms, avg_quality, total_runs
            FROM model_performance
            ORDER BY total_runs DESC
        """)
        models = [dict(r) for r in await rows.fetchall()]

        # Best per step type
        best_by_step = {}
        for m in models:
            st = m["step_type"]
            if st not in best_by_step or m["avg_quality"] > best_by_step[st].get("avg_quality", 0):
                best_by_step[st] = m

        # Fastest models
        fastest = sorted(models, key=lambda x: x["avg_duration_ms"])[:3] if models else []

        # Cheapest models
        cheapest = sorted(models, key=lambda x: x["avg_cost"])[:3] if models else []

        # Total stats
        total_runs = sum(m["total_runs"] for m in models)

        return {
            "total_model_entries": len(models),
            "total_tracked_runs": total_runs,
            "best_by_step": best_by_step,
            "fastest": fastest,
            "cheapest": cheapest,
            "all_models": models,
        }
    finally:
        await db.close()
