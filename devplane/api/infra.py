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


@router.post("/droplets")
async def create_new_droplet(data: CreateDropletRequest):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN.")
    if not data.name:
        import secrets
        data.name = f"devplane-{data.droplet_type}-{secrets.token_hex(3)}"
    return await mgr.create_droplet(data.name, data.size, data.image, data.droplet_type, data.ttl_minutes)


@router.delete("/droplets/{droplet_id}")
async def remove_droplet(droplet_id: int):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured.")
    return await mgr.destroy_droplet(droplet_id)


# ─── Workers ─────────────────────────────────────────────────────────────────

@router.post("/workers")
async def create_worker(data: CreateWorkerRequest):
    mgr = get_infra_manager()
    if not mgr.configured:
        raise HTTPException(400, "DigitalOcean not configured.")
    return await mgr.create_worker(data.ttl_minutes, data.size)


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
