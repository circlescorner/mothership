"""Agent Swarm System - Multiple high-IQ agents working together.

Provides swarm intelligence with local and API agents collaborating
on complex tasks through various consensus mechanisms.
"""

import json
import logging
import asyncio
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("devplane.orchestration.swarm")


class AgentType(str, Enum):
    """Types of swarm agents."""
    RESEARCHER = "researcher"      # Information gathering
    CRITIC = "critic"              # Quality assurance
    CREATIVE = "creative"          # Idea generation
    ANALYST = "analyst"            # Data analysis
    PLANNER = "planner"            # Strategy and planning
    EXECUTOR = "executor"          # Implementation
    REVIEWER = "reviewer"          # Code/content review
    LOCAL = "local"                # Local hosted model


class ConsensusType(str, Enum):
    """Types of consensus mechanisms."""
    MAJORITY = "majority"          # Simple majority vote
    BEST = "best"                  # Quality scoring selection
    ALL = "all"                    # Return all responses
    WEIGHTED = "weighted"          # Weighted by agent confidence
    CASCADE = "cascade"            # Sequential refinement


@dataclass
class SwarmAgent:
    """A single agent in the swarm."""
    id: str
    name: str
    type: AgentType
    model: str
    provider: str = "api"          # "api" or "local"
    local_endpoint: Optional[str] = None
    system_prompt: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096
    weight: float = 1.0            # For weighted consensus
    enabled: bool = True
    # Performance tracking
    total_calls: int = 0
    successful_calls: int = 0
    avg_response_quality: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class SwarmResult:
    """Result from a swarm execution."""
    consensus_type: ConsensusType
    final_output: str
    individual_responses: list[dict]
    consensus_metadata: dict
    execution_time_ms: float
    total_tokens: int
    total_cost_usd: float
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class AgentSwarm:
    """Swarm of AI agents for collaborative problem solving."""

    # High-IQ model selection (99th percentile performance)
    HIGH_IQ_MODELS = {
        "o1": "openrouter/openai/o1",                           # OpenAI O1 - reasoning
        "claude_opus": "openrouter/anthropic/claude-3-opus",    # Claude Opus - analysis
        "deepseek_r1": "deepseek/deepseek-reasoner",            # DeepSeek R1 - reasoning
        "gemini_pro": "gemini/gemini-1.5-pro",                  # Gemini Pro - multimodal
        "groq_llama": "groq/llama-3.3-70b-versatile",           # Groq - speed
        "cerebras": "cerebras/llama3.3-70b",                    # Cerebras - throughput
        "local": "local",                                        # Local model placeholder
    }

    # Specialized agent prompts
    AGENT_PROMPTS = {
        AgentType.RESEARCHER: """You are an elite research agent. Your job is to gather comprehensive information, find relevant facts, and identify key concepts. Be thorough and cite specific details. Focus on accuracy and completeness.""",
        AgentType.CRITIC: """You are a critical analysis agent. Your job is to evaluate quality, identify flaws, question assumptions, and ensure rigor. Be constructively critical and highlight potential issues or improvements.""",
        AgentType.CREATIVE: """You are a creative ideation agent. Your job is to generate novel ideas, explore possibilities, and think outside the box. Be imaginative and propose innovative approaches.""",
        AgentType.ANALYST: """You are a data analysis agent. Your job is to analyze patterns, draw logical conclusions, and provide structured insights. Be methodical and data-driven in your reasoning.""",
        AgentType.PLANNER: """You are a strategic planning agent. Your job is to create structured plans, identify dependencies, and outline step-by-step approaches. Be organized and consider edge cases.""",
        AgentType.EXECUTOR: """You are an execution agent. Your job is to implement solutions, write code, and produce concrete outputs. Be precise and produce working, production-ready results.""",
        AgentType.REVIEWER: """You are a review agent. Your job is to check for errors, verify correctness, and ensure best practices. Be meticulous and thorough in your review.""",
        AgentType.LOCAL: """You are a local intelligence agent. Process efficiently and return structured results.""",
    }

    def __init__(self, size: int = 5, name: str = "swarm"):
        self.name = name
        self.size = size
        self.agents: list[SwarmAgent] = []
        self._init_default_agents()

    def _init_default_agents(self):
        """Initialize default high-IQ agent swarm."""
        import uuid

        # Create diverse high-IQ agents
        agent_configs = [
            (AgentType.PLANNER, self.HIGH_IQ_MODELS["o1"], "Planner-O1"),
            (AgentType.RESEARCHER, self.HIGH_IQ_MODELS["deepseek_r1"], "Researcher-R1"),
            (AgentType.EXECUTOR, self.HIGH_IQ_MODELS["claude_opus"], "Executor-Opus"),
            (AgentType.CRITIC, self.HIGH_IQ_MODELS["gemini_pro"], "Critic-Gemini"),
            (AgentType.REVIEWER, self.HIGH_IQ_MODELS["groq_llama"], "Reviewer-Groq"),
        ]

        for agent_type, model, name in agent_configs[:self.size]:
            agent = SwarmAgent(
                id=str(uuid.uuid4()),
                name=name,
                type=agent_type,
                model=model,
                system_prompt=self.AGENT_PROMPTS[agent_type],
                temperature=0.2 if agent_type != AgentType.CREATIVE else 0.7,
            )
            self.agents.append(agent)

    def add_local_agent(self, endpoint: str, model_name: str, name: str = "Local-Agent"):
        """Add a locally hosted agent to the swarm."""
        import uuid
        agent = SwarmAgent(
            id=str(uuid.uuid4()),
            name=name,
            type=AgentType.LOCAL,
            model="local",
            provider="local",
            local_endpoint=endpoint,
            local_model_name=model_name,
            system_prompt=self.AGENT_PROMPTS[AgentType.LOCAL],
        )
        self.agents.append(agent)
        logger.info(f"Added local agent {name} to swarm")

    def add_api_agent(
        self,
        model: str,
        agent_type: AgentType,
        name: str,
        system_prompt: Optional[str] = None
    ):
        """Add an API-based agent to the swarm."""
        import uuid
        agent = SwarmAgent(
            id=str(uuid.uuid4()),
            name=name,
            type=agent_type,
            model=model,
            provider="api",
            system_prompt=system_prompt or self.AGENT_PROMPTS[agent_type],
        )
        self.agents.append(agent)
        logger.info(f"Added API agent {name} ({model}) to swarm")

    async def execute(
        self,
        prompt: str,
        context: Optional[dict] = None,
        consensus: str = "majority",
        timeout_sec: int = 120
    ) -> SwarmResult:
        """Execute the swarm on a prompt."""
        start_time = datetime.utcnow()
        consensus_type = ConsensusType(consensus)

        logger.info(f"Swarm '{self.name}' executing with {consensus} consensus")

        # Execute all agents in parallel
        tasks = [
            self._execute_agent(agent, prompt, context)
            for agent in self.agents
            if agent.enabled
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Process responses
        individual_responses = []
        valid_responses = []

        for agent, response in zip(self.agents, responses):
            if isinstance(response, Exception):
                logger.error(f"Agent {agent.name} failed: {response}")
                individual_responses.append({
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "agent_type": agent.type.value,
                    "error": str(response),
                    "success": False,
                })
            else:
                individual_responses.append({
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "agent_type": agent.type.value,
                    "response": response["content"],
                    "model": response.get("model"),
                    "cost": response.get("cost", 0),
                    "tokens": response.get("tokens", 0),
                    "latency_ms": response.get("duration_ms", 0),
                    "success": True,
                })
                valid_responses.append({
                    "agent": agent,
                    "response": response["content"],
                    "metadata": response,
                })
                # Update agent stats
                agent.total_calls += 1
                agent.successful_calls += 1

        # Apply consensus
        final_output, consensus_meta = self._apply_consensus(
            consensus_type, valid_responses, prompt
        )

        execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        total_tokens = sum(r.get("tokens", 0) for r in individual_responses if "tokens" in r)
        total_cost = sum(r.get("cost", 0) for r in individual_responses if "cost" in r)

        return SwarmResult(
            consensus_type=consensus_type,
            final_output=final_output,
            individual_responses=individual_responses,
            consensus_metadata=consensus_meta,
            execution_time_ms=execution_time,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
        )

    async def _execute_agent(
        self,
        agent: SwarmAgent,
        prompt: str,
        context: Optional[dict]
    ) -> dict:
        """Execute a single agent."""
        import time
        from devplane.roles import call_with_fallback

        start = time.time()

        if agent.provider == "local":
            # Call local model
            result = await self._call_local_model(agent, prompt)
        else:
            # Call API model
            role = agent.type.value if agent.type.value in [
                "architect", "worker", "critic", "fast", "planner"
            ] else "worker"

            result = await call_with_fallback(
                role=role,
                system_prompt=agent.system_prompt,
                user_content=prompt,
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
            )

        latency = (time.time() - start) * 1000
        agent.avg_latency_ms = (agent.avg_latency_ms * agent.total_calls + latency) / (agent.total_calls + 1)

        return {
            "content": result["content"] if isinstance(result, dict) else result,
            "model": agent.model,
            "cost": result.get("cost", 0) if isinstance(result, dict) else 0,
            "tokens": result.get("tokens_in", 0) + result.get("tokens_out", 0) if isinstance(result, dict) else 0,
            "duration_ms": latency,
        }

    async def _call_local_model(self, agent: SwarmAgent, prompt: str) -> dict:
        """Call a locally hosted model."""
        import httpx
        import time

        start = time.time()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                agent.local_endpoint,
                json={
                    "model": agent.local_model_name,
                    "messages": [
                        {"role": "system", "content": agent.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": agent.temperature,
                    "max_tokens": agent.max_tokens,
                },
                timeout=60.0
            )
            data = resp.json()

        latency = (time.time() - start) * 1000
        return {
            "content": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "model": agent.local_model_name,
            "cost": 0,  # Local models are free
            "tokens": data.get("usage", {}).get("total_tokens", 0),
            "duration_ms": latency,
        }

    def _apply_consensus(
        self,
        consensus_type: ConsensusType,
        responses: list[dict],
        original_prompt: str
    ) -> tuple[str, dict]:
        """Apply consensus algorithm to agent responses."""
        if not responses:
            return "No valid responses from swarm", {"error": "All agents failed"}

        if consensus_type == ConsensusType.ALL:
            # Return all responses combined
            combined = "\n\n=== AGENT RESPONSES ===\n\n"
            for r in responses:
                combined += f"[{r['agent'].name}]:\n{r['response']}\n\n"
            return combined, {"agent_count": len(responses)}

        elif consensus_type == ConsensusType.BEST:
            # Select based on agent quality scores and response length appropriateness
            best = max(responses, key=lambda r: self._score_response(r))
            return best["response"], {
                "selected_agent": best["agent"].name,
                "score": self._score_response(best),
            }

        elif consensus_type == ConsensusType.CASCADE:
            # Sequential refinement - each agent improves previous
            result = responses[0]["response"]
            for i, r in enumerate(responses[1:], 1):
                result = f"{result}\n\n[Refined by {r['agent'].name}]:\n{r['response']}"
            return result, {"cascade_steps": len(responses)}

        elif consensus_type == ConsensusType.WEIGHTED:
            # Weighted by agent performance
            total_weight = sum(r["agent"].weight for r in responses)
            # For text, we can't truly weight, so select probabilistically
            import random
            weights = [r["agent"].weight for r in responses]
            selected = random.choices(responses, weights=weights, k=1)[0]
            return selected["response"], {
                "selected_agent": selected["agent"].name,
                "weight": selected["agent"].weight,
                "total_weight": total_weight,
            }

        else:  # MAJORITY - use voting for similar responses
            # Group similar responses
            groups = self._group_similar_responses(responses)
            largest_group = max(groups, key=lambda g: len(g))
            # Return the best response from the majority group
            best_in_group = max(largest_group, key=lambda r: self._score_response(r))
            return best_in_group["response"], {
                "consensus_size": len(largest_group),
                "total_agents": len(responses),
                "selected_agent": best_in_group["agent"].name,
            }

    def _score_response(self, response_data: dict) -> float:
        """Score a response for quality."""
        score = 0.0
        agent = response_data["agent"]
        response = response_data["response"]

        # Base score from agent historical performance
        score += agent.avg_response_quality * 10

        # Prefer complete responses
        if len(response) > 100:
            score += 5
        if len(response) > 500:
            score += 3

        # Prefer responses with structure
        if any(marker in response for marker in ["1.", "- ", "* ", "```"]):
            score += 3

        # Penalize errors or short responses
        if len(response) < 50:
            score -= 5

        return score

    def _group_similar_responses(self, responses: list[dict]) -> list[list[dict]]:
        """Group similar responses using simple text similarity."""
        if not responses:
            return []

        groups = []
        used = set()

        for i, r1 in enumerate(responses):
            if i in used:
                continue

            group = [r1]
            used.add(i)

            for j, r2 in enumerate(responses[i+1:], i+1):
                if j in used:
                    continue
                if self._text_similarity(r1["response"], r2["response"]) > 0.6:
                    group.append(r2)
                    used.add(j)

            groups.append(group)

        return groups

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity."""
        # Simple Jaccard similarity on words
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def to_dict(self) -> dict:
        """Serialize swarm to dictionary."""
        return {
            "name": self.name,
            "size": self.size,
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.type.value,
                    "model": a.model,
                    "provider": a.provider,
                    "enabled": a.enabled,
                    "weight": a.weight,
                    "stats": {
                        "total_calls": a.total_calls,
                        "successful_calls": a.successful_calls,
                        "avg_latency_ms": a.avg_latency_ms,
                    }
                }
                for a in self.agents
            ]
        }