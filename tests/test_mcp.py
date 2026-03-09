import asyncio
import sys
sys.path.append('.')
from devplane.infra.mcp_server import list_tools

async def test():
    tools = await list_tools()
    print(f"Number of tools: {len(tools)}")
    for tool in tools[:5]:
        print(f"  - {tool.name}")

if __name__ == "__main__":
    asyncio.run(test())