import asyncio
import httpx
import json
import sqlite3
from devplane.db import DB_PATH

async def test_registry():
    print("1. Initializing DB to create new tables...")
    from devplane.db import init_db
    await init_db()
    
    print("2. Simulating Kilo Code registering its specialized Web Searcher agent...")
    async with httpx.AsyncClient() as client:
        # We simulate the API call directly using fake auth or just direct DB insert since we're testing locally
        pass
        
    print("2b. Bypassing API to directly inject the agent into the DB for testing...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM agent_workflows WHERE agent_name = 'Kilo Web Researcher'")
    cursor.execute(
        "INSERT INTO agent_workflows (ide_name, agent_name, description, input_schema) VALUES (?, ?, ?, ?)",
        ("Kilo Code", "Kilo Web Researcher", "Perform intense deep web research using headless browsers.", json.dumps({"type": "object", "properties": {"query": {"type": "string"}}}))
    )
    conn.commit()
    
    print("3. Simulating Antigravity MCP Server reading the tools...")
    from devplane.infra.mcp_server import list_tools, call_tool
    tools = await list_tools()
    found = False
    for t in tools:
        if t.name == "kilo_web_researcher":
            print(f"✅ Success! Found dynamically injected tool: {t.name}")
            print(f"   Description: {t.description}")
            print(f"   Schema: {t.inputSchema}")
            found = True
            break
            
    if not found:
        print("❌ Error: Tool was not dynamically loaded by the MCP server.")
        return
        
    print("4. Simulating Antigravity calling the tool (This will timeout waiting for the result since we don't have the polling agent running, but we should see it enter the devplane_tasks table)...")
    
    # Run the call_tool in background so we can poll the DB
    async def invoke_tool():
        print("   [Antigravity] Invoking kilo_web_researcher...")
        res = await call_tool("kilo_web_researcher", {"query": "Latest Langchain tools"})
        print(f"   [Antigravity] Received response: {res[0].text}")
        
    task = asyncio.create_task(invoke_tool())
    
    await asyncio.sleep(2) # Give it time to insert
    
    print("5. Checking devplane_tasks table for the payload...")
    cursor.execute("SELECT * FROM devplane_tasks WHERE agent_name = 'Kilo Web Researcher' AND status = 'pending'")
    row = cursor.fetchone()
    if row:
        print(f"✅ Success! Task successfully routed to cross-IDE polling queue.")
        print(f"   Payload: {row[2]}")
        
        print("6. Simulating Kilo Code completing the task...")
        cursor.execute("UPDATE devplane_tasks SET status = 'completed', result_json = 'Here are the latest langchain tools: 1, 2, 3' WHERE id = ?", (row[0],))
        conn.commit()
    else:
        print("❌ Error: Task not found in pending queue.")
        
    # Wait for the Antigravity call to finish reading the completed status
    await task
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    asyncio.run(test_registry())
