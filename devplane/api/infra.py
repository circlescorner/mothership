"""API router — Infrastructure management endpoints."""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from devplane.infra.manager import get_infra_manager
from devplane.infra.kasm import create_workspace, list_workspaces, destroy_workspace

router = APIRouter(prefix="/api/infra", tags=["infrastructure"])


class CreateDropletRequest(BaseModel):
    name: str = ""
    size: str = "s-2vcpu-4gb"
    image: str = "ubuntu-22-04-x64"
    droplet_type: str = "worker"
    ttl_minutes: int = 0


class CreateWorkerRequest(BaseModel):
    ttl_minutes: int = 30
    size: str = "s-2vcpu-4gb"


class CreateGPURequest(BaseModel):
    gpu_size: str = "gpu-h100x1-80gb"
    name: str = ""


class CreateWorkspaceRequest(BaseModel):
    template: str = "dev-full"
    user_email: str = ""


# ─── Infrastructure Status ───────────────────────────────────────────────────

@router.get("/status")
async def infra_status():
    mgr = get_infra_manager()
    return await mgr.get_infra_summary()


@router.get("/sizes")
async def size_catalog():
    mgr = get_infra_manager()
    return mgr.get_size_catalog()


@router.get("/templates")
async def workspace_templates():
    mgr = get_infra_manager()
    return mgr.get_workspace_templates()


# ─── Droplet Management ──────────────────────────────────────────────────────

@router.get("/droplets")
async def get_droplets():
    mgr = get_infra_manager()
    if not mgr.configured:
        from devplane.db import get_db
        db = await get_db()
        try:
            rows = await db.execute("SELECT * FROM droplets ORDER BY created_at DESC")
            return [dict(r) for r in await rows.fetchall()]
        finally:
            await db.close()
    return await mgr.list_droplets()


@router.get("/droplets/{droplet_id}")
async def get_droplet(droplet_id: int):
    """Get a specific droplet by ID."""
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN.")
    result = await mgr.get_droplet(droplet_id)
    if "error" in result:
        raise HTTPException(404, result.get("error", "Droplet not found"))
    return result


@router.post("/droplets")
async def create_new_droplet(data: CreateDropletRequest):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN.")
    if not data.name:
        import secrets
        data.name = f"devplane-{data.droplet_type}-{secrets.token_hex(3)}"
    result = await mgr.create_droplet(data.name, data.size, data.image, data.droplet_type, data.ttl_minutes)
    if "error" in result:
        raise HTTPException(400, result.get("error", "Failed to create droplet"))
    return result


@router.delete("/droplets/{droplet_id}")
async def remove_droplet(droplet_id: int):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured.")
    result = await mgr.destroy_droplet(droplet_id)
    if "error" in result:
        raise HTTPException(400, result.get("error", "Failed to destroy droplet"))
    return result


# ─── Workers ─────────────────────────────────────────────────────────────────

@router.post("/workers")
async def create_worker(data: CreateWorkerRequest):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured.")
    result = await mgr.create_worker(data.ttl_minutes, data.size)
    if "error" in result:
        raise HTTPException(400, result.get("error", "Failed to create worker"))
    return result


# ─── Deployment Automation ─────────────────────────────────────────────────

class DeployRequest(BaseModel):
    droplet_name: str = ""
    size: str = "s-2vcpu-4gb"
    git_repo: str = ""
    branch: str = "main"
    startup_script: str = ""
    ttl_minutes: int = 0


@router.post("/deploy")
async def deploy_to_droplet(data: DeployRequest):
    """Deploy application to a new droplet with optional startup script."""
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN.")
    
    import secrets
    droplet_name = data.droplet_name or f"deploy-{secrets.token_hex(4)}"
    
    # Build user_data script
    user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker root
systemctl enable docker

mkdir -p /srv/devplane
hostnamectl set-hostname {droplet_name}
"""
    
    # Add git clone if repo specified
    if data.git_repo:
        user_data += f"""
# Install git and clone repository
apt-get install -y git
cd /srv/devplane
git clone {data.git_repo} .
git checkout {data.branch}
"""
    
    # Add custom startup script
    if data.startup_script:
        user_data += f"""
# Custom startup script
cat > /srv/devplane/startup.sh << 'EOF'
{data.startup_script}
EOF
chmod +x /srv/devplane/startup.sh
"""
    
    user_data += f"""
echo "Deployment droplet {droplet_name} ready"
"""
    
    result = await mgr.create_droplet(
        name=droplet_name,
        size=data.size,
        droplet_type="deploy",
        ttl_minutes=data.ttl_minutes,
        user_data=user_data
    )
    
    if "error" in result:
        raise HTTPException(400, result.get("error", "Failed to create deployment droplet"))
    
    return {
        "status": "deploying",
        "droplet_name": droplet_name,
        "droplet_id": result.get("droplet_id"),
        "ip": result.get("ip"),
        "message": "Droplet created. Application will be ready in 2-3 minutes."
    }


# ─── GPU Droplets ─────────────────────────────────────────────────────────────

@router.post("/gpu")
async def create_gpu(data: CreateGPURequest):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured.")
    return await mgr.create_gpu_droplet(data.gpu_size, data.name)


# ─── Kasm Workspaces ─────────────────────────────────────────────────────────

@router.get("/workspaces")
async def get_workspaces():
    return await list_workspaces()


@router.post("/workspaces")
async def create_new_workspace(data: CreateWorkspaceRequest):
    return await create_workspace(data.template, data.user_email)


@router.delete("/workspaces/{workspace_id}")
async def remove_workspace(workspace_id: str):
    return await destroy_workspace(workspace_id)


# ─── GPU Compute Arsenal ─────────────────────────────────────────────────────

class GPUDispatchRequest(BaseModel):
    script: str
    provider: str = "auto"


@router.get("/gpu/providers")
async def gpu_providers():
    from devplane.infra.gpu import get_gpu_arsenal
    arsenal = get_gpu_arsenal()
    return {"configured": arsenal.configured, "providers": arsenal.list_providers()}


@router.get("/gpu/cheapest")
async def gpu_cheapest(min_vram_gb: int = 24):
    from devplane.infra.gpu import get_gpu_arsenal
    arsenal = get_gpu_arsenal()
    return await arsenal.find_cheapest_gpu(min_vram_gb)


@router.post("/gpu/dispatch")
async def gpu_dispatch(data: GPUDispatchRequest):
    from devplane.infra.gpu import get_gpu_arsenal
    arsenal = get_gpu_arsenal()
    return await arsenal.dispatch_job(data.script, data.provider)


@router.get("/gpu/jobs")
async def gpu_jobs():
    from devplane.infra.gpu import get_gpu_arsenal
    arsenal = get_gpu_arsenal()
    return await arsenal.list_jobs()


@router.delete("/gpu/{job_id}")
async def gpu_cancel(job_id: str):
    from devplane.infra.gpu import get_gpu_arsenal
    arsenal = get_gpu_arsenal()
    return await arsenal.cancel_job(job_id)


# ─── Cloudflare DNS & Tunnels ────────────────────────────────────────────────

class DNSCreateRequest(BaseModel):
    name: str
    content: str
    record_type: str = "A"
    proxied: bool = True


class AutoExposeRequest(BaseModel):
    ip: str
    subdomain: str


@router.get("/dns")
async def list_dns():
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        return {"error": "Cloudflare not configured", "records": []}
    return await cf.list_dns_records()


@router.post("/dns")
async def create_dns(data: DNSCreateRequest):
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        raise HTTPException(400, "Cloudflare not configured")
    return await cf.create_dns_record(data.name, data.content, data.record_type, data.proxied)


@router.delete("/dns/{record_id}")
async def delete_dns(record_id: str):
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        raise HTTPException(400, "Cloudflare not configured")
    return await cf.delete_dns_record(record_id)


@router.post("/dns/expose")
async def auto_expose(data: AutoExposeRequest):
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        raise HTTPException(400, "Cloudflare not configured")
    return await cf.auto_expose(data.ip, data.subdomain)


@router.get("/tunnels")
async def list_tunnels():
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        return {"error": "Cloudflare not configured", "tunnels": []}
    return await cf.list_tunnels()


@router.post("/tunnels")
async def create_tunnel(data: dict):
    """Create a new Cloudflare Tunnel."""
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        raise HTTPException(400, "Cloudflare not configured")
    name = data.get("name", "devplane-tunnel")
    return await cf.create_tunnel(name)


@router.delete("/tunnels/{tunnel_id}")
async def delete_tunnel(tunnel_id: str):
    """Delete a Cloudflare Tunnel."""
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        raise HTTPException(400, "Cloudflare not configured")
    return await cf.delete_tunnel(tunnel_id)


@router.get("/tunnels/{tunnel_id}/token")
async def get_tunnel_token(tunnel_id: str):
    """Get the token for a tunnel."""
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    if not cf.configured:
        raise HTTPException(400, "Cloudflare not configured")
    return await cf.get_tunnel_token(tunnel_id)


@router.get("/cloudflare/status")
async def cloudflare_status():
    """Get Cloudflare configuration status."""
    from devplane.infra.cloudflare import get_cloudflare_manager
    cf = get_cloudflare_manager()
    zone_info = await cf.get_zone_info() if cf.configured else {"error": "Not configured"}
    return {
        "configured": cf.configured,
        "domain": cf.domain,
        "zone": zone_info,
    }


# ─── Role Registry ───────────────────────────────────────────────────────────

class RolesUpdateRequest(BaseModel):
    role: str
    models: list[str]


@router.get("/roles")
async def get_roles():
    from devplane.roles import get_all_roles
    return get_all_roles()


@router.put("/roles")
async def update_role(data: RolesUpdateRequest):
    from devplane.roles import set_role_models, save_to_db
    set_role_models(data.role, data.models)
    await save_to_db()
    return {"status": "updated", "role": data.role}

