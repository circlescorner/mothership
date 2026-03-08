#!/usr/bin/env python3
"""Test config endpoints with proper authentication."""
import asyncio
import aiohttp
import json
import sys
import time

BASE_URL = "http://localhost:8000"
SESSION_COOKIE_NAME = "devplane_session"

async def register_user(session: aiohttp.ClientSession) -> bool:
    """Register a new test user."""
    register_data = {
        "username": "configtest",
        "email": "configtest@example.com",
        "password": "ConfigTest123!",
        "full_name": "Config Test User"
    }
    try:
        async with session.post(f"{BASE_URL}/api/auth/register", json=register_data) as resp:
            if resp.status == 201:
                print("Registered configtest user")
                return True
            elif resp.status == 400:
                # User may already exist
                print("User already exists, continuing")
                return True
            else:
                print(f"Registration failed: {resp.status} - {await resp.text()}")
                return False
    except Exception as e:
        print(f"Registration error: {e}")
        return False

async def login_and_get_cookie(session: aiohttp.ClientSession) -> str:
    """Login and return session cookie value."""
    login_data = {
        "username": "configtest",
        "password": "ConfigTest123!"
    }
    async with session.post(f"{BASE_URL}/api/auth/login", json=login_data) as resp:
        if resp.status == 200:
            # Check if MFA required
            data = await resp.json()
            if data.get("mfa_required"):
                print("ERROR: MFA required for user configtest. Cannot proceed.")
                sys.exit(1)
            # Extract cookie from response headers
            cookie = resp.cookies.get(SESSION_COOKIE_NAME)
            if cookie:
                cookie_value = cookie.value
                print(f"Logged in successfully, session cookie: {cookie_value[:10]}...")
                return cookie_value
            else:
                # Try to get Set-Cookie header manually
                set_cookie = resp.headers.get('Set-Cookie')
                if set_cookie:
                    # parse
                    import re
                    match = re.search(rf'{SESSION_COOKIE_NAME}=([^;]+)', set_cookie)
                    if match:
                        cookie_value = match.group(1)
                        print(f"Extracted cookie from header: {cookie_value[:10]}...")
                        return cookie_value
                print("WARNING: No session cookie found in response.")
                return ""
        else:
            print(f"Login failed: {resp.status} - {await resp.text()}")
            return ""

async def test_get_roles(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.get(f"{BASE_URL}/api/config/roles", headers=headers) as resp:
        print(f"GET /api/config/roles -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {json.dumps(data, indent=2)}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_role(session, cookie):
    payload = {"models": ["openrouter/anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat"]}
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.put(f"{BASE_URL}/api/config/roles/architect", json=payload, headers=headers) as resp:
        print(f"PUT /api/config/roles/architect -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_delete_role(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.delete(f"{BASE_URL}/api/config/roles/testrole", headers=headers) as resp:
        print(f"DELETE /api/config/roles/testrole -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_get_memory(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.get(f"{BASE_URL}/api/config/memory", headers=headers) as resp:
        print(f"GET /api/config/memory -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {json.dumps(data, indent=2)}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_memory(session, cookie):
    payload = {
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "qdrant_url": "http://localhost:6333",
        "qdrant_collection": "devplane_memories",
        "max_memory_items": 5000
    }
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.put(f"{BASE_URL}/api/config/memory", json=payload, headers=headers) as resp:
        print(f"PUT /api/config/memory -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_get_optimizer(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.get(f"{BASE_URL}/api/config/optimizer", headers=headers) as resp:
        print(f"GET /api/config/optimizer -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {json.dumps(data, indent=2)}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_optimizer(session, cookie):
    # scoring_weights_json must be a JSON string
    payload = {
        "complexity_threshold": 0.7,
        "scoring_weights_json": '{"accuracy": 0.5, "cost": 0.3, "speed": 0.2}',
        "max_iterations": 5,
        "timeout_seconds": 45
    }
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.put(f"{BASE_URL}/api/config/optimizer", json=payload, headers=headers) as resp:
        print(f"PUT /api/config/optimizer -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_get_tools(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.get(f"{BASE_URL}/api/config/tools", headers=headers) as resp:
        print(f"GET /api/config/tools -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Found {len(data)} tools")
            for tool in data[:3]:
                print(f"    - {tool['tool_name']} enabled={tool['enabled']}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_put_tool(session, cookie):
    payload = {"enabled": False, "timeout_seconds": 45}
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.put(f"{BASE_URL}/api/config/tools/write_file", json=payload, headers=headers) as resp:
        print(f"PUT /api/config/tools/write_file -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_post_mcp_server(session, cookie):
    payload = {
        "display_name": "Test MCP Server",
        "server_type": "custom",
        "endpoint": "http://localhost:8001",
        "config_json": {"key": "value"}
    }
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.post(f"{BASE_URL}/api/config/mcp_servers", json=payload, headers=headers) as resp:
        print(f"POST /api/config/mcp_servers -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_sync_mcp_server(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.post(f"{BASE_URL}/api/config/mcp_servers/test_mcp_server/sync", headers=headers) as resp:
        print(f"POST /api/config/mcp_servers/test_mcp_server/sync -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def test_delete_mcp_server(session, cookie):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
    async with session.delete(f"{BASE_URL}/api/config/mcp_servers/test_mcp_server", headers=headers) as resp:
        print(f"DELETE /api/config/mcp_servers/test_mcp_server -> {resp.status}")
        if resp.status == 200:
            data = await resp.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {await resp.text()}")

async def main():
    print("Testing DevPlane config endpoints with authentication...")
    # Create a session without cookie jar to avoid secure flag issues
    # We'll manually manage cookies
    async with aiohttp.ClientSession() as session:
        # Register user
        success = await register_user(session)
        if not success:
            print("Failed to register user, exiting.")
            return
        
        # Login and get cookie
        cookie = await login_and_get_cookie(session)
        if not cookie:
            print("Failed to obtain session cookie, exiting.")
            return
        
        # Add a small delay to avoid rate limiting
        await asyncio.sleep(1)
        
        # GET endpoints
        await test_get_roles(session, cookie)
        await asyncio.sleep(0.5)
        await test_get_memory(session, cookie)
        await asyncio.sleep(0.5)
        await test_get_optimizer(session, cookie)
        await asyncio.sleep(0.5)
        await test_get_tools(session, cookie)
        await asyncio.sleep(0.5)
        
        # PUT endpoints
        await test_put_role(session, cookie)
        await asyncio.sleep(0.5)
        await test_put_memory(session, cookie)
        await asyncio.sleep(0.5)
        await test_put_optimizer(session, cookie)
        await asyncio.sleep(0.5)
        await test_put_tool(session, cookie)
        await asyncio.sleep(0.5)
        
        # POST endpoints
        await test_post_mcp_server(session, cookie)
        await asyncio.sleep(0.5)
        await test_sync_mcp_server(session, cookie)
        await asyncio.sleep(0.5)
        
        # DELETE endpoints
        await test_delete_role(session, cookie)
        await asyncio.sleep(0.5)
        await test_delete_mcp_server(session, cookie)
        await asyncio.sleep(0.5)
        
        print("\nAll tests completed.")

if __name__ == "__main__":
    asyncio.run(main())