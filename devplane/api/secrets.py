from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from devplane.db import get_db
from devplane.secrets_mgr import get_vault
import logging

logger = logging.getLogger("devplane.api.secrets")
router = APIRouter(prefix="/api/secrets", tags=["secrets"])

# Models
class SecretCreate(BaseModel):
    name: str
    value: str
    ttl_minutes: int = 0

class SecretResponse(BaseModel):
    id: str
    name: str
    expires_at: Optional[str]

    
@router.get("/", response_model=List[SecretResponse])
async def list_secrets():
    """List all active secrets in the DevPlane Vault (Metadata only)."""
    db = await get_db()
    try:
        # Also clean expired secrets during list query
        await get_vault().clean_expired_secrets()
        
        rows = await db.execute("SELECT id, name, expires_at FROM devplane_secrets ORDER BY created_at DESC")
        secrets = await rows.fetchall()
        return [dict(s) for s in secrets]
    finally:
        await db.close()

@router.post("/", response_model=SecretResponse)
async def create_secret(req: SecretCreate):
    """Store a new encrypted secret."""
    vault = get_vault()
    try:
        secret_id = await vault.store_secret(req.name, req.value, req.ttl_minutes)
        
        db = await get_db()
        row = await db.execute("SELECT id, name, expires_at FROM devplane_secrets WHERE id = ?", (secret_id,))
        record = await row.fetchone()
        await db.close()
        return dict(record)
    except Exception as e:
        logger.error(f"Failed to create secret: {e}")
        raise HTTPException(status_code=500, detail="Failed to store secret securely.")

@router.delete("/{secret_id}")
async def delete_secret(secret_id: str):
    """Revoke and delete a secret permanently."""
    success = await get_vault().revoke_secret(secret_id)
    if not success:
        raise HTTPException(status_code=404, detail="Secret not found or already deleted.")
    return {"status": "success", "message": "Secret revoked"}
