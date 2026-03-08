"""Visual Workflow Orchestration Engine.

Provides a node-based visual pipeline builder for configuring AI workflows,
agent routing, and chain configurations through a visual interface.
"""

import json
import logging
import hashlib
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("devplane.orchestration.workflow")


class NodeType(str, Enum):
    """Types of workflow nodes."""
    INPUT = "input"           # User input
    AGENT = "agent"           # AI Agent
    ROUTER = "router"         # Lang routing decision
    CHAIN = "chain"           # Chain workflow
    CONDITION = "condition"   # If/else logic
    MERGE = "merge"          # Join multiple paths
    OUTPUT = "output"        # Final output
    MEMORY = "memory"        # Memory store/recall
    TOOL = "tool"            # External tool call


class AgentProvider(str, Enum):
    """Agent execution providers."""
    API = "api"              # Cloud API (OpenAI, Anthropic, etc.)
    LOCAL = "local"          # Local hosted model
    SWARM = "swarm"          # Agent swarm
    PERSONAL = "personal"    # Personal long-term agent


@dataclass
class AgentConfig:
    """Configuration for an AI agent node."""
    model: str = "deepseek/deepseek-chat"
    provider: AgentProvider = AgentProvider.API
    temperature: float = 0.2
    max_tokens: int = 4096
    system_prompt: str = ""
    memory_enabled: bool = True
    cache_enabled: bool = True
    fallback_models: list[str] = field(default_factory=list)
    # For local agents
    local_endpoint: Optional[str] = None
    local_model_name: Optional[str] = None
    # For swarm
    swarm_size: int = 3
    swarm_consensus: str = "majority"  # majority, best, or all


@dataclass
class WorkflowNode:
    """A single node in the workflow graph."""
    id: str
    type: NodeType
    name: str
    position: dict = field(default_factory=dict)  # {x, y} for visual layout
    config: dict = field(default_factory=dict)
    agent_config: Optional[AgentConfig] = None
    # Execution state
    status: str = "idle"  # idle, running, completed, error
    last_output: Optional[str] = None
    execution_time_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0


@dataclass
class WorkflowEdge:
    """Connection between two workflow nodes."""
    id: str
    source: str  # Source node ID
    target: str  # Target node ID
    condition: Optional[str] = None  # JavaScript-like condition for conditional edges
    label: str = ""


@dataclass
class Workflow:
    """Complete workflow definition."""
    id: str
    name: str
    description: str
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    is_active: bool = True
    # Global settings
    auto_save_memory: bool = True
    enable_caching: bool = True
    max_execution_time_sec: int = 300
    cost_budget_usd: float = 1.0


class WorkflowEngine:
    """Engine for executing visual workflows."""

    def __init__(self):
        self._workflows: dict[str, Workflow] = {}
        self._execution_cache: dict[str, Any] = {}

    async def create_workflow(self, name: str, description: str = "") -> Workflow:
        """Create a new workflow."""
        import uuid
        workflow = Workflow(
            id=str(uuid.uuid4()),
            name=name,
            description=description
        )
        self._workflows[workflow.id] = workflow
        await self._persist_workflow(workflow)
        return workflow

    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        if workflow_id in self._workflows:
            return self._workflows[workflow_id]
        # Try to load from database
        return await self._load_workflow(workflow_id)

    async def update_workflow(self, workflow: Workflow) -> bool:
        """Update a workflow."""
        workflow.updated_at = datetime.utcnow().isoformat()
        self._workflows[workflow.id] = workflow
        return await self._persist_workflow(workflow)

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
        # Delete from database
        from devplane.db import get_db
        db = await get_db()
        try:
            await db.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
            await db.commit()
            return True
        finally:
            await db.close()

    async def add_node(self, workflow_id: str, node: WorkflowNode) -> bool:
        """Add a node to a workflow."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return False
        workflow.nodes.append(node)
        return await self.update_workflow(workflow)

    async def add_edge(self, workflow_id: str, edge: WorkflowEdge) -> bool:
        """Add an edge to a workflow."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return False
        workflow.edges.append(edge)
        return await self.update_workflow(workflow)

    async def execute_workflow(
        self,
        workflow_id: str,
        input_data: dict,
        user_id: Optional[str] = None
    ) -> dict:
        """Execute a workflow with given input."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return {"error": "Workflow not found"}

        execution_id = hashlib.sha256(
            f"{workflow_id}:{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]

        logger.info(f"Executing workflow {workflow.name} (execution: {execution_id})")

        # Find input node
        input_nodes = [n for n in workflow.nodes if n.type == NodeType.INPUT]
        if not input_nodes:
            return {"error": "No input node found in workflow"}

        start_node = input_nodes[0]
        context = {"input": input_data, "execution_id": execution_id, "user_id": user_id}

        try:
            result = await self._execute_node(workflow, start_node, context)
            return {
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "status": "completed",
                "result": result,
            }
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return {
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "status": "error",
                "error": str(e),
            }

    async def _execute_node(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        context: dict
    ) -> Any:
        """Execute a single workflow node."""
        from devplane.orchestration.cache import TokenCache
        from devplane.roles import call_with_fallback

        cache = TokenCache()
        node.status = "running"

        # Check cache if enabled
        if workflow.enable_caching and node.cache_enabled:
            cache_key = cache.get_cache_key(node.type, json.dumps(node.config), json.dumps(context))
            cached = await cache.get(cache_key)
            if cached:
                logger.info(f"Node {node.id} cache hit")
                node.status = "completed"
                node.last_output = cached["output"]
                return cached["output"]

        start_time = datetime.utcnow()

        try:
            if node.type == NodeType.INPUT:
                result = context.get("input", {})

            elif node.type == NodeType.AGENT:
                result = await self._execute_agent_node(node, context)

            elif node.type == NodeType.ROUTER:
                result = await self._execute_router_node(node, context)

            elif node.type == NodeType.CHAIN:
                result = await self._execute_chain_node(node, context)

            elif node.type == NodeType.MEMORY:
                result = await self._execute_memory_node(node, context)

            elif node.type == NodeType.CONDITION:
                result = await self._execute_condition_node(node, context)

            elif node.type == NodeType.OUTPUT:
                result = context.get("last_output", "")

            else:
                result = {"error": f"Unknown node type: {node.type}"}

            # Update node state
            node.status = "completed"
            node.last_output = str(result) if not isinstance(result, dict) else json.dumps(result)
            node.execution_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Cache result
            if workflow.enable_caching and node.cache_enabled:
                await cache.set(cache_key, {"output": result})

            # Auto-save to memory if enabled
            if workflow.auto_save_memory and node.memory_enabled:
                await self._save_to_memory(workflow.id, node, context, result)

            # Continue to next nodes
            next_nodes = self._get_next_nodes(workflow, node.id, result)
            for next_node in next_nodes:
                context["last_output"] = result
                await self._execute_node(workflow, next_node, context)

            return result

        except Exception as e:
            node.status = "error"
            raise

    async def _execute_agent_node(self, node: WorkflowNode, context: dict) -> Any:
        """Execute an agent node."""
        from devplane.roles import call_with_fallback

        if not node.agent_config:
            return {"error": "No agent config"}

        config = node.agent_config
        prompt = context.get("last_output", context.get("input", {}))
        if isinstance(prompt, dict):
            prompt = json.dumps(prompt)

        # Route to appropriate execution method
        if config.provider == AgentProvider.LOCAL and config.local_endpoint:
            return await self._call_local_agent(config, prompt)
        elif config.provider == AgentProvider.SWARM:
            from devplane.orchestration.swarm import AgentSwarm
            swarm = AgentSwarm(size=config.swarm_size)
            return await swarm.execute(prompt, consensus=config.swarm_consensus)
        elif config.provider == AgentProvider.PERSONAL:
            from devplane.orchestration.personal import PersonalAgent
            agent = PersonalAgent()
            return await agent.chat(prompt, user_id=context.get("user_id"))
        else:
            # API provider
            role = "worker" if not config.system_prompt else "architect"
            result = await call_with_fallback(
                role=role,
                system_prompt=config.system_prompt or "You are a helpful AI assistant.",
                user_content=prompt,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            return result["content"]

    async def _call_local_agent(self, config: AgentConfig, prompt: str) -> str:
        """Call a locally hosted model."""
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                config.local_endpoint,
                json={
                    "model": config.local_model_name,
                    "prompt": prompt,
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                },
                timeout=60.0
            )
            data = resp.json()
            return data.get("response", data.get("text", ""))

    async def _execute_router_node(self, node: WorkflowNode, context: dict) -> str:
        """Execute a routing decision."""
        # Simple keyword-based routing for now
        prompt = str(context.get("last_output", "")).lower()
        routes = node.config.get("routes", {})
        for keyword, route in routes.items():
            if keyword in prompt:
                return route
        return node.config.get("default_route", "default")

    async def _execute_chain_node(self, node: WorkflowNode, context: dict) -> Any:
        """Execute a chain workflow node."""
        from devplane.chain.engine import run_tournament
        prompt = str(context.get("last_output", context.get("input", "")))
        result = await run_tournament(prompt, project_id=0)
        return result.get("final_output", "")

    async def _execute_memory_node(self, node: WorkflowNode, context: dict) -> Any:
        """Execute a memory store/recall node."""
        from devplane.memory.store import MemoryStore
        store = MemoryStore()

        action = node.config.get("action", "recall")
        if action == "store":
            content = str(context.get("last_output", ""))
            await store.add(content, metadata={"workflow": True})
            return {"stored": True}
        else:  # recall
            query = str(context.get("last_output", ""))
            memories = await store.search(query, limit=5)
            return {"memories": memories}

    async def _execute_condition_node(self, node: WorkflowNode, context: dict) -> bool:
        """Execute a condition check."""
        condition = node.config.get("condition", "true")
        # Simple condition evaluation (safer than eval)
        last_output = str(context.get("last_output", ""))
        return condition.lower() in last_output.lower()

    def _get_next_nodes(
        self,
        workflow: Workflow,
        node_id: str,
        result: Any
    ) -> list[WorkflowNode]:
        """Get the next nodes to execute based on edges and conditions."""
        next_nodes = []
        for edge in workflow.edges:
            if edge.source == node_id:
                # Check condition if present
                if edge.condition:
                    if not self._evaluate_condition(edge.condition, result):
                        continue
                # Find target node
                target = next((n for n in workflow.nodes if n.id == edge.target), None)
                if target:
                    next_nodes.append(target)
        return next_nodes

    def _evaluate_condition(self, condition: str, result: Any) -> bool:
        """Evaluate a condition expression."""
        result_str = str(result).lower()
        # Simple string contains check for now
        return condition.lower() in result_str

    async def _save_to_memory(
        self,
        workflow_id: str,
        node: WorkflowNode,
        context: dict,
        result: Any
    ):
        """Save workflow execution to memory."""
        from devplane.memory.store import MemoryStore
        store = MemoryStore()
        content = f"Workflow {workflow_id}, Node {node.name}: {result}"
        await store.add(content, metadata={
            "workflow_id": workflow_id,
            "node_id": node.id,
            "node_type": node.type,
            "user_id": context.get("user_id"),
        })

    async def _persist_workflow(self, workflow: Workflow) -> bool:
        """Save workflow to database."""
        from devplane.db import get_db
        db = await get_db()
        try:
            await db.execute("""
                INSERT OR REPLACE INTO workflows 
                (id, name, description, nodes, edges, created_at, updated_at, is_active, config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                workflow.id,
                workflow.name,
                workflow.description,
                json.dumps([self._node_to_dict(n) for n in workflow.nodes]),
                json.dumps([self._edge_to_dict(e) for e in workflow.edges]),
                workflow.created_at,
                workflow.updated_at,
                workflow.is_active,
                json.dumps({
                    "auto_save_memory": workflow.auto_save_memory,
                    "enable_caching": workflow.enable_caching,
                    "max_execution_time_sec": workflow.max_execution_time_sec,
                    "cost_budget_usd": workflow.cost_budget_usd,
                })
            ))
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to persist workflow: {e}")
            return False
        finally:
            await db.close()

    async def _load_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Load workflow from database."""
        from devplane.db import get_db
        db = await get_db()
        try:
            row = await db.execute(
                "SELECT * FROM workflows WHERE id = ?",
                (workflow_id,)
            )
            data = await row.fetchone()
            if not data:
                return None

            config = json.loads(data["config"] or "{}")
            workflow = Workflow(
                id=data["id"],
                name=data["name"],
                description=data["description"],
                nodes=[self._dict_to_node(n) for n in json.loads(data["nodes"] or "[]")],
                edges=[self._dict_to_edge(e) for e in json.loads(data["edges"] or "[]")],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                is_active=data["is_active"],
                auto_save_memory=config.get("auto_save_memory", True),
                enable_caching=config.get("enable_caching", True),
                max_execution_time_sec=config.get("max_execution_time_sec", 300),
                cost_budget_usd=config.get("cost_budget_usd", 1.0),
            )
            self._workflows[workflow_id] = workflow
            return workflow
        finally:
            await db.close()

    def _node_to_dict(self, node: WorkflowNode) -> dict:
        """Convert node to dictionary."""
        return {
            "id": node.id,
            "type": node.type.value,
            "name": node.name,
            "position": node.position,
            "config": node.config,
            "agent_config": {
                "model": node.agent_config.model,
                "provider": node.agent_config.provider.value,
                "temperature": node.agent_config.temperature,
                "max_tokens": node.agent_config.max_tokens,
                "system_prompt": node.agent_config.system_prompt,
                "memory_enabled": node.agent_config.memory_enabled,
                "cache_enabled": node.agent_config.cache_enabled,
                "fallback_models": node.agent_config.fallback_models,
                "local_endpoint": node.agent_config.local_endpoint,
                "local_model_name": node.agent_config.local_model_name,
                "swarm_size": node.agent_config.swarm_size,
                "swarm_consensus": node.agent_config.swarm_consensus,
            } if node.agent_config else None,
        }

    def _dict_to_node(self, data: dict) -> WorkflowNode:
        """Convert dictionary to node."""
        agent_config = None
        if data.get("agent_config"):
            ac = data["agent_config"]
            agent_config = AgentConfig(
                model=ac.get("model", "deepseek/deepseek-chat"),
                provider=AgentProvider(ac.get("provider", "api")),
                temperature=ac.get("temperature", 0.2),
                max_tokens=ac.get("max_tokens", 4096),
                system_prompt=ac.get("system_prompt", ""),
                memory_enabled=ac.get("memory_enabled", True),
                cache_enabled=ac.get("cache_enabled", True),
                fallback_models=ac.get("fallback_models", []),
                local_endpoint=ac.get("local_endpoint"),
                local_model_name=ac.get("local_model_name"),
                swarm_size=ac.get("swarm_size", 3),
                swarm_consensus=ac.get("swarm_consensus", "majority"),
            )
        return WorkflowNode(
            id=data["id"],
            type=NodeType(data["type"]),
            name=data["name"],
            position=data.get("position", {}),
            config=data.get("config", {}),
            agent_config=agent_config,
        )

    def _edge_to_dict(self, edge: WorkflowEdge) -> dict:
        """Convert edge to dictionary."""
        return {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "condition": edge.condition,
            "label": edge.label,
        }

    def _dict_to_edge(self, data: dict) -> WorkflowEdge:
        """Convert dictionary to edge."""
        return WorkflowEdge(
            id=data["id"],
            source=data["source"],
            target=data["target"],
            condition=data.get("condition"),
            label=data.get("label", ""),
        )


# Global workflow engine instance
_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    """Get the global workflow engine instance."""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine