import asyncio
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from devplane.chain.agent import get_agent_graph

load_dotenv()

async def test():
    print("Testing LangGraph Compilation with Saver...")
    try:
        async with AsyncSqliteSaver.from_conn_string("devplane.db") as checkpointer:
            graph = get_agent_graph(checkpointer=checkpointer)
            print("Graph compiled successfully:", type(graph))
            
            # Test a simple run
            print("\nTesting agent execution (simple math)...")
            config = {"configurable": {"thread_id": "test_thread_1"}}
            
            async for event in graph.astream(
                {"messages": [HumanMessage(content="What is 15 * 4?")], "current_tier": "groq/llama3-8b-8192"},
                config,
                stream_mode="updates"
            ):
                print("EVENT:", event)
            
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    asyncio.run(test())
