"""Infrastructure Manager — DigitalOcean droplet lifecycle management.

Spin up/down VMs, GPU droplets, and ephemeral workers from the dashboard.
Adapted from PythonProject4's deploy-infrastructure.py.
"""

import os
import json
import logging
import secrets
import httpx
from datetime import datetime, timedelta
from typing import Optional
from devplane.db import get_db

logger = logging.getLogger("devplane.infra")

# ─── Droplet Size Catalog ────────────────────────────────────────────────────

DROPLET_SIZES = {
    # Standard droplets
    "s-1vcpu-1gb": {"vcpus": 1, "memory": 1024, "disk": 25, "price_hourly": 0.00893, "price_monthly": 6.0, "label": "Basic 1vCPU 1GB"},
    "s-1vcpu-2gb": {"vcpus": 1, "memory": 2048, "disk": 50, "price_hourly": 0.01786, "price_monthly": 12.0, "label": "Basic 1vCPU 2GB"},
    "s-2vcpu-4gb": {"vcpus": 2, "memory": 4096, "disk": 80, "price_hourly": 0.03571, "price_monthly": 24.0, "label": "Basic 2vCPU 4GB"},
    "s-4vcpu-8gb": {"vcpus": 4, "memory": 8192, "disk": 160, "price_hourly": 0.07143, "price_monthly": 48.0, "label": "Basic 4vCPU 8GB"},
    "s-8vcpu-16gb": {"vcpus": 8, "memory": 16384, "disk": 320, "price_hourly": 0.14286, "price_monthly": 96.0, "label": "Basic 8vCPU 16GB"},
    # GPU droplets
    "gpu-h100x1-80gb": {"vcpus": 16, "memory": 65536, "disk": 500, "price_hourly": 2.50, "price_monthly": 1825.0, "label": "GPU H100 x1"},
    "gpu-h100x8-640gb": {"vcpus": 128, "memory": 524288, "disk": 4000, "price_hourly": 20.0, "price_monthly": 14600.0, "label": "GPU H100 x8"},
}

WORKSPACE_TEMPLATES = {
    "antigravity": {
        "label": "Antigravity Pro",
        "description": "Chrome + Antigravity Pro, VS Code, full Ubuntu desktop",
        "image": "kasmweb/chrome:1.15.0",
        "size": "s-2vcpu-4gb",
    },
    "kilo-code": {
        "label": "Kilo Code",
        "description": "VS Code + Kilo extensions, terminal, SSH, Docker",
        "image": "kasmweb/vs-code:1.15.0",
        "size": "s-4vcpu-8gb",
    },
    "dev-full": {
        "label": "Full Dev Desktop",
        "description": "Ubuntu Desktop, Docker, Python, Node.js, full tools",
        "image": "kasmweb/ubuntu-jammy-desktop:1.15.0",
        "size": "s-4vcpu-8gb",
    },
    "pycharm-kilo": {
        "label": "PyCharm Pro & Kilo Code",
        "description": "Ubuntu Full Desktop + PyCharm Pro pre-installed w/ Kilo",
        "image": "kasmweb/ubuntu-jammy-desktop:1.15.0",
        "size": "s-4vcpu-8gb",
    },
}


class InfraManager:
    """DigitalOcean infrastructure manager."""

    def __init__(self):
        self.token = os.environ.get("DIGITALOCEAN_TOKEN", "")
        self.region = os.environ.get("DIGITALOCEAN_REGION", "nyc1")
        self.vpc_id = os.environ.get("DIGITALOCEAN_VPC_ID", "")
        self.ssh_key_id = os.environ.get("DIGITALOCEAN_SSH_KEY_ID", "")
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def _api(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make DigitalOcean API request."""
        if not self.token:
            return {"error": "DIGITALOCEAN_TOKEN not configured"}

        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.digitalocean.com/v2",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )

        try:
            if method == "GET":
                resp = await self._client.get(endpoint)
            elif method == "POST":
                resp = await self._client.post(endpoint, json=data or {})
            elif method == "DELETE":
                resp = await self._client.delete(endpoint)
            else:
                resp = await self._client.request(method, endpoint, json=data)

            if resp.status_code == 204:
                return {"status": "ok"}
            return resp.json()
        except Exception as e:
            logger.error(f"DO API error: {e}")
            return {"error": str(e)}

    # ─── Droplet Operations ───────────────────────────────────────────────

    async def list_droplets(self) -> list[dict]:
        """List all DevPlane-managed droplets."""
        result = await self._api("GET", "/droplets?tag_name=devplane")
        droplets = result.get("droplets", [])

        # Also sync with local DB
        db = await get_db()
        try:
            for d in droplets:
                await db.execute("""
                    INSERT OR REPLACE INTO droplets (droplet_id, name, size, region, status, public_ip, vpc_ip)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    d["id"], d["name"], d["size"]["slug"], d["region"]["slug"],
                    d["status"],
                    d["networks"]["v4"][0]["ip_address"] if d.get("networks", {}).get("v4") else None,
                    d["networks"]["v4"][-1]["ip_address"] if len(d.get("networks", {}).get("v4", [])) > 1 else None,
                ))
            await db.commit()
        finally:
            await db.close()

        return droplets

    async def create_droplet(self, name: str, size: str = "s-2vcpu-4gb",
                              image: str = "ubuntu-22-04-x64",
                              droplet_type: str = "worker",
                              ttl_minutes: int = 0,
                              user_data: str = "") -> dict:
        """Create a new droplet."""
        if not user_data:
            user_data = self._generate_user_data(name, droplet_type, ttl_minutes)

        config = {
            "name": name,
            "region": self.region,
            "size": size,
            "image": image,
            "tags": ["devplane", droplet_type],
            "user_data": user_data,
        }

        if self.vpc_id:
            config["vpc_uuid"] = self.vpc_id
        if self.ssh_key_id:
            config["ssh_keys"] = [int(self.ssh_key_id)]

        result = await self._api("POST", "/droplets", config)
        droplet = result.get("droplet", {})

        if droplet.get("id"):
            # Track in DB
            size_info = DROPLET_SIZES.get(size, {})
            expires = None
            if ttl_minutes > 0:
                expires = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat()

            db = await get_db()
            try:
                await db.execute("""
                    INSERT INTO droplets (droplet_id, name, size, region, status, droplet_type, cost_per_hour, ttl_minutes, expires_at, tags)
                    VALUES (?, ?, ?, ?, 'creating', ?, ?, ?, ?, ?)
                """, (
                    droplet["id"], name, size, self.region, droplet_type,
                    size_info.get("price_hourly", 0), ttl_minutes, expires,
                    json.dumps(["devplane", droplet_type])
                ))
                await db.commit()
            finally:
                await db.close()

            logger.info(f"Created droplet: {name} ({size}) — ID {droplet['id']}")

        return result

    async def destroy_droplet(self, droplet_id: int) -> dict:
        """Destroy a droplet and track costs."""
        result = await self._api("DELETE", f"/droplets/{droplet_id}")

        db = await get_db()
        try:
            await db.execute(
                "UPDATE droplets SET status = 'destroyed' WHERE droplet_id = ?",
                (droplet_id,)
            )
            await db.commit()
        finally:
            await db.close()

        logger.info(f"Destroyed droplet: {droplet_id}")
        return result

    async def create_worker(self, ttl_minutes: int = 30,
                             size: str = "s-2vcpu-4gb") -> dict:
        """Create an ephemeral worker with auto-expiry."""
        worker_id = f"w{secrets.token_hex(4)}"
        name = f"devplane-worker-{worker_id}"

        dynamic_secret = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat()

        user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker root
systemctl enable docker

mkdir -p /etc/devplane /srv/devplane/worker
echo "{dynamic_secret}" > /etc/devplane/secret
echo "{expires}" > /etc/devplane/secret_expires
echo "{worker_id}" > /etc/devplane/worker_id
chmod 600 /etc/devplane/secret

# Auto-destroy cron
echo "*/5 * * * * root python3 -c \\"
import datetime
exp = datetime.datetime.fromisoformat(open('/etc/devplane/secret_expires').read().strip())
if datetime.datetime.utcnow() > exp:
    import subprocess
    subprocess.run(['shutdown', '-h', 'now'])
\\"" > /etc/cron.d/devplane-expire

hostnamectl set-hostname {name}
echo "Worker {worker_id} ready — expires at {expires}"
"""

        return await self.create_droplet(name, size, "ubuntu-22-04-x64", "worker", ttl_minutes, user_data)

    async def create_gpu_droplet(self, gpu_size: str = "gpu-h100x1-80gb",
                                  name: str = "") -> dict:
        """Create a GPU droplet for local inference."""
        if not name:
            name = f"devplane-gpu-{secrets.token_hex(3)}"

        user_data = """#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker root

# Install NVIDIA drivers + CUDA toolkit
apt-get install -y nvidia-driver-535 nvidia-cuda-toolkit

# Pull vLLM for fast inference
docker pull vllm/vllm-openai:latest

mkdir -p /srv/devplane/gpu /srv/llm/models
hostnamectl set-hostname """ + name + """
echo "GPU droplet ready"
"""

        return await self.create_droplet(name, gpu_size, "gpu-h100x1-80gb-ubuntu-22-04", "gpu", 0, user_data)

    async def get_infra_summary(self) -> dict:
        """Get infrastructure cost summary."""
        db = await get_db()
        try:
            # Active droplets
            row = await db.execute("SELECT COUNT(*) as c FROM droplets WHERE status NOT IN ('destroyed', 'error')")
            active = (await row.fetchone())["c"]

            # Estimate monthly cost
            row = await db.execute("SELECT COALESCE(SUM(cost_per_hour), 0) as total FROM droplets WHERE status NOT IN ('destroyed', 'error')")
            hourly = (await row.fetchone())["total"]

            # Active workspaces
            row = await db.execute("SELECT COUNT(*) as c FROM workspaces WHERE status = 'running'")
            ws_active = (await row.fetchone())["c"]

            return {
                "configured": self.configured,
                "active_droplets": active,
                "active_workspaces": ws_active,
                "cost_per_hour": round(hourly, 4),
                "cost_per_month": round(hourly * 730, 2),
                "region": self.region,
            }
        finally:
            await db.close()

    def get_size_catalog(self) -> list[dict]:
        """Return available droplet sizes."""
        return [{"slug": k, **v} for k, v in DROPLET_SIZES.items()]

    def get_workspace_templates(self) -> list[dict]:
        """Return available workspace templates."""
        return [{"id": k, **v} for k, v in WORKSPACE_TEMPLATES.items()]

    def _generate_user_data(self, name: str, droplet_type: str, ttl: int) -> str:
        return f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker root
systemctl enable docker
mkdir -p /srv/devplane
hostnamectl set-hostname {name}
echo "{droplet_type} droplet ready"
"""


# Singleton
_manager: Optional[InfraManager] = None

def get_infra_manager() -> InfraManager:
    global _manager
    if _manager is None:
        _manager = InfraManager()
    return _manager
