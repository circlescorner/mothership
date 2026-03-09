#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '.')
from devplane.chain.mesh import run_mesh

async def test():
    try:
        # Run mesh with a simple task, expecting it to fail due to missing API keys
        # but we just want to ensure no configuration errors.
        result = await run_mesh("print hello world", max_iterations=2)
        print("Result status:", result.get('status'))
        print("Error if any:", result.get('error'))
        # If status is error due to LLM, that's fine.
        # Check that max_iterations was used (should be 2)
        # We can't easily verify but we can print result iterations
        print("Iterations:", result.get('iterations'))
    except Exception as e:
        print("Unexpected exception:", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test())