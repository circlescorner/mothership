import os
import sys
from dotenv import load_dotenv
import asyncio
import httpx
import json

load_dotenv()

async def list_droplets():
    token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not token:
        print("No DIGITALOCEAN_TOKEN found.")
        return
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.digitalocean.com/v2/droplets",
            headers={"Authorization": f"Bearer {token}"}
        )
        with open("tmp_drops.json", "w") as f:
            json.dump(resp.json(), f, indent=2)
        print("Wrote to tmp_drops.json")

if __name__ == "__main__":
    asyncio.run(list_droplets())
