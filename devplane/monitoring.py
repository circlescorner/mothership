"""Monitoring and health check utilities for DevPlane.

Provides Prometheus-style metrics, comprehensive health checks,
and system status monitoring for all integrated services.
"""

import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("devplane.monitoring")

# ─── Metrics Collection ──────────────────────────────────────────────────────

@dataclass
class MetricsSnapshot:
    """Snapshot of system metrics."""
    timestamp: float = field(default_factory=time.time)
    request_count: int = 0
    request_latency_ms: float = 0.0
    error_count: int = 0
    active_connections: int = 0
    llm_calls_total: int = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_cost_total: float = 0.0
    droplets_active: int = 0
    workspaces_active: int = 0
    memory_entries: int = 0


class MetricsCollector:
    """Collect and aggregate system metrics."""
    
    def __init__(self):
        self._metrics = defaultdict(lambda: defaultdict(int))
        self._latencies: list[float] = []
        self._start_time = time.time()
    
    def record_request(self, path: str, latency_ms: float, status_code: int):
        """Record an API request."""
        self._metrics["requests"]["total"] += 1
        self._metrics["requests"][f"path_{path}"] += 1
        self._metrics["requests"][f"status_{status_code}"] += 1
        self._latencies.append(latency_ms)
        
        # Keep only last 1000 latencies
        if len(self._latencies) > 1000:
            self._latencies = self._latencies[-1000:]
    
    def record_llm_call(self, provider: str, tokens_in: int, tokens_out: int, cost: float):
        """Record an LLM API call."""
        self._metrics["llm"]["calls_total"] += 1
        self._metrics["llm"][f"provider_{provider}"] += 1
        self._metrics["llm"]["tokens_in"] += tokens_in
        self._metrics["llm"]["tokens_out"] += tokens_out
        self._metrics["llm"]["cost_total"] += cost
    
    def record_error(self, error_type: str):
        """Record an error."""
        self._metrics["errors"]["total"] += 1
        self._metrics["errors"][f"type_{error_type}"] += 1
    
    def get_summary(self) -> dict:
        """Get metrics summary."""
        latencies = self._latencies
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
        
        return {
            "uptime_seconds": int(time.time() - self._start_time),
            "requests": dict(self._metrics["requests"]),
            "llm": {
                "calls_total": self._metrics["llm"]["calls_total"],
                "tokens_in": self._metrics["llm"]["tokens_in"],
                "tokens_out": self._metrics["llm"]["tokens_out"],
                "cost_total": round(self._metrics["llm"]["cost_total"], 4),
            },
            "errors": dict(self._metrics["errors"]),
            "latency": {
                "avg_ms": round(avg_latency, 2),
                "p95_ms": round(p95_latency, 2),
            }
        }

# Global metrics collector
metrics = MetricsCollector()


# ─── Health Checks ───────────────────────────────────────────────────────────

@dataclass
class HealthStatus:
    """Health status of a service."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    response_time_ms: float
    message: str
    last_check: datetime


class HealthChecker:
    """Perform health checks on all integrated services."""
    
    def __init__(self):
        self._cache: dict[str, HealthStatus] = {}
        self._cache_time: float = 0
        self._cache_ttl = 30  # 30 seconds
    
    async def check_database(self) -> HealthStatus:
        """Check SQLite database health."""
        start = time.time()
        try:
            from devplane.db import get_db
            db = await get_db()
            await db.execute("SELECT 1")
            await db.close()
            latency = (time.time() - start) * 1000
            return HealthStatus(
                name="database",
                status="healthy",
                response_time_ms=latency,
                message="Connected",
                last_check=datetime.utcnow()
            )
        except Exception as e:
            return HealthStatus(
                name="database",
                status="unhealthy",
                response_time_ms=(time.time() - start) * 1000,
                message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_qdrant(self) -> HealthStatus:
        """Check Qdrant vector DB health."""
        start = time.time()
        try:
            from devplane.memory.store import _check_qdrant
            if not await _check_qdrant():
                return HealthStatus(
                    name="qdrant",
                    status="degraded",
                    response_time_ms=0,
                    message="Not configured",
                    last_check=datetime.utcnow()
                )
            
            # Try actual connection
            from qdrant_client import QdrantClient
            url = os.environ.get("QDRANT_URL", "")
            key = os.environ.get("QDRANT_KEY", "")
            client = QdrantClient(url=url, api_key=key if key else None)
            try:
                client.get_collections()
                latency = (time.time() - start) * 1000
                return HealthStatus(
                    name="qdrant",
                    status="healthy",
                    response_time_ms=latency,
                    message="Connected",
                    last_check=datetime.utcnow()
                )
            finally:
                # Ensure client is closed to prevent connection leaks
                client.close()
        except Exception as e:
            return HealthStatus(
                name="qdrant",
                status="degraded",
                response_time_ms=(time.time() - start) * 1000,
                message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_providers(self) -> list[HealthStatus]:
        """Check configured AI providers."""
        from devplane.providers import get_all_providers
        from devplane.credits import check_budget
        
        providers = await get_all_providers()
        results = []
        
        for prov in providers:
            if not prov.get("enabled") or not prov.get("api_key"):
                continue
            
            start = time.time()
            try:
                allowed, reason = await check_budget(prov["name"], 0)
                latency = (time.time() - start) * 1000
                
                if allowed:
                    results.append(HealthStatus(
                        name=f"provider_{prov['name']}",
                        status="healthy",
                        response_time_ms=latency,
                        message="API key valid, budget available",
                        last_check=datetime.utcnow()
                    ))
                else:
                    results.append(HealthStatus(
                        name=f"provider_{prov['name']}",
                        status="degraded",
                        response_time_ms=latency,
                        message=f"Budget exhausted: {reason}",
                        last_check=datetime.utcnow()
                    ))
            except Exception as e:
                results.append(HealthStatus(
                    name=f"provider_{prov['name']}",
                    status="unhealthy",
                    response_time_ms=(time.time() - start) * 1000,
                    message=str(e),
                    last_check=datetime.utcnow()
                ))
        
        return results
    
    async def check_digitalocean(self) -> HealthStatus:
        """Check DigitalOcean API connectivity."""
        start = time.time()
        try:
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            
            if not mgr.configured:
                return HealthStatus(
                    name="digitalocean",
                    status="degraded",
                    response_time_ms=0,
                    message="Not configured (DIGITALOCEAN_TOKEN not set)",
                    last_check=datetime.utcnow()
                )
            
            # Try API call
            await mgr._api("GET", "/account")
            latency = (time.time() - start) * 1000
            return HealthStatus(
                name="digitalocean",
                status="healthy",
                response_time_ms=latency,
                message="API accessible",
                last_check=datetime.utcnow()
            )
        except Exception as e:
            return HealthStatus(
                name="digitalocean",
                status="unhealthy",
                response_time_ms=(time.time() - start) * 1000,
                message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_cloudflare(self) -> HealthStatus:
        """Check Cloudflare API connectivity."""
        start = time.time()
        try:
            from devplane.infra.cloudflare import get_cloudflare_manager
            cf = get_cloudflare_manager()
            
            if not cf.configured:
                return HealthStatus(
                    name="cloudflare",
                    status="degraded",
                    response_time_ms=0,
                    message="Not configured (CLOUDFLARE_API_KEY not set)",
                    last_check=datetime.utcnow()
                )
            
            # Try API call
            await cf.list_dns_records()
            latency = (time.time() - start) * 1000
            return HealthStatus(
                name="cloudflare",
                status="healthy",
                response_time_ms=latency,
                message="API accessible",
                last_check=datetime.utcnow()
            )
        except Exception as e:
            return HealthStatus(
                name="cloudflare",
                status="unhealthy",
                response_time_ms=(time.time() - start) * 1000,
                message=str(e),
                last_check=datetime.utcnow()
            )
    
    async def check_slack(self) -> HealthStatus:
        """Check Slack bot status."""
        from devplane.slack.bot import slack_handler
        
        if slack_handler is None:
            return HealthStatus(
                name="slack",
                status="degraded",
                response_time_ms=0,
                message="Not configured (SLACK_BOT_TOKEN not set)",
                last_check=datetime.utcnow()
            )
        
        return HealthStatus(
            name="slack",
            status="healthy",
            response_time_ms=0,
            message="Bot initialized",
            last_check=datetime.utcnow()
        )
    
    async def check_sandboxes(self) -> HealthStatus:
        """Check Sandbox infrastructure status."""
        start = time.time()
        try:
            from devplane.infra.manager import get_infra_manager
            mgr = get_infra_manager()
            
            if not mgr.configured:
                return HealthStatus(
                    name="sandboxes",
                    status="degraded",
                    response_time_ms=0,
                    message="Not configured (DIGITALOCEAN_TOKEN not set)",
                    last_check=datetime.utcnow()
                )
            
            # List droplets to see if we can query them
            droplets = await mgr.list_droplets()
            sandbox_count = sum(1 for d in droplets if "sandbox" in d.get("tags", []) or d.get("name", "").startswith("sandbox-"))
            
            latency = (time.time() - start) * 1000
            return HealthStatus(
                name="sandboxes",
                status="healthy",
                response_time_ms=latency,
                message=f"API accessible, {sandbox_count} active sandboxes",
                last_check=datetime.utcnow()
            )
        except Exception as e:
            return HealthStatus(
                name="sandboxes",
                status="unhealthy",
                response_time_ms=(time.time() - start) * 1000,
                message=str(e),
                last_check=datetime.utcnow()
            )

    async def get_full_health_report(self) -> dict:
        """Get comprehensive health report for all services."""
        cache_key = "full_report"
        now = time.time()
        
        if cache_key in self._cache and now - self._cache_time < self._cache_ttl:
            cached = self._cache[cache_key]
            return {
                "status": "healthy" if all(s.status == "healthy" for s in cached) else "degraded",
                "timestamp": datetime.utcnow().isoformat(),
                "services": [
                    {
                        "name": s.name,
                        "status": s.status,
                        "response_time_ms": round(s.response_time_ms, 2),
                        "message": s.message,
                    }
                    for s in cached
                ]
            }
        
        # Run all checks
        checks = []
        checks.append(await self.check_database())
        checks.append(await self.check_qdrant())
        checks.append(await self.check_digitalocean())
        checks.append(await self.check_cloudflare())
        checks.append(await self.check_slack())
        checks.extend(await self.check_providers())
        
        self._cache[cache_key] = checks
        self._cache_time = now
        
        healthy_count = sum(1 for c in checks if c.status == "healthy")
        degraded_count = sum(1 for c in checks if c.status == "degraded")
        
        overall_status = "healthy"
        if degraded_count > 0:
            overall_status = "degraded"
        if healthy_count < len(checks) / 2:
            overall_status = "unhealthy"
        
        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total": len(checks),
                "healthy": healthy_count,
                "degraded": degraded_count,
                "unhealthy": len(checks) - healthy_count - degraded_count,
            },
            "services": [
                {
                    "name": s.name,
                    "status": s.status,
                    "response_time_ms": round(s.response_time_ms, 2),
                    "message": s.message,
                }
                for s in checks
            ]
        }

# Global health checker
health_checker = HealthChecker()


# ─── Prometheus-Style Metrics Export ─────────────────────────────────────────

def generate_prometheus_metrics() -> str:
    """Generate Prometheus-style metrics for monitoring systems."""
    lines = []
    summary = metrics.get_summary()
    
    # Request metrics
    lines.append("# HELP devplane_requests_total Total number of requests")
    lines.append("# TYPE devplane_requests_total counter")
    lines.append(f'devplane_requests_total {summary["requests"].get("total", 0)}')
    
    # LLM metrics
    lines.append("# HELP devplane_llm_calls_total Total LLM API calls")
    lines.append("# TYPE devplane_llm_calls_total counter")
    lines.append(f'devplane_llm_calls_total {summary["llm"]["calls_total"]}')
    
    lines.append("# HELP devplane_llm_tokens_total Total tokens processed")
    lines.append("# TYPE devplane_llm_tokens_total counter")
    lines.append(f'devplane_llm_tokens_total{{direction="in"}} {summary["llm"]["tokens_in"]}')
    lines.append(f'devplane_llm_tokens_total{{direction="out"}} {summary["llm"]["tokens_out"]}')
    
    lines.append("# HELP devplane_llm_cost_total Total LLM API cost")
    lines.append("# TYPE devplane_llm_cost_total counter")
    lines.append(f'devplane_llm_cost_total {summary["llm"]["cost_total"]}')
    
    # Error metrics
    lines.append("# HELP devplane_errors_total Total errors")
    lines.append("# TYPE devplane_errors_total counter")
    lines.append(f'devplane_errors_total {summary["errors"].get("total", 0)}')
    
    # Latency metrics
    lines.append("# HELP devplane_request_latency_ms Request latency")
    lines.append("# TYPE devplane_request_latency_ms gauge")
    lines.append(f'devplane_request_latency_ms{{quantile="avg"}} {summary["latency"]["avg_ms"]}')
    lines.append(f'devplane_request_latency_ms{{quantile="p95"}} {summary["latency"]["p95_ms"]}')
    
    return "\n".join(lines)
