import os
import asyncio
from dotenv import load_dotenv

import sys
sys.path.insert(0, ".")
from devplane.infra.cloudflare import CloudflareManager

import builtins
builtins.input = lambda _: "yes"

load_dotenv()

async def check_dns():
    cf = CloudflareManager()
    if not cf.configured:
        print("CF manager not config")
        return
        
    records = await cf.list_dns_records()
    print("DNS Records:")
    for r in records:
        print(f"{r.get('name')} -> {r.get('type')} {r.get('content')} (Proxied: {r.get('proxied')})")
         
    await cf.close()

if __name__ == "__main__":
    asyncio.run(check_dns())
