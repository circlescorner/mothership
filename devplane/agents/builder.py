import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("devplane.agents.builder")

class BuilderAgent:
    """
    Persistent agent dedicated to building and implementing improvements on DevPlane itself.
    """
    def __init__(self):
        self.is_running = False
        self.task_queue = asyncio.Queue()

    async def start(self):
        self.is_running = True
        logger.info("Builder Agent started.")
        asyncio.create_task(self._build_loop())

    def stop(self):
        self.is_running = False
        logger.info("Builder Agent stopped.")

    async def submit_improvement_task(self, task_description: str):
        """Submit a new improvement task to the builder."""
        await self.task_queue.put(task_description)
        logger.info(f"Improvement task queued: {task_description}")

    async def _build_loop(self):
        while self.is_running:
            try:
                # Wait for a task
                task = await self.task_queue.get()
                logger.info(f"Builder Agent processing task: {task}")
                
                # Simulate building/implementing
                await self._implement_improvement(task)
                
                self.task_queue.task_done()
            except Exception as e:
                logger.error(f"Error in Builder loop: {e}")
            
            await asyncio.sleep(1)

    async def _implement_improvement(self, task: str):
        """Simulate the process of implementing an improvement."""
        logger.info(f"Analyzing codebase for: {task}")
        await asyncio.sleep(2)
        
        logger.info(f"Generating code changes for: {task}")
        await asyncio.sleep(3)
        
        logger.info(f"Applying changes and running tests for: {task}")
        await asyncio.sleep(2)
        
        logger.info(f"Successfully implemented: {task}")

# Singleton instance
_builder_agent = None

def get_builder_agent() -> BuilderAgent:
    global _builder_agent
    if _builder_agent is None:
        _builder_agent = BuilderAgent()
    return _builder_agent
