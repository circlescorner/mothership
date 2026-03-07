"""API router — Provider management endpoints."""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from devplane.providers import (
    get_all_providers, get_provider, update_provider,
    create_provider, delete_provider, test_provider_connection,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderUpdate(BaseModel):
    api_key: Optional[str] = None
    enabled: Optional[bool] = None
    monthly_budget: Optional[float] = None
    display_name: Optional[str] = None


class ProviderCreate(BaseModel):
    name: str
    display_name: str
    api_key: str = ""
    monthly_budget: float = 0.0


@router.get("")
async def list_providers():
    providers = await get_all_providers()
    # Mask API keys for frontend display
    for p in providers:
        if p.get("api_key"):
            key = p["api_key"]
            p["api_key_masked"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
            p["has_key"] = True
        else:
            p["api_key_masked"] = ""
            p["has_key"] = False
        # Don't send raw key to frontend
        del p["api_key"]
    return providers


@router.get("/{provider_id}")
async def get_single_provider(provider_id: int):
    p = await get_provider(provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    if p.get("api_key"):
        key = p["api_key"]
        p["api_key_masked"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        p["has_key"] = True
    else:
        p["api_key_masked"] = ""
        p["has_key"] = False
    del p["api_key"]
    return p


@router.put("/{provider_id}")
async def update_single_provider(provider_id: int, data: ProviderUpdate):
    kwargs = {k: v for k, v in data.model_dump().items() if v is not None}
    success = await update_provider(provider_id, **kwargs)
    if not success:
        raise HTTPException(400, "No valid fields to update")
    return {"status": "updated"}


@router.post("")
async def create_new_provider(data: ProviderCreate):
    pid = await create_provider(data.name, data.display_name, data.api_key, data.monthly_budget)
    return {"id": pid, "status": "created"}


@router.delete("/{provider_id}")
async def remove_provider(provider_id: int):
    await delete_provider(provider_id)
    return {"status": "deleted"}


@router.post("/{provider_id}/test")
async def test_connection(provider_id: int):
    result = await test_provider_connection(provider_id)
    return result
