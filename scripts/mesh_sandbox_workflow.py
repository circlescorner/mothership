#!/usr/bin/env python3
"""
Mesh-Sandbox Integration Example Workflow.

This script demonstrates a workflow where code is executed in a secure sandbox,
and if it fails, the error is passed to the DevPlane Mesh (vibe_code) to debug
and fix the code automatically, before retrying in a new sandbox.
"""

import os
import sys
import asyncio
import logging
import json

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
from devplane.chain.mesh import run_mesh
from devplane.providers import load_all_keys_to_env
from devplane.db import init_db
from devplane.roles import load_from_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mesh_sandbox_workflow")

# A deliberately buggy script (SyntaxError or TypeError)
BUGGY_SCRIPT = """
def calculate_fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    
    # Bug: trying to add integer to list directly
    sequence = [0, 1]
    for i in range(2, n):
        next_val = sequence[i-1] + sequence[i-2]
        sequence = sequence + next_val  # TypeError here
        
    return sequence

print("Calculating Fibonacci sequence up to 5...")
result = calculate_fibonacci(5)
print(f"Result: {result}")
"""

async def main():
    logger.info("Initializing DevPlane environment...")
    await load_all_keys_to_env()
    await init_db()
    await load_from_db()
    
    sandbox_mgr = get_sandbox_manager()
    
    logger.info("Step 1: Running buggy script in sandbox...")
    logger.info(f"Script content:\n{BUGGY_SCRIPT}")
    
    result1 = await sandbox_mgr.run_safe_task(BUGGY_SCRIPT)
    
    if result1.get("success"):
        logger.error("Wait, the buggy script succeeded? That shouldn't happen.")
        return
        
    error_output = result1.get("stderr", "Unknown error")
    logger.info(f"Step 2: Script failed as expected. Error output:\n{error_output}")
    
    logger.info("Step 3: Calling DevPlane Mesh (vibe_code) to fix the code...")
    
    fix_task = f"""
I have a Python script that is failing with an error. Please fix the code.
Return ONLY the fixed Python code, no markdown formatting or explanations.

Original Code:
```python
{BUGGY_SCRIPT}
```

Error Output:
```
{error_output}
```
"""
    
    mesh_result = await run_mesh(fix_task)
    fixed_code = mesh_result.get("code", "")
    
    # Clean up markdown if the model included it despite instructions
    if fixed_code.startswith("```python"):
        fixed_code = fixed_code[9:]
    if fixed_code.startswith("```"):
        fixed_code = fixed_code[3:]
    if fixed_code.endswith("```"):
        fixed_code = fixed_code[:-3]
        
    fixed_code = fixed_code.strip()
    
    logger.info(f"Step 4: Mesh provided fixed code:\n{fixed_code}")
    
    logger.info("Step 5: Running fixed script in a new sandbox...")
    result2 = await sandbox_mgr.run_safe_task(fixed_code)
    
    if result2.get("success"):
        logger.info("Success! The fixed code ran perfectly.")
        logger.info(f"Output:\n{result2.get('stdout')}")
    else:
        logger.error("The fixed code still failed.")
        logger.error(f"Error:\n{result2.get('stderr')}")

if __name__ == "__main__":
    asyncio.run(main())
