#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '.')
from devplane.db import get_db

async def seed():
    db = await get_db()
    try:
        mesh_config_id = 1
        role_configs = [
            ('architect', 'openrouter/anthropic/claude-sonnet-4', 3, 60),
            ('worker', 'deepseek/deepseek-chat', 3, 60),
            ('critic', 'openrouter/anthropic/claude-sonnet-4', 3, 60),
        ]
        for role_name, model_slug, iteration_limit, timeout_seconds in role_configs:
            await db.execute("""
                INSERT OR REPLACE INTO mesh_role_config (mesh_config_id, role_name, model_slug, iteration_limit, timeout_seconds)
                VALUES (?, ?, ?, ?, ?)
            """, (mesh_config_id, role_name, model_slug, iteration_limit, timeout_seconds))
        await db.commit()
        print("Inserted role configs")
        # Verify
        rows = await db.execute("SELECT * FROM mesh_role_config")
        async for row in rows:
            print(dict(row))
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(seed())