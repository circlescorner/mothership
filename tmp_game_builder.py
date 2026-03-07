import asyncio
from devplane.chain.agent import get_agent_graph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import HumanMessage
import json
from devplane.providers import load_all_keys_to_env
from devplane.infra.mcp import get_mcp_manager

async def run():
    print("Loading API keys from DB...")
    await load_all_keys_to_env()
    
    print("Connecting to local SQLite MCP Server...")
    mcp_manager = get_mcp_manager()
    await mcp_manager.connect_local_server(
        name="devplane_db",
        command="python",
        args=["-m", "mcp_server_sqlite", "--db-path", "devplane.db"]
    )
    
    async with AsyncSqliteSaver.from_conn_string("devplane.db") as checkpointer:
        graph = get_agent_graph(checkpointer=checkpointer)
        
        prompt = "Look at my database using your MCP tools. Tell me what tables exist, and how many Workspaces we have deployed right now."
        
        inputs = {
            "messages": [HumanMessage(content=prompt)],
            "project_id": 0,
            "current_tier": "openrouter/anthropic/claude-3.5-sonnet"
        }
        config = {"configurable": {"thread_id": "game_builder_1"}}
        
        print("Running agent...")
        result = await graph.ainvoke(inputs, config)
        print("Final Output:")
        print(result["messages"][-1].content)
        
    print("Cleaning up MCP Server...")
    await mcp_manager.cleanup()

if __name__ == "__main__":
    asyncio.run(run())
