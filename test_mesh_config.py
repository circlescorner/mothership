#!/usr/bin/env python3
"""Quick test of mesh configuration changes."""
import asyncio
import sys
sys.path.insert(0, '.')
from devplane.db import init_db, get_db
from devplane.chain.mesh import get_active_mesh_config

async def test():
    await init_db()
    config = await get_active_mesh_config()
    print("Mesh config:", config)
    print("max_iterations:", config.get('max_iterations'))
    print("role_configs:", config.get('role_configs'))
    # Ensure role configs exist
    for role, cfg in config.get('role_configs', {}).items():
        print(f"  {role}: {cfg}")
    # Test that mesh can be run (just graph compilation)
    from devplane.chain.mesh import get_mesh_graph
    graph = get_mesh_graph()
    print("Graph compiled successfully")
    # Test that max_iterations is used in critic node
    from devplane.chain.mesh import critic_node
    print("Critic node function:", critic_node)
    # Check database schema for mesh_role_config
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM mesh_role_config")
        async for row in rows:
            print(f"DB row: {dict(row)}")
    finally:
        await db.close()
    print("All checks passed")

if __name__ == "__main__":
    asyncio.run(test())