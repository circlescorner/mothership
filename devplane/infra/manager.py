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
from devplane.secrets_mgr import get_vault

logger = logging.getLogger("devplane.infra.manager")

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
            return {"error": "DIGITALOCEAN_TOKEN not configured", "code": "NOT_CONFIGURED"}

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
            
            # Check for error responses
            if resp.status_code >= 400:
                error_data = resp.json() if resp.text else {}
                return {
                    "error": error_data.get("message", f"API error {resp.status_code}"),
                    "code": error_data.get("id", f"HTTP_{resp.status_code}"),
                    "status_code": resp.status_code
                }
            
            return resp.json()
        except httpx.TimeoutException:
            logger.error(f"DO API timeout: {endpoint}")
            return {"error": "Request timed out", "code": "TIMEOUT"}
        except httpx.ConnectError as e:
            logger.error(f"DO API connection error: {e}")
            return {"error": "Failed to connect to DigitalOcean API", "code": "CONNECTION_ERROR"}
        except Exception as e:
            logger.error(f"DO API error: {e}")
            return {"error": str(e), "code": "UNKNOWN_ERROR"}

    # ─── Droplet Operations ───────────────────────────────────────────────

    async def list_droplets(self) -> list[dict]:
        """List all DevPlane-managed droplets."""
        result = await self._api("GET", "/droplets?tag_name=devplane")
        
        # Handle API errors
        if "error" in result:
            logger.error(f"Failed to list droplets: {result.get('error')}")
            # Return cached data from DB as fallback
            db = await get_db()
            try:
                rows = await db.execute("SELECT * FROM droplets WHERE status NOT IN ('destroyed', 'error') ORDER BY created_at DESC")
                return [dict(r) for r in await rows.fetchall()]
            finally:
                await db.close()
        
        droplets = result.get("droplets", [])

        # Also sync with local DB
        db = await get_db()
        try:
            for d in droplets:
                await db.execute("""
                    INSERT INTO droplets (droplet_id, name, size, image, region, status, droplet_type, cost_per_hour, tags, ttl_minutes, expires_at, public_ip, vpc_ip)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(droplet_id) DO UPDATE SET
                        name = excluded.name,
                        size = excluded.size,
                        image = excluded.image,
                        region = excluded.region,
                        status = excluded.status,
                        public_ip = excluded.public_ip,
                        vpc_ip = excluded.vpc_ip,
                        tags = excluded.tags,
                        cost_per_hour = excluded.cost_per_hour
                """, (
                    d["id"],
                    d["name"],
                    d["size"]["slug"],
                    d["image"]["slug"],
                    d["region"]["slug"],
                    d["status"],
                    "worker" if "worker" in d.get("tags", []) else "kasm" if "kasm" in d.get("tags", []) else "gpu" if "gpu" in d.get("tags", []) else "deploy",
                    DROPLET_SIZES.get(d["size"]["slug"], {}).get("price_hourly", 0),
                    json.dumps(d.get("tags", [])),
                    0,
                    None,
                    d["networks"]["v4"][0]["ip_address"] if d.get("networks", {}).get("v4") else None,
                    d["networks"]["v4"][-1]["ip_address"] if len(d.get("networks", {}).get("v4", [])) > 1 else None,
                ))
            await db.commit()
        finally:
            await db.close()

        return droplets

    async def get_droplet(self, droplet_id: int) -> dict:
        """Get a specific droplet by ID."""
        result = await self._api("GET", f"/droplets/{droplet_id}")
        
        if "error" in result:
            return result
            
        droplet = result.get("droplet", {})
        if droplet:
            return {
                "droplet_id": droplet["id"],
                "name": droplet["name"],
                "size": droplet["size"]["slug"],
                "region": droplet["region"]["slug"],
                "status": droplet["status"],
                "public_ip": droplet["networks"]["v4"][0]["ip_address"] if droplet.get("networks", {}).get("v4") else None,
                "private_ip": droplet["networks"]["v4"][-1]["ip_address"] if len(droplet.get("networks", {}).get("v4", [])) > 1 else None,
                "created_at": droplet.get("created_at"),
                "tags": droplet.get("tags", []),
            }
        return {"error": "Droplet not found", "code": "NOT_FOUND"}

    async def create_droplet(self, name: str, size: str = "s-2vcpu-4gb",
                              image: str = "ubuntu-22-04-x64",
                              droplet_type: str = "worker",
                              ttl_minutes: int = 0,
                              user_data: str = "") -> dict:
        """Create a new droplet."""
        # Validate size against catalog
        if size not in DROPLET_SIZES:
            available_sizes = list(DROPLET_SIZES.keys())
            return {
                "error": f"Invalid size '{size}'. Available sizes: {available_sizes}",
                "code": "INVALID_SIZE"
            }

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
        
        # Check for API errors
        if "error" in result:
            logger.error(f"Failed to create droplet: {result.get('error')}")
            return result

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
                    INSERT INTO droplets (droplet_id, name, size, image, region, status, droplet_type, cost_per_hour, ttl_minutes, expires_at, tags, public_ip, vpc_ip)
                    VALUES (?, ?, ?, ?, ?, 'creating', ?, ?, ?, ?, ?, NULL, NULL)
                """, (
                    droplet["id"], name, size, image, self.region, droplet_type,
                    size_info.get("price_hourly", 0), ttl_minutes, expires,
                    json.dumps(["devplane", droplet_type])
                ))
                await db.commit()
            finally:
                await db.close()

            logger.info(f"Created droplet: {name} ({size}) — ID {droplet['id']}")
            
            # Return success with droplet details
            return {
                "status": "created",
                "droplet_id": droplet["id"],
                "name": name,
                "size": size,
                "region": self.region,
                "type": droplet_type,
                "ip": droplet.get("networks", {}).get("v4", [{}])[0].get("ip_address") if droplet.get("networks") else None,
            }

        return result

    async def restore_from_snapshot(self, snapshot_id: int, name: str, size: str = "s-2vcpu-4gb") -> dict:
        """Create a new droplet exact copy from an image snapshot."""
        if size not in DROPLET_SIZES:
            return {"error": f"Invalid size '{size}'", "code": "INVALID_SIZE"}
            
        config = {
            "name": name,
            "region": self.region,
            "size": size,
            "image": snapshot_id,
            "tags": ["devplane", "restored"],
        }
        
        if self.vpc_id:
            config["vpc_uuid"] = self.vpc_id
        if self.ssh_key_id:
            config["ssh_keys"] = [int(self.ssh_key_id)]
            
        result = await self._api("POST", "/droplets", config)
        if "error" in result:
            return result
            
        droplet = result.get("droplet", {})
        if droplet.get("id"):
            db = await get_db()
            try:
                await db.execute("""
                    INSERT INTO droplets (droplet_id, name, size, image, region, status, droplet_type, cost_per_hour, tags)
                    VALUES (?, ?, ?, ?, ?, 'creating', 'restored', ?, ?)
                """, (
                    droplet["id"], name, size, str(snapshot_id), self.region,
                    DROPLET_SIZES[size]["price_hourly"], json.dumps(["devplane", "restored"])
                ))
                await db.commit()
            finally:
                await db.close()
                
            return {
                "status": "restoring",
                "droplet_id": droplet["id"],
                "name": name
            }
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

    # ─── Snapshot Operations ──────────────────────────────────────────────

    async def snapshot_droplet(self, droplet_id: int, snapshot_name: str) -> dict:
        """Power off and take a snapshot of a droplet."""
        # 1. Power off
        power_off_req = {
            "type": "power_off"
        }
        await self._api("POST", f"/droplets/{droplet_id}/actions", power_off_req)
        
        # In a real app we'd poll for power-off completion, but often the DO API 
        # queues the snapshot action automatically after power off.
        
        # 2. Snapshot
        snapshot_req = {
            "type": "snapshot",
            "name": snapshot_name
        }
        result = await self._api("POST", f"/droplets/{droplet_id}/actions", snapshot_req)
        
        if "error" not in result:
            logger.info(f"Initiated snapshot '{snapshot_name}' for droplet {droplet_id}")
            return {"status": "snapshotting", "action": result.get("action", {})}
        return result

    async def get_snapshots(self) -> list[dict]:
        """List all available DevPlane snapshots."""
        result = await self._api("GET", "/snapshots?resource_type=droplet")
        if "error" in result:
            return result
            
        # Filter for our snapshots (could check tags or name prefix)
        snapshots = result.get("snapshots", [])
        return [s for s in snapshots if s["name"].startswith("devplane-")]

    async def create_worker(self, ttl_minutes: int = 30,
                             size: str = "s-2vcpu-4gb") -> dict:
        name = f"devplane-worker-{secrets.token_hex(4)}"
        
        # 1. Generate dynamic secret via Vault
        vault = get_vault()
        secret_data = await vault.generate_ephemeral_secret(name, ttl_minutes)
        dynamic_secret = secret_data["secret_value"]
        expires_at = secret_data["expires_at"]

        user_data = f"""#!/bin/bash
set -e

export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

# Timeout Safe Aliases
alias curl='curl --max-time 30 --connect-timeout 10'
alias wget='wget --timeout=30 --tries=3'

# System update
timeout 300 apt-get update
timeout 600 apt-get upgrade -y

# Create directories
mkdir -p /etc/devplane
mkdir -p /srv/devplane/worker
mkdir -p /var/log/devplane

# Inject dynamic secret safely
echo "{dynamic_secret}" > /etc/devplane/secret
echo "{expires_at}" > /etc/devplane/secret_expires
echo "{name}" > /etc/devplane/worker_id
chmod 600 /etc/devplane/secret /etc/devplane/secret_expires

# Create secret expiration checker script
cat > /usr/local/bin/check-secret-expiration.sh << 'SCRIPT'
#!/bin/bash
SECRET_FILE="/etc/devplane/secret"
EXPIRES_FILE="/etc/devplane/secret_expires"
LOG_FILE="/var/log/devplane-secrets.log"

log() {{
    echo "\\$(date -Iseconds) - \\$1" >> "\\$LOG_FILE"
}}

if [[ ! -f "\\$SECRET_FILE" ]] || [[ ! -f "\\$EXPIRES_FILE" ]]; then
    exit 0
fi

EXPIRES_AT=\\$(cat "\\$EXPIRES_FILE")
CURRENT_TIME=\\$(date -u +%Y-%m-%dT%H:%M:%S)

if [[ "\\$CURRENT_TIME" > "\\$EXPIRES_AT" ]]; then
    log "ERROR: Secret EXPIRED. Shutting down worker..."
    shred -u "\\$SECRET_FILE" 2>/dev/null || rm -f "\\$SECRET_FILE"
    shutdown -h now
fi
SCRIPT
chmod +x /usr/local/bin/check-secret-expiration.sh

# Setup cron for secret expiration checking
echo "*/2 * * * * root /usr/local/bin/check-secret-expiration.sh" > /etc/cron.d/devplane-secrets

hostnamectl set-hostname {name}
echo "DevPlane worker {name} ready with dynamic secret"
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
