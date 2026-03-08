"""God-Mode Mesh — Architect → Worker → Critic iterative code generation.

A LangGraph-powered pipeline that generates high-quality code through
an iterative loop: Architect plans, Worker codes, Critic reviews.
If the Critic finds issues, Worker retries with feedback (up to max_iterations).

Uses the role-based model registry for 5-way fallback per step.
"""

import logging
import time
import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from devplane.db import get_db

logger = logging.getLogger("devplane.chain.mesh")


async def get_active_mesh_config():
    """Fetch the active mesh configuration with role configs."""
    db = await get_db()
    try:
        # Get mesh config
        row = await db.execute(
            "SELECT * FROM mesh_configs WHERE is_active = 1 LIMIT 1"
        )
        config = await row.fetchone()
        if not config:
            # Create default
            await db.execute("""
                INSERT INTO mesh_configs (name, execution_mode, mcp_servers_enabled, default_tier, max_iterations, timeout_seconds)
                VALUES ('Default Mesh', 'tournament', '["llamaindex", "haystack", "crewai", "pydanticai", "semantickernel"]', 'mid', 3, 60)
            """)
            await db.commit()
            row = await db.execute("SELECT * FROM mesh_configs WHERE is_active = 1 LIMIT 1")
            config = await row.fetchone()
        
        # Get role configs
        role_rows = await db.execute(
            "SELECT * FROM mesh_role_config WHERE mesh_config_id = ?",
            (config["id"],)
        )
        role_configs = {}
        async for role_row in role_rows:
            role_configs[role_row["role_name"]] = {
                "model_slug": role_row["model_slug"],
                "iteration_limit": role_row["iteration_limit"],
                "timeout_seconds": role_row["timeout_seconds"],
                "config_json": json.loads(role_row["config_json"]) if role_row["config_json"] else {},
            }
        
        return {
            "id": config["id"],
            "name": config["name"],
            "execution_mode": config["execution_mode"],
            "mcp_servers_enabled": json.loads(config["mcp_servers_enabled"]) if config["mcp_servers_enabled"] else [],
            "default_tier": config["default_tier"],
            "max_iterations": config["max_iterations"],
            "timeout_seconds": config["timeout_seconds"],
            "config_json": json.loads(config["config_json"]) if config["config_json"] else {},
            "role_configs": role_configs,
        }
    finally:
        await db.close()


# ─── State Schema ────────────────────────────────────────────────────────────

class MeshState(TypedDict):
    """State flowing through the God-Mode mesh pipeline."""
    task: str
    plan: str
    code: str
    feedback: str
    iterations: int
    max_iterations: int
    is_valid: bool
    project_id: int
    run_id: int
    total_cost: float
    steps: list[dict]
    status: str
    error: str


# ─── Nodes ───────────────────────────────────────────────────────────────────

async def architect_node(state: MeshState) -> dict:
    """The Architect creates a bullet-proof technical plan."""
    from devplane.roles import call_with_fallback

    logger.info(f"🧠 Architecting: {state['task'][:80]}...")

    result = await call_with_fallback(
        role="architect",
        system_prompt=(
            "You are an elite software architect. Create a concise, bullet-proof "
            "technical plan for the given task. Focus on correctness, security, "
            "and clean structure. Output ONLY the plan, no code."
        ),
        user_content=state["task"],
        temperature=0.3,
        project_id=state.get("project_id", 0),
        run_id=state.get("run_id", 0),
    )

    step = {
        "step": "architect",
        "model": result["model"],
        "cost": result["cost"],
        "duration_ms": result["duration_ms"],
    }

    return {
        "plan": result["content"],
        "iterations": 0,
        "total_cost": state.get("total_cost", 0) + result["cost"],
        "steps": state.get("steps", []) + [step],
    }


async def worker_node(state: MeshState) -> dict:
    """The Worker generates code from the plan + feedback."""
    from devplane.roles import call_with_fallback

    iteration = state.get("iterations", 0)
    logger.info(f"🔨 Coding (Iteration {iteration + 1})...")

    feedback_section = ""
    if state.get("feedback") and state["feedback"] != "None":
        feedback_section = f"\n\nPREVIOUS FEEDBACK (fix these issues):\n{state['feedback']}"

    result = await call_with_fallback(
        role="worker",
        system_prompt=(
            "You are an expert programmer. Write complete, production-ready code "
            "that implements the plan exactly. Include all imports, error handling, "
            "and edge cases. Output ONLY the code."
        ),
        user_content=f"PLAN:\n{state['plan']}{feedback_section}",
        temperature=0.2,
        max_tokens=8192,
        project_id=state.get("project_id", 0),
        run_id=state.get("run_id", 0),
    )

    step = {
        "step": f"worker_iter_{iteration + 1}",
        "model": result["model"],
        "cost": result["cost"],
        "duration_ms": result["duration_ms"],
    }

    return {
        "code": result["content"],
        "iterations": iteration + 1,
        "total_cost": state.get("total_cost", 0) + result["cost"],
        "steps": state.get("steps", []) + [step],
    }


async def critic_node(state: MeshState) -> dict:
    """The Critic reviews code for bugs, security issues, and correctness."""
    from devplane.roles import call_with_fallback

    logger.info("🧐 Reviewing...")

    result = await call_with_fallback(
        role="critic",
        system_prompt=(
            "You are an elite code reviewer. Review the code for bugs, security "
            "issues, missing edge cases, and correctness. If the code is perfect "
            "and production-ready, respond with EXACTLY 'LGTM'. Otherwise, list "
            "the specific issues that need to be fixed."
        ),
        user_content=f"TASK: {state['task']}\n\nCODE:\n{state['code']}",
        temperature=0.1,
        project_id=state.get("project_id", 0),
        run_id=state.get("run_id", 0),
    )

    max_iterations = state.get("max_iterations", 3)
    is_valid = (
        "LGTM" in result["content"].upper()
        or state.get("iterations", 0) >= max_iterations
    )

    step = {
        "step": f"critic_iter_{state.get('iterations', 0)}",
        "model": result["model"],
        "cost": result["cost"],
        "duration_ms": result["duration_ms"],
        "verdict": "LGTM" if is_valid else "NEEDS_WORK",
    }

    return {
        "feedback": result["content"],
        "is_valid": is_valid,
        "total_cost": state.get("total_cost", 0) + result["cost"],
        "steps": state.get("steps", []) + [step],
    }


# ─── Graph Construction ──────────────────────────────────────────────────────

def _build_mesh_graph() -> StateGraph:
    """Build the Architect → Worker → Critic state machine."""
    workflow = StateGraph(MeshState)

    workflow.add_node("architect", architect_node)
    workflow.add_node("worker", worker_node)
    workflow.add_node("critic", critic_node)

    workflow.set_entry_point("architect")
    workflow.add_edge("architect", "worker")
    workflow.add_edge("worker", "critic")

    # Conditional: if valid → END, else → back to worker with feedback
    workflow.add_conditional_edges(
        "critic",
        lambda state: "end" if state.get("is_valid", False) else "worker",
        {"end": END, "worker": "worker"},
    )

    return workflow


_compiled_mesh = None


def get_mesh_graph():
    """Get the compiled mesh graph (singleton)."""
    global _compiled_mesh
    if _compiled_mesh is None:
        _compiled_mesh = _build_mesh_graph().compile()
    return _compiled_mesh


# ─── Main Entry Point ────────────────────────────────────────────────────────

async def run_mesh(
    task: str,
    project_id: int = 0,
    max_iterations: int = 3,
    event_callback=None,
) -> dict:
    """Run the God-Mode mesh pipeline.

    Args:
        task: The coding task to accomplish
        project_id: Project for budget tracking
        max_iterations: Max worker→critic iterations (default 3)
        event_callback: Optional async callable for SSE progress events

    Returns:
        dict with keys: status, code, plan, feedback, total_cost, steps, iterations
    """
    from devplane.db import get_db
    from devplane.memory.store import recall, remember

    start = time.time()

    # Create a run record
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO runs (project_id, chain_id, prompt, status) VALUES (?, 1, ?, 'running')",
            (project_id, task)
        )
        await db.commit()
        row = await db.execute("SELECT last_insert_rowid()")
        run_id = (await row.fetchone())[0]
    finally:
        await db.close()

    # Recall relevant context from memory
    context = ""
    try:
        memories = await recall(task, project_id, k=3)
        if memories:
            context = "\n\nRELEVANT CONTEXT FROM PAST RUNS:\n" + "\n---\n".join(
                m.get("content", "")[:500] for m in memories
            )
    except Exception as e:
        logger.warning(f"Memory recall failed: {e}")

    # Emit start event
    if event_callback:
        await event_callback({"step": "mesh_start", "status": "running", "task": task})

    # Run the mesh
    try:
        # Fetch mesh configuration
        mesh_config = await get_active_mesh_config()
        # Use provided max_iterations if different from default, else config value
        if max_iterations == 3:
            max_iterations = mesh_config["max_iterations"]
        
        graph = get_mesh_graph()
        initial_state = {
            "task": task + context,
            "plan": "",
            "code": "",
            "feedback": "",
            "iterations": 0,
            "max_iterations": max_iterations,
            "is_valid": False,
            "project_id": project_id,
            "run_id": run_id,
            "total_cost": 0.0,
            "steps": [],
            "status": "running",
            "error": "",
        }

        # Stream execution events
        final_state = initial_state
        async for event in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in event.items():
                final_state = {**final_state, **node_output}
                if event_callback:
                    await event_callback({
                        "step": node_name,
                        "status": "running",
                        "iteration": final_state.get("iterations", 0),
                        "cost": final_state.get("total_cost", 0),
                    })

        duration_ms = int((time.time() - start) * 1000)

        # Store result in memory
        try:
            await remember(
                f"Task: {task}\n\nCode:\n{final_state.get('code', '')}",
                role="assistant",
                project_id=project_id,
                metadata={"mode": "mesh", "cost": final_state.get("total_cost", 0)},
            )
        except Exception as e:
            logger.warning(f"Memory store failed: {e}")

        # Update run record
        db = await get_db()
        try:
            import json
            await db.execute(
                "UPDATE runs SET final_output=?, winning_tier='mesh', total_cost=?, "
                "total_duration_ms=?, status='success', steps_json=? WHERE id=?",
                (
                    final_state.get("code", ""),
                    final_state.get("total_cost", 0),
                    duration_ms,
                    json.dumps(final_state.get("steps", [])),
                    run_id,
                )
            )
            await db.commit()
        finally:
            await db.close()

        if event_callback:
            await event_callback({"step": "mesh_complete", "status": "complete"})

        return {
            "status": "success",
            "code": final_state.get("code", ""),
            "plan": final_state.get("plan", ""),
            "feedback": final_state.get("feedback", ""),
            "total_cost": final_state.get("total_cost", 0),
            "total_duration_ms": duration_ms,
            "steps": final_state.get("steps", []),
            "iterations": final_state.get("iterations", 0),
            "final_output": final_state.get("code", ""),
            "winning_tier": "mesh",
        }

    except Exception as e:
        logger.error(f"Mesh pipeline error: {e}")
        if event_callback:
            await event_callback({"step": "mesh_error", "status": "error", "error": str(e)})

        db = await get_db()
        try:
            await db.execute("UPDATE runs SET status='error' WHERE id=?", (run_id,))
            await db.commit()
        finally:
            await db.close()

        return {
            "status": "error",
            "final_output": f"Mesh pipeline error: {str(e)}",
            "total_cost": 0,
            "steps": [],
        }
