#!/usr/bin/env python3
"""
Scalability Testing Script for DevPlane Sandboxes.

This script runs load tests with multiple interacting sandbox instances
to verify reliability under concurrent usage.
"""

import os
import sys
import asyncio
import logging
import time
import argparse

# Add parent directory to path to import devplane
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key, value.strip("'\""))

load_env_file()

from devplane.infra.sandbox import get_sandbox_manager
from devplane.infra.manager import get_infra_manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("sandbox_scalability")

async def run_single_sandbox_test(sandbox_id: int, system_type: str = "basic") -> dict:
    """Run a single sandbox test end-to-end."""
    logger.info(f"Starting sandbox test {sandbox_id} (type: {system_type})")
    start_time = time.time()
    
    sandbox_mgr = get_sandbox_manager()
    
    # Simple script to run in the sandbox
    test_script = f"""
import sys
import time

print("Sandbox {sandbox_id} execution started")
time.sleep(2)
print("Sandbox {sandbox_id} execution completed")
sys.exit(0)
"""
    
    try:
        # Run the safe task which handles deploy, execute, and destroy
        result = await sandbox_mgr.run_safe_task(test_script, system_type=system_type)
        
        duration = time.time() - start_time
        logger.info(f"Sandbox test {sandbox_id} completed in {duration:.2f}s. Success: {result.get('success', False)}")
        
        return {
            "id": sandbox_id,
            "success": result.get("success", False),
            "duration": duration,
            "result": result
        }
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Sandbox test {sandbox_id} failed after {duration:.2f}s: {e}")
        return {
            "id": sandbox_id,
            "success": False,
            "duration": duration,
            "error": str(e)
        }

async def run_scalability_test(concurrent_instances: int, system_type: str = "basic"):
    """Run multiple sandbox tests concurrently."""
    logger.info(f"Starting scalability test with {concurrent_instances} concurrent instances (type: {system_type})")
    
    mgr = get_infra_manager()
    if not mgr.configured:
        logger.error("DigitalOcean is not configured. Please set DIGITALOCEAN_TOKEN.")
        return
        
    start_time = time.time()
    
    # Create tasks for concurrent execution
    tasks = []
    for i in range(concurrent_instances):
        tasks.append(run_single_sandbox_test(i + 1, system_type))
        
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)
    
    total_duration = time.time() - start_time
    
    # Analyze results
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful
    
    logger.info("=" * 50)
    logger.info("SCALABILITY TEST RESULTS")
    logger.info("=" * 50)
    logger.info(f"Total instances: {concurrent_instances}")
    logger.info(f"System type: {system_type}")
    logger.info(f"Total duration: {total_duration:.2f}s")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Success rate: {(successful / concurrent_instances) * 100:.1f}%")
    
    if failed > 0:
        logger.info("\nFailed instances details:")
        for r in results:
            if not r["success"]:
                logger.info(f"  Instance {r['id']}: {r.get('error', r.get('result', 'Unknown error'))}")
                
    logger.info("=" * 50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run sandbox scalability tests")
    parser.add_argument("-c", "--concurrent", type=int, default=3, help="Number of concurrent sandbox instances to run")
    parser.add_argument("-t", "--type", type=str, choices=["basic", "docker", "kubernetes"], default="basic", help="System type for sandboxes")
    
    args = parser.parse_args()
    
    asyncio.run(run_scalability_test(args.concurrent, args.type))
