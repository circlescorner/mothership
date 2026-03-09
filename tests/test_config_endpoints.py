#!/usr/bin/env python3
"""Quick test of new config endpoints."""
import asyncio
import aiohttp
import json
import sys

BASE_URL = "http://localhost:8000"

async def test_get_roles():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/config/roles") as resp:
            print(f"GET /api/config/roles -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {json.dumps(data, indent=2)}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_get_memory():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/config/memory") as resp:
            print(f"GET /api/config/memory -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {json.dumps(data, indent=2)}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_get_optimizer():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/config/optimizer") as resp:
            print(f"GET /api/config/optimizer -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {json.dumps(data, indent=2)}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_get_tools():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/config/tools") as resp:
            print(f"GET /api/config/tools -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Found {len(data)} tools")
                for tool in data[:3]:
                    print(f"    - {tool['tool_name']} enabled={tool['enabled']}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_put_memory():
    async with aiohttp.ClientSession() as session:
        payload = {"embedding_model": "text-embedding-3-small", "embedding_dimension": 1536}
        async with session.put(f"{BASE_URL}/api/config/memory", json=payload) as resp:
            print(f"PUT /api/config/memory -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {data}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_put_optimizer():
    async with aiohttp.ClientSession() as session:
        payload = {"complexity_threshold": 0.7, "scoring_weights_json": "{\"accuracy\": 0.5, \"cost\": 0.3, \"speed\": 0.2}"}
        async with session.put(f"{BASE_URL}/api/config/optimizer", json=payload) as resp:
            print(f"PUT /api/config/optimizer -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {data}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_put_tool():
    async with aiohttp.ClientSession() as session:
        payload = {"enabled": False, "timeout_seconds": 45}
        async with session.put(f"{BASE_URL}/api/config/tools/write_file", json=payload) as resp:
            print(f"PUT /api/config/tools/write_file -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {data}")
            else:
                print(f"  Error: {await resp.text()}")

async def test_mcp_servers():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/config/mcp_servers") as resp:
            print(f"GET /api/config/mcp_servers -> {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Response: {json.dumps(data, indent=2)}")
            else:
                print(f"  Error: {await resp.text()}")

async def main():
    print("Testing DevPlane config endpoints...")
    # Note: endpoints require authentication; we may get 401.
    # We'll just check if they respond (including 401).
    await test_get_roles()
    await test_get_memory()
    await test_get_optimizer()
    await test_get_tools()
    # PUT endpoints will also require auth; we'll still attempt.
    await test_put_memory()
    await test_put_optimizer()
    await test_put_tool()
    # MCP servers endpoint not implemented (we didn't add GET).
    # We'll skip.
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(main())
