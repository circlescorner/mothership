#!/usr/bin/env python3
"""Comprehensive test of new config endpoints."""
import asyncio
import aiohttp
import json
import sys

BASE_URL = "http://localhost:8000"
SESSION_COOKIE_NAME = "session_id"

async def login(session: aiohttp.ClientSession) -> bool:
    """Attempt to login with default credentials (admin/admin)."""
    try:
        # Try to register a new user first
        register_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "TestPassword123!",
            "full_name": "Test User"
        }
        async with session.post(f"{BASE_URL}/api/auth/register", json=register_data) as resp:
            if resp.status == 201:
                print("Registered test user")
            elif resp.status == 400:
                # User may already exist, try login
                pass
            else:
                print(f"Registration failed: {resp.status}")
                # Continue anyway
        # Now login
        login_data = {
            "username": "testuser",
            "password": "TestPassword123!"
        }
        async with session.post(f"{BASE_URL}/api/auth/login", json=login_data) as resp:
            if resp.status == 200:
                print("Logged in successfully")
                # Session cookie will be set automatically via Set-Cookie
                return True
            else:
                print(f"Login failed: {resp.status}")
                return False
    except Exception as e:
        print(f"Login error: {e}")
        return False

async def test_get_roles(session):
    async with session.get(f"{BASE_URL}/api/config/roles") as resp:
        print(f"GET /api/config/roles -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {json.dumps(data, indent=2)}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_role(session):
    payload = {"models": ["openrouter/anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat"]}
    async with session.put(f"{BASE_URL}/api/config/roles/architect", json=payload) as resp:
        print(f"PUT /api/config/roles/architect -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_delete_role(session):
    async with session.delete(f"{BASE_URL}/api/config/roles/testrole") as resp:
        print(f"DELETE /api/config/roles/testrole -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_get_memory(session):
    async with session.get(f"{BASE_URL}/api/config/memory") as resp:
        print(f"GET /api/config/memory -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {json.dumps(data, indent=2)}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_memory(session):
    payload = {
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "qdrant_url": "http://localhost:6333",
        "qdrant_collection": "devplane_memories",
        "max_memory_items": 5000
    }
    async with session.put(f"{BASE_URL}/api/config/memory", json=payload) as resp:
        print(f"PUT /api/config/memory -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_get_optimizer(session):
    async with session.get(f"{BASE_URL}/api/config/optimizer") as resp:
        print(f"GET /api/config/optimizer -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {json.dumps(data, indent=2)}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_optimizer(session):
    payload = {
        "complexity_threshold": 0.7,
        "scoring_weights_json": {"accuracy": 0.5, "cost": 0.3, "speed": 0.2},
        "max_iterations": 5,
        "timeout_seconds": 45
    }
    async with session.put(f"{BASE_URL}/api/config/optimizer", json=payload) as resp:
        print(f"PUT /api/config/optimizer -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_get_tools(session):
    async with session.get(f"{BASE_URL}/api/config/tools") as resp:
        print(f"GET /api/config/tools -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Found {len(data)} tools")
            for tool in data[:3]:
                print(f"    - {tool['tool_name']} enabled={tool['enabled']}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_tool(session):
    payload = {"enabled": False, "timeout_seconds": 45}
    async with session.put(f"{BASE_URL}/api/config/tools/write_file", json=payload) as resp:
        print(f"PUT /api/config/tools/write_file -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_post_mcp_server(session):
    payload = {
        "display_name": "Test MCP Server",
        "server_type": "custom",
        "endpoint": "http://localhost:8001",
        "config_json": {"key": "value"}
    }
    async with session.post(f"{BASE_URL}/api/config/mcp_servers", json=payload) as resp:
        print(f"POST /api/config/mcp_servers -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_sync_mcp_server(session):
    async with session.post(f"{BASE_URL}/api/config/mcp_servers/test_mcp_server/sync") as resp:
        print(f"POST /api/config/mcp_servers/test_mcp_server/sync -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_delete_mcp_server(session):
    async with session.delete(f"{BASE_URL}/api/config/mcp_servers/test_mcp_server") as resp:
        print(f"DELETE /api/config/mcp_servers/test_mcp_server -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def main():
    print("Testing DevPlane config endpoints...")
    async with aiohttp.ClientSession() as session:
        # Attempt login (optional)
        logged_in = await login(session)
        if not logged_in:
            print("Warning: Could not authenticate; endpoints may return 401.")
        
        # GET endpoints
        await test_get_roles(session)
        await test_get_memory(session)
        await test_get_optimizer(session)
        await test_get_tools(session)
        
        # PUT endpoints
        await test_put_role(session)
        await test_put_memory(session)
        await test_put_optimizer(session)
        await test_put_tool(session)
        
        # POST endpoints
        await test_post_mcp_server(session)
        await test_sync_mcp_server(session)
        
        # DELETE endpoints
        await test_delete_role(session)
        await test_delete_mcp_server(session)
        
        print("\nAll tests completed.")

if __name__ == "__main__":
    asyncio.run(main())