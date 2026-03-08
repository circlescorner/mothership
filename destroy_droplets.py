import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def run():
    token = os.getenv("DIGITALOCEAN_TOKEN")
    if not token:
        print("No DO token")
        return
    
    async with httpx.AsyncClient() as client:
        # Get all droplets
        resp = await client.get(
            "https://api.digitalocean.com/v2/droplets",
            headers={"Authorization": f"Bearer {token}"}
        )
        droplets = resp.json().get("droplets", [])
        
        # We want to keep the one we just deployed: `devplane-vps`
        to_delete = [d for d in droplets if d["name"] != "devplane-vps"]
        
        for d in to_delete:
            print(f"Deleting droplet {d['name']} (ID: {d['id']})...")
            del_resp = await client.delete(
                f"https://api.digitalocean.com/v2/droplets/{d['id']}",
                headers={"Authorization": f"Bearer {token}"}
            )
            print(f"Status: {del_resp.status_code}")

asyncio.run(run())
