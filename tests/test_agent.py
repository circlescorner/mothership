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
            
            # Use deepseek model which has a valid API key
            # Collect events with timeout
            events = []
            try:
                # Create an async generator
                stream = graph.astream(
                    {"messages": [HumanMessage(content="What is 15 * 4?")], "current_tier": "deepseek/deepseek-chat"},
                    config,
                    stream_mode="updates"
                )
                # Use asyncio.wait_for with async generator
                async for event in stream:
                    events.append(event)
                    print("EVENT:", event)
                    # Break after a few events to avoid infinite loop
                    if len(events) > 10:
                        break
                print(f"Test completed with {len(events)} events")
            except asyncio.TimeoutError:
                print("ERROR: Test timed out")
            except Exception as e:
                print(f"ERROR during execution: {e}")
                
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    asyncio.run(test())
