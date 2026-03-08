"""API endpoints for Visual Workflow Orchestration."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class CreateWorkflowRequest(BaseModel):
    name: str
    description: str = ""


class CreateNodeRequest(BaseModel):
    workflow_id: str
    type: str
    name: str
    position: dict = {}
    config: dict = {}
    id: Optional[str] = None  # Optional: client can provide ID or server will generate one


class CreateEdgeRequest(BaseModel):
    workflow_id: str
    source: str
    target: str
    condition: Optional[str] = None


class ExecuteWorkflowRequest(BaseModel):
    input_data: dict
    user_id: Optional[str] = None


@router.get("")
async def list_workflows():
    """List all workflows."""
    from devplane.orchestration import get_workflow_engine
    engine = get_workflow_engine()
    # Load from database
    # SECURITY: This query uses a static string. For dynamic queries with user input,
    # always use parameterized queries: await db.execute("SELECT * FROM table WHERE id = ?", (user_id,))
    from devplane.db import get_db
    db = await get_db()
    try:
        rows = await db.execute("SELECT id, name, description, is_active FROM workflows ORDER BY updated_at DESC")
        workflows = [dict(r) for r in await rows.fetchall()]
        return {"workflows": workflows}
    finally:
        await db.close()


@router.post("")
async def create_workflow(data: CreateWorkflowRequest):
    """Create a new workflow."""
    from devplane.orchestration import get_workflow_engine
    engine = get_workflow_engine()
    workflow = await engine.create_workflow(data.name, data.description)
    return {"workflow_id": workflow.id, "name": workflow.name}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get workflow details."""
    from devplane.orchestration import get_workflow_engine
    engine = get_workflow_engine()
    workflow = await engine.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "nodes": [engine._node_to_dict(n) for n in workflow.nodes],
        "edges": [engine._edge_to_dict(e) for e in workflow.edges],
        "is_active": workflow.is_active,
    }


@router.post("/{workflow_id}/nodes")
async def add_node(workflow_id: str, data: CreateNodeRequest):
    """Add a node to a workflow."""
    from devplane.orchestration import get_workflow_engine
    from devplane.orchestration.workflow import WorkflowNode, NodeType

    import uuid

    engine = get_workflow_engine()
    node = WorkflowNode(
        id=data.id or str(uuid.uuid4()),
        type=NodeType(data.type),
        name=data.name,
        position=data.position,
        config=data.config,
    )
    success = await engine.add_node(workflow_id, node)
    if not success:
        raise HTTPException(400, "Failed to add node")
    return {"node_id": node.id}


@router.post("/{workflow_id}/edges")
async def add_edge(workflow_id: str, data: CreateEdgeRequest):
    """Add an edge to a workflow."""
    from devplane.orchestration import get_workflow_engine
    from devplane.orchestration.workflow import WorkflowEdge

    engine = get_workflow_engine()
    edge = WorkflowEdge(
        id=str(__import__('uuid').uuid4()),
        source=data.source,
        target=data.target,
        condition=data.condition,
    )
    success = await engine.add_edge(workflow_id, edge)
    if not success:
        raise HTTPException(400, "Failed to add edge")
    return {"edge_id": edge.id}


@router.post("/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, data: ExecuteWorkflowRequest):
    """Execute a workflow."""
    from devplane.orchestration import get_workflow_engine
    engine = get_workflow_engine()
    result = await engine.execute_workflow(
        workflow_id,
        data.input_data,
        data.user_id
    )
    return result


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    from devplane.orchestration import get_workflow_engine
    engine = get_workflow_engine()
    success = await engine.delete_workflow(workflow_id)
    if not success:
        raise HTTPException(404, "Workflow not found")
    return {"status": "deleted"}


# ─── Agent Swarm Endpoints ───────────────────────────────────────────────────

@router.post("/swarm/execute")
async def execute_swarm(
    prompt: str,
    size: int = 5,
    consensus: str = "majority",
    context: Optional[dict] = None
):
    """Execute an agent swarm."""
    from devplane.orchestration.swarm import AgentSwarm

    swarm = AgentSwarm(size=size)
    result = await swarm.execute(prompt, context=context, consensus=consensus)

    return {
        "consensus": result.consensus_type.value,
        "output": result.final_output,
        "individual_responses": result.individual_responses,
        "execution_time_ms": result.execution_time_ms,
        "total_tokens": result.total_tokens,
        "total_cost_usd": result.total_cost_usd,
    }


# ─── Personal Agent Endpoints ────────────────────────────────────────────────

@router.post("/personal/chat")
async def personal_chat(
    message: str,
    user_id: str = "default",
    store_memory: bool = True
):
    """Chat with the personal agent."""
    from devplane.orchestration.personal import PersonalAgent

    agent = PersonalAgent(user_id=user_id)
    result = await agent.chat(message, store_memory=store_memory)
    return result


@router.get("/personal/preferences")
async def get_personal_preferences(
    user_id: str = "default",
    pref_type: Optional[str] = None
):
    """Get personal agent preferences."""
    from devplane.orchestration.personal import PersonalAgent, PreferenceType

    agent = PersonalAgent(user_id=user_id)
    prefs = await agent.get_preferences(
        PreferenceType(pref_type) if pref_type else None
    )
    return {"preferences": prefs}


@router.post("/personal/preferences")
async def add_personal_preference(
    user_id: str = "default",
    pref_type: str = "communication",
    key: str = "",
    value: Any = None,
    confidence: float = 0.8
):
    """Add a personal preference."""
    from devplane.orchestration.personal import PersonalAgent, PreferenceType

    agent = PersonalAgent(user_id=user_id)
    await agent.add_preference(
        PreferenceType(pref_type),
        key,
        value,
        confidence
    )
    return {"status": "added"}


# ─── Token Cache Endpoints ───────────────────────────────────────────────────

@router.get("/cache/stats")
async def get_cache_stats():
    """Get token cache statistics."""
    from devplane.orchestration.cache import get_token_cache

    cache = get_token_cache()
    return await cache.get_stats()


@router.post("/cache/clear")
async def clear_cache():
    """Clear the token cache."""
    from devplane.orchestration.cache import get_token_cache

    cache = get_token_cache()
    await cache.clear()
    return {"status": "cleared"}