#!/usr/bin/env python3
"""Check that langchain_tools table exists and has seeded rows."""
import asyncio
import sys
sys.path.insert(0, '.')
from devplane.db import get_db

async def check():
    db = await get_db()
    try:
        rows = await db.execute("SELECT name, description, enabled FROM langchain_tools")
        tools = await rows.fetchall()
        print(f"Found {len(tools)} langchain_tools:")
        for row in tools:
            print(f"  - {row['name']}: {row['description']} (enabled={row['enabled']})")
        if len(tools) == 0:
            print("ERROR: No tools seeded!")
            sys.exit(1)
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(check())