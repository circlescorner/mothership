import os
import json
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def run():
    token = os.getenv("DIGITALOCEAN_TOKEN")
    if not token:
        print("No DO token")
        return
    resp = await httpx.AsyncClient().get(
        "https://api.digitalocean.com/v2/droplets",
        headers={"Authorization": f"Bearer {token}"}
    )
    droplets = resp.json().get("droplets", [])
    res = [
        {
            "id": d["id"],
            "name": d["name"],
            "tags": d.get("tags", []),
            "status": d["status"],
            "ip": d.get("networks", {}).get("v4", [{}])[0].get("ip_address") if d.get("networks", {}).get("v4") else None
        }
        for d in droplets
    ]
    print(json.dumps(res, indent=2))

asyncio.run(run())
