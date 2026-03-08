import os
import asyncio
from dotenv import load_dotenv

import sys
sys.path.insert(0, ".")
from devplane.infra.cloudflare import CloudflareManager

import builtins
builtins.input = lambda _: "yes"

load_dotenv()

async def get_token():
    cf = CloudflareManager()
    if not cf.configured:
        print("CF manager not config")
        return
        
    tunnels = await cf.list_tunnels()
    valid_tunnels = [t for t in tunnels if "error" not in t]
    existing = next((t for t in valid_tunnels if t.get("name") == "devplane-vps-tunnel"), None)
    
    if not existing:
         print("creating tunnel")
         existing = await cf.create_tunnel("devplane-vps-tunnel")
         
    tunnel_id = existing.get("id")
    result = await cf.get_tunnel_token(tunnel_id)
    token = result.get("token")
    if token:
         print(f"Token: {token}")
         import re
         with open(".env", "r", encoding='utf-8') as f:
             config = f.read()
         config = re.sub(r'#?\s*TUNNEL_TOKEN=.*', f'TUNNEL_TOKEN={token}', config)
         with open(".env", "w", encoding='utf-8') as f:
             f.write(config)
         print("Wrote token to .env")
    else:
         print("No token")
         
    await cf.close()

if __name__ == "__main__":
    asyncio.run(get_token())
