import asyncio
import logging
from typing import Dict, Any
from devplane.infra.manager import get_infra_manager

logger = logging.getLogger("devplane.agents.infra_manager")

class InfraManagerAgent:
    """
    Persistent agent dedicated to managing infrastructure, maintaining documented status,
    and handling scale-to-zero operations.
    """
    def __init__(self):
        self.infra_manager = get_infra_manager()
        self.is_running = False

    async def start(self):
        self.is_running = True
        logger.info("Infra Manager Agent started.")
        asyncio.create_task(self._monitor_loop())

    def stop(self):
        self.is_running = False
        logger.info("Infra Manager Agent stopped.")

    async def _monitor_loop(self):
        while self.is_running:
            try:
                await self._check_and_scale_to_zero()
                await self._update_status_docs()
            except Exception as e:
                logger.error(f"Error in Infra Manager loop: {e}")
            
            # Run every 5 minutes
            await asyncio.sleep(300)

    async def _check_and_scale_to_zero(self):
        """Check for idle resources and scale them to zero (snapshot and destroy)."""
        logger.info("Checking for idle resources to scale to zero...")
        
        # Check budget first
        from devplane.credits import get_credit_summary
        summary = await get_credit_summary()
        
        # If we are over 90% of daily budget, aggressively scale down everything non-essential
        aggressive_scale_down = False
        if summary["total_today"] >= summary["budget_daily"] * 0.9:
            logger.warning("Approaching daily budget limit! Enabling aggressive scale-to-zero.")
            aggressive_scale_down = True
            
        droplets = await self.infra_manager.list_droplets()
        
        for d in droplets:
            if d["status"] != "active":
                continue
                
            # In aggressive mode, scale down everything except the main control plane
            if aggressive_scale_down and "control-plane" not in d["name"]:
                logger.info(f"Aggressive scale down: {d['name']}")
                snap_name = f"budget-sleep-{d['name']}-{int(asyncio.get_event_loop().time())}"
                await self.infra_manager.snapshot_droplet(d["id"], snap_name)
                await self.infra_manager.destroy_droplet(d["id"])
                continue
                
            # Normal heuristic: if it's a worker and has been running for a while, maybe scale down
            # In a real system, this would check metrics or active connections
            if "worker" in d["name"]:
                logger.info(f"Scaling down idle worker: {d['name']}")
                snap_name = f"auto-sleep-{d['name']}-{int(asyncio.get_event_loop().time())}"
                await self.infra_manager.snapshot_droplet(d["id"], snap_name)
                await self.infra_manager.destroy_droplet(d["id"])

    async def _update_status_docs(self):
        """Maintain documented status of all infra."""
        logger.info("Updating infrastructure status documentation...")
        droplets = await self.infra_manager.list_droplets()
        
        status_doc = "# Infrastructure Status\n\n"
        status_doc += "## Active Droplets\n"
        for d in droplets:
            status_doc += f"- **{d['name']}** (ID: {d['id']}): {d['status']}\n"
            
        # Write to a local file or push to a wiki
        with open("data/infra_status.md", "w") as f:
            f.write(status_doc)

# Singleton instance
_infra_agent = None

def get_infra_agent() -> InfraManagerAgent:
    global _infra_agent
    if _infra_agent is None:
        _infra_agent = InfraManagerAgent()
    return _infra_agent
