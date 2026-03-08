import asyncio
import json
import logging
from unittest.mock import patch
from typing import Any
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from mcp_server_devplane import handle_call_tool

logging.basicConfig(level=logging.INFO)

async def test_mcp():
    print("Testing ask_any_role (planner)...")
    try:
        res1 = await handle_call_tool("ask_any_role", {"role": "planner", "prompt": "Give me a 3 step plan to learn python."})
        print("Response 1:", res1[0].text if res1 else "No response")
    except Exception as e:
        print("Error 1:", e)
        
    print("\n-------------------------------\n")
        
    print("Testing run_devplane_routing (agent)...")
    try:
        res2 = await handle_call_tool("run_devplane_routing", {"mode": "agent", "prompt": "What is 2+2?"})
        print("Response 2:", res2[0].text if res2 else "No response")
    except Exception as e:
        print("Error 2:", e)

if __name__ == "__main__":
    asyncio.run(test_mcp())
