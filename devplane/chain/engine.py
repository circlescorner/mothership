"""Chain Engine — LangGraph-powered configurable AI pipeline.

Supports:
- Configurable Plan → Execute → Review → Judge pipelines
- Tournament mode: run multiple tiers in parallel, judge picks winner
- Tier escalation: auto-retry on higher tier if quality is low
- Budget-aware: checks credits before each LLM call
"""

import asyncio
import json
import logging
import time
from typing import TypedDict, Annotated, Optional, Any
from litellm import acompletion
from devplane.db import get_db, record_usage
from devplane.credits import check_budget, record_call
from devplane.providers import load_all_keys_to_env

logger = logging.getLogger("devplane.chain")


# ─── State Schema ─────────────────────────────────────────────────────────────

class ChainState(TypedDict, total=False):
    """State flowing through the LangGraph pipeline."""
    prompt: str
    project_id: int
    run_id: int
    tier: str
    plan: str
    execution: str
    review: str
    final_output: str
    cost: float
    steps: list[dict]
    status: str
    error: str


# ─── LLM Call Wrapper ─────────────────────────────────────────────────────────

async def call_llm(model: str, system_prompt: str, user_content: str,
                   timeout: int = 60, project_id: int = 0,
                   run_id: int = 0) -> dict:
    """Make a single LLM call with budget checking and usage recording."""
    # Extract provider name from model slug
    provider = model.split("/")[0] if "/" in model else model

    # Check budget
    allowed, reason = await check_budget(provider, project_id)
    if not allowed:
        return {
            "content": "",
            "error": f"Budget blocked: {reason}",
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": 0,
            "status": "budget_blocked"
        }

    start = time.time()
    try:
        response = await asyncio.wait_for(
            acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            ),
            timeout=float(timeout)
        )
        duration_ms = int((time.time() - start) * 1000)

        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        # Get cost from LiteLLM's built-in tracking
        cost = 0.0
        if hasattr(response, "_hidden_params"):
            cost = response._hidden_params.get("response_cost", 0.0) or 0.0

        # Record usage
        await record_call(provider, model, input_tokens, output_tokens,
                          cost, project_id, run_id)

        return {
            "content": content,
            "error": None,
            "cost": cost,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": duration_ms,
            "status": "success"
        }

    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "content": "",
            "error": f"Timeout after {timeout}s",
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": duration_ms,
            "status": "error"
        }
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        logger.error(f"LLM call failed: {model} — {e}")
        return {
            "content": "",
            "error": str(e),
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": duration_ms,
            "status": "error"
        }


# ─── Pipeline Runner ──────────────────────────────────────────────────────────

async def run_tier_pipeline(prompt: str, tier: dict, chain_steps: list[dict],
                            project_id: int = 0, run_id: int = 0,
                            event_callback=None) -> dict:
    """Run a complete Plan → Execute → Review pipeline for one tier.
    
    Args:
        prompt: User's input
        tier: Tier config dict from DB (level, planner_model, executor_model, etc.)
        chain_steps: List of step configs from DB
        project_id: Project ID for budget tracking
        run_id: Run ID for linking usage records
        event_callback: Optional async function called with (step_type, status, data)
    """
    tier_name = tier["level"]
    results = []
    total_cost = 0.0

    # Map step types to tier models
    model_map = {
        "planner": tier.get("planner_model", ""),
        "executor": tier.get("executor_model", ""),
        "reviewer": tier.get("reviewer_model", ""),
        "judge": tier.get("judge_model", ""),
    }

    plan_text = ""
    exec_text = ""
    review_text = ""

    for step in chain_steps:
        step_type = step["step_type"]
        if step_type == "judge":
            continue  # Judge is handled separately

        model = model_map.get(step_type, "")
        if not model:
            continue

        system_prompt = step.get("system_prompt", "")
        timeout = step.get("timeout_seconds", 60)

        # Build user content based on step type (inject memory context for planner)
        if step_type == "planner":
            # Inject memory context from run_tournament if available
            user_content = prompt
        elif step_type == "executor":
            system_prompt = f"Execute the following plan precisely:\n{plan_text}" if plan_text else system_prompt
            user_content = prompt
        elif step_type == "reviewer":
            content_to_review = exec_text or plan_text
            system_prompt = f"You are a reviewer. Polish the provided execution output which was created to fulfill the user request: '{prompt}'. Fix errors and format cleanly. Output ONLY the polished response."
            user_content = content_to_review
        else:
            user_content = prompt

        if event_callback:
            await event_callback(step_type, "running", {"tier": tier_name, "model": model})

        result = await call_llm(model, system_prompt, user_content,
                                timeout, project_id, run_id)

        step_result = {
            "step_type": step_type,
            "tier": tier_name,
            "model": model,
            "output": result["content"],
            "cost": result["cost"],
            "duration_ms": result["duration_ms"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "status": result["status"],
            "error": result.get("error"),
        }
        results.append(step_result)
        total_cost += result["cost"]

        if result["status"] != "success":
            if event_callback:
                await event_callback(step_type, "error", step_result)
            return {
                "tier": tier_name,
                "output": "",
                "cost": total_cost,
                "steps": results,
                "status": "error",
                "error": result.get("error", "Step failed"),
            }

        # Store outputs for downstream steps
        if step_type == "planner":
            plan_text = result["content"]
        elif step_type == "executor":
            exec_text = result["content"]
        elif step_type == "reviewer":
            review_text = result["content"]

        if event_callback:
            await event_callback(step_type, "complete", step_result)

    final = review_text or exec_text or plan_text
    return {
        "tier": tier_name,
        "output": final,
        "cost": total_cost,
        "steps": results,
        "status": "success",
        "error": None,
    }


# ─── Tournament Runner ────────────────────────────────────────────────────────

async def run_tournament(prompt: str, project_id: int = 0,
                         event_callback=None, mode: str = "tournament") -> dict:
    """Run the full tournament: multiple tiers in parallel, judge picks winner.
    
    This is the main entry point called by the Slack bot and dashboard.
    Now includes: memory recall before run, memory storage after, and performance tracking.
    
    Args:
        mode: 'tournament' (default), 'mesh' (God-Mode iterative), or 'agent' (LangGraph tool agent)
    """
    # ── Mode Delegation ──
    if mode == "mesh":
        from devplane.chain.mesh import run_mesh
        return await run_mesh(prompt, project_id, event_callback=event_callback)

    if mode == "agent":
        from devplane.chain.agent import get_agent_graph
        from langchain_core.messages import HumanMessage
        try:
            graph = get_agent_graph()
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=prompt)], "current_tier": "deepseek/deepseek-chat"},
            )
            final = result["messages"][-1].content if result["messages"] else ""
            return {"status": "success", "final_output": final, "winning_tier": "agent", "total_cost": 0, "steps": []}
        except Exception as e:
            return {"status": "error", "final_output": str(e), "winning_tier": "", "total_cost": 0, "steps": []}

    # ── Tournament Mode (original behavior below) ──
    await load_all_keys_to_env()

    # ── Memory: recall relevant past context ──
    memory_context = ""
    try:
        from devplane.memory.store import recall
        memories = await recall(prompt, project_id, k=3)
        if memories:
            memory_context = "\n\n[Relevant past context]\n" + "\n".join(
                f"- {m['content'][:300]}" for m in memories
            )
    except Exception as e:
        logger.debug(f"Memory recall skipped: {e}")

    db = await get_db()
    try:
        # Get project config
        proj_row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj_row.fetchone()
        if not project:
            proj_row = await db.execute("SELECT * FROM projects WHERE is_default = 1")
            project = await proj_row.fetchone()

        chain_id = project["active_chain_id"]

        # Get chain config
        chain_row = await db.execute("SELECT * FROM chains WHERE id = ?", (chain_id,))
        chain = await chain_row.fetchone()

        # Get chain steps
        steps_rows = await db.execute(
            "SELECT * FROM chain_steps WHERE chain_id = ? ORDER BY step_order",
            (chain_id,)
        )
        chain_steps = [dict(r) for r in await steps_rows.fetchall()]

        # Get enabled tiers
        tier_rows = await db.execute(
            "SELECT * FROM tiers WHERE project_id = ? AND enabled = 1 ORDER BY level",
            (project["id"],)
        )
        all_tiers = [dict(r) for r in await tier_rows.fetchall()]

        # Filter to configured parallel tiers
        parallel_tiers = json.loads(chain["parallel_tiers"]) if chain["parallel_tiers"] else ["cheap", "mid", "premium"]
        tiers_to_run = [t for t in all_tiers if t["level"] in parallel_tiers]

        if not tiers_to_run:
            return {
                "final_output": "No tiers configured to run.",
                "winning_tier": "",
                "total_cost": 0.0,
                "status": "error",
                "steps": [],
            }

        # Create run record
        await db.execute(
            "INSERT INTO runs (project_id, chain_id, prompt, status) VALUES (?, ?, ?, 'running')",
            (project["id"], chain_id, prompt)
        )
        await db.commit()
        run_id_row = await db.execute("SELECT last_insert_rowid()")
        run_id = (await run_id_row.fetchone())[0]

    finally:
        await db.close()

    if event_callback:
        await event_callback("tournament", "started", {
            "run_id": run_id,
            "tiers": [t["level"] for t in tiers_to_run],
        })

    # Run all tiers in parallel
    if chain.get("tournament_mode", True) if isinstance(chain, dict) else chain["tournament_mode"]:
        tasks = [
            run_tier_pipeline(prompt, tier, chain_steps, project["id"], run_id, event_callback)
            for tier in tiers_to_run
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        # Single tier mode — run just the first tier
        results = [await run_tier_pipeline(prompt, tiers_to_run[0], chain_steps,
                                            project["id"], run_id, event_callback)]

    # Collect valid results
    valid = []
    all_steps = []
    total_cost = 0.0
    for r in results:
        if isinstance(r, Exception):
            continue
        if isinstance(r, dict):
            all_steps.extend(r.get("steps", []))
            total_cost += r.get("cost", 0.0)
            if r.get("status") == "success":
                valid.append(r)

    if not valid:
        # All failed
        db2 = await get_db()
        await db2.execute(
            "UPDATE runs SET status='error', total_cost=?, steps_json=? WHERE id=?",
            (total_cost, json.dumps(all_steps), run_id)
        )
        await db2.commit()
        await db2.close()
        return {
            "run_id": run_id,
            "final_output": "All AI stacks failed. Check API keys and balances.",
            "winning_tier": "",
            "total_cost": total_cost,
            "status": "error",
            "steps": all_steps,
        }

    # If only one result, skip judging
    if len(valid) == 1:
        winner = valid[0]
    else:
        # Judge picks the winner
        winner = await _judge_results(prompt, valid, chain_steps, all_tiers,
                                       project["id"], run_id, event_callback)
        if winner is None:
            winner = valid[0]  # Fallback to first
        total_cost += winner.get("judge_cost", 0.0)

    # Save run result
    db2 = await get_db()
    try:
        await db2.execute(
            "UPDATE runs SET final_output=?, winning_tier=?, total_cost=?, status='success', steps_json=?, total_duration_ms=? WHERE id=?",
            (winner["output"], winner["tier"], total_cost, json.dumps(all_steps),
             sum(s.get("duration_ms", 0) for s in all_steps), run_id)
        )
        await db2.commit()
    finally:
        await db2.close()

    if event_callback:
        await event_callback("tournament", "complete", {
            "run_id": run_id,
            "winning_tier": winner["tier"],
            "total_cost": total_cost,
        })

    # ── Memory: store prompt + result ──
    try:
        from devplane.memory.store import remember
        await remember(prompt, "user", project_id, {"run_id": run_id})
        await remember(winner["output"][:2000], "assistant", project_id, {
            "run_id": run_id, "tier": winner["tier"], "cost": total_cost
        })
    except Exception as e:
        logger.debug(f"Memory storage skipped: {e}")

    # ── Optimizer: record performance metrics ──
    try:
        from devplane.chain.optimizer import record_step_performance
        for step in all_steps:
            if step.get("status") == "success" and step.get("model"):
                await record_step_performance(
                    step["model"], step["step_type"],
                    step.get("cost", 0), step.get("duration_ms", 0),
                    quality=0.7 if step["tier"] == winner["tier"] else 0.4
                )
    except Exception as e:
        logger.debug(f"Performance recording skipped: {e}")

    return {
        "run_id": run_id,
        "final_output": winner["output"],
        "winning_tier": winner["tier"],
        "total_cost": total_cost,
        "status": "success",
        "steps": all_steps,
    }


async def _judge_results(prompt: str, candidates: list[dict], chain_steps: list[dict],
                          tiers: list[dict], project_id: int, run_id: int,
                          event_callback=None) -> dict:
    """Have a judge model pick the best output from multiple tier results."""
    # Find judge step config
    judge_step = next((s for s in chain_steps if s["step_type"] == "judge"), None)
    system_prompt = judge_step["system_prompt"] if judge_step else (
        "You are an elite judge evaluating AI pipeline outputs. "
        "Choose the most accurate, comprehensive answer. "
        "Output the winning stack's name in bold, followed by its complete response."
    )
    timeout = judge_step.get("timeout_seconds", 45) if judge_step else 45

    # Find judge model from any tier
    judge_model = ""
    for t in tiers:
        if t.get("judge_model"):
            judge_model = t["judge_model"]
            break
    if not judge_model:
        judge_model = "deepseek/deepseek-chat"

    # Build judge prompt
    judge_input = f"User query: '{prompt}'\n\n"
    for c in candidates:
        judge_input += f"--- CANDIDATE: {c['tier'].upper()} ---\n{c['output']}\n\n"

    if event_callback:
        await event_callback("judge", "running", {"model": judge_model})

    result = await call_llm(judge_model, system_prompt, judge_input,
                            timeout, project_id, run_id)

    if result["status"] != "success":
        if event_callback:
            await event_callback("judge", "error", {"error": result.get("error")})
        return None

    if event_callback:
        await event_callback("judge", "complete", {"cost": result["cost"]})

    # Try to figure out which tier won from the judge's output
    judge_text = result["content"]
    winning_tier = candidates[0]["tier"]
    for c in candidates:
        if c["tier"].upper() in judge_text.upper():
            winning_tier = c["tier"]
            break

    winning = next((c for c in candidates if c["tier"] == winning_tier), candidates[0])
    return {
        "tier": winning_tier,
        "output": judge_text,
        "judge_cost": result["cost"],
    }
