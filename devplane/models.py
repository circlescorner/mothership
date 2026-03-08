"""Pydantic models for DevPlane — chains, tiers, providers, projects, runs."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class StepType(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    JUDGE = "judge"
    CUSTOM = "custom"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    BUDGET_BLOCKED = "budget_blocked"


class TierLevel(str, Enum):
    CHEAP = "cheap"
    MID = "mid"
    PREMIUM = "premium"


# ─── Providers ────────────────────────────────────────────────────────────────

class Provider(BaseModel):
    id: Optional[int] = None
    name: str                          # e.g. "openrouter", "groq", "deepseek"
    display_name: str                  # e.g. "OpenRouter"
    api_key: str = ""                  # encrypted or raw
    enabled: bool = True
    monthly_budget: float = 0.0        # 0 = unlimited
    base_url: Optional[str] = None     # custom base URL if needed
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProviderModel(BaseModel):
    """A specific model available from a provider."""
    id: Optional[int] = None
    provider_id: int
    slug: str                          # LiteLLM format: "groq/llama-3.3-70b-versatile"
    display_name: str                  # "LLaMA 3.3 70B"
    input_cost_per_1k: float = 0.0     # $ per 1K input tokens
    output_cost_per_1k: float = 0.0    # $ per 1K output tokens
    max_tokens: int = 4096
    enabled: bool = True


# ─── Chain Configuration ──────────────────────────────────────────────────────

class ChainStep(BaseModel):
    """One step in a chain pipeline."""
    id: Optional[int] = None
    chain_id: int = 0
    step_type: StepType = StepType.CUSTOM
    label: str = ""                    # Display name
    system_prompt: str = ""            # System prompt template for this step
    model_slug: str = ""               # LiteLLM model slug
    timeout_seconds: int = 60
    order: int = 0                     # Execution order


class TierConfig(BaseModel):
    """A tier — a set of model assignments for each step type."""
    id: Optional[int] = None
    project_id: int = 0
    level: TierLevel = TierLevel.CHEAP
    planner_model: str = ""
    executor_model: str = ""
    reviewer_model: str = ""
    judge_model: str = ""
    max_cost_per_run: float = 0.10
    enabled: bool = True


class ChainConfig(BaseModel):
    """A complete chain configuration."""
    id: Optional[int] = None
    project_id: int = 0
    name: str = "Default Chain"
    description: str = ""
    steps: list[ChainStep] = Field(default_factory=list)
    tournament_mode: bool = True        # Run multiple tiers in parallel
    parallel_tiers: list[TierLevel] = Field(default_factory=lambda: [TierLevel.CHEAP, TierLevel.MID, TierLevel.PREMIUM])
    escalation_enabled: bool = True
    escalation_max: int = 2
    quality_threshold: float = 0.7
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ─── Projects ─────────────────────────────────────────────────────────────────

class Project(BaseModel):
    id: Optional[int] = None
    name: str = "Default Project"
    description: str = ""
    active_chain_id: Optional[int] = None
    daily_budget: float = 5.00
    weekly_budget: float = 25.00
    monthly_budget: float = 100.00
    is_default: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ─── Budget Limits ────────────────────────────────────────────────────────────

class BudgetLimits(BaseModel):
    daily: float = 5.00
    weekly: float = 25.00
    monthly: float = 100.00
    per_provider: dict[str, float] = Field(default_factory=dict)


# ─── Run Records ──────────────────────────────────────────────────────────────

class StepResult(BaseModel):
    step_type: str
    model_slug: str
    tier: str
    input_text: str = ""
    output_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    status: RunStatus = RunStatus.PENDING
    error: Optional[str] = None


class RunRecord(BaseModel):
    id: Optional[int] = None
    project_id: int = 0
    chain_id: int = 0
    prompt: str = ""
    final_output: str = ""
    winning_tier: str = ""
    total_cost: float = 0.0
    total_duration_ms: int = 0
    status: RunStatus = RunStatus.PENDING
    steps: list[StepResult] = Field(default_factory=list)
    created_at: Optional[datetime] = None


# ─── API Usage Record ─────────────────────────────────────────────────────────

class UsageRecord(BaseModel):
    id: Optional[int] = None
    provider_name: str
    model_slug: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    project_id: int = 0
    run_id: Optional[int] = None
    created_at: Optional[datetime] = None


# ─── Dashboard Summaries ──────────────────────────────────────────────────────

class CreditSummary(BaseModel):
    """Aggregated spending summary for the dashboard."""
    total_today: float = 0.0
    total_this_week: float = 0.0
    total_this_month: float = 0.0
    budget_daily: float = 5.00
    budget_weekly: float = 25.00
    budget_monthly: float = 100.00
    by_provider: dict[str, float] = Field(default_factory=dict)
    provider_limits: dict[str, float] = Field(default_factory=dict)


# ─── Mesh Configuration ──────────────────────────────────────────────────────

class MeshConfig(BaseModel):
    """Mesh global configuration."""
    id: Optional[int] = None
    name: str = "Default Mesh"
    execution_mode: str = "tournament"
    mcp_servers_enabled: list[str] = Field(default_factory=lambda: ["llamaindex", "haystack", "crewai", "pydanticai", "semantickernel"])
    default_tier: str = "mid"
    max_iterations: int = 3
    timeout_seconds: int = 60
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MeshRoleConfig(BaseModel):
    """Per-role configuration within a mesh."""
    id: Optional[int] = None
    mesh_config_id: int
    role_name: str
    model_slug: Optional[str] = None
    iteration_limit: Optional[int] = None
    timeout_seconds: int = 60
    config_json: dict[str, Any] = Field(default_factory=dict)


class LangchainTool(BaseModel):
    """LangChain tool registration."""
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    schema_json: str = "{}"
    handler_type: str
    handler_config_json: str = "{}"
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class HealthStatus(BaseModel):
    status: str = "online"
    version: str = "1.0.0"
    slack_connected: bool = False
    providers_active: int = 0
    total_runs: int = 0
    uptime_seconds: int = 0
