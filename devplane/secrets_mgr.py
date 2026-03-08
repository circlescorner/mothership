"""Secrets Manager (Vault) — Dynamic, expiring credentials.

Provides a secure way to generate, store, and revoke temporary secrets 
(e.g., for ephemeral workers), mimicking HashiCorp Vault functionality.
"""

import os
import secrets
import base64
import logging
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from devplane.db import get_db

logger = logging.getLogger("devplane.secrets_mgr")

class DevPlaneVault:
    def __init__(self):
        # Master encryption key. Read from env, but fail securely if missing
        master_key_b64 = os.environ.get("VAULT_MASTER_KEY")
        if not master_key_b64:
            # Generate a temporary one for the session if not set (not ideal for persistence, 
            # but safe enough for temporary RAM worker setups testing)
            master_key_b64 = base64.urlsafe_b64encode(os.urandom(32)).decode()
            os.environ["VAULT_MASTER_KEY"] = master_key_b64
            logger.warning("VAULT_MASTER_KEY not fully set in .env. Using ephemeral RAM key.")
            
        try:
            self.cipher = Fernet(master_key_b64.encode())
        except Exception as e:
            logger.error("Invalid VAULT_MASTER_KEY. Must be 32 url-safe base64-encoded bytes.")
            self.cipher = Fernet(Fernet.generate_key())

    def _encrypt(self, plaintext: str) -> str:
        return self.cipher.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        return self.cipher.decrypt(ciphertext.encode()).decode()

    async def store_secret(self, name: str, value: str, ttl_minutes: int = 0) -> str:
        """Store a new secret in the DB, securely encrypted."""
        secret_id = f"sct_{secrets.token_hex(8)}"
        encrypted = self._encrypt(value)
        
        expires_at = None
        if ttl_minutes > 0:
            expires_at = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat()
            
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO devplane_secrets (id, name, encrypted_value, expires_at) VALUES (?, ?, ?, ?)",
                (secret_id, name, encrypted, expires_at)
            )
            await db.commit()
            logger.info(f"Stored secret '{name}' (ID: {secret_id})")
            return secret_id
        except Exception as e:
            logger.error(f"Failed to store secret: {e}")
            raise
        finally:
            await db.close()

    async def generate_ephemeral_secret(self, name: str, ttl_minutes: int = 30) -> dict:
        """Generate a random strong string and store it as an expiring secret."""
        # 32 bytes of high-entropy data, URL-safe
        raw_secret = secrets.token_urlsafe(32)
        secret_id = await self.store_secret(name, raw_secret, ttl_minutes)
        
        return {
            "id": secret_id,
            "name": name,
            "secret_value": raw_secret,  # Only returned once!
            "expires_at": (datetime.utcnow() + timedelta(minutes=ttl_minutes)).isoformat()
        }

    async def get_secret(self, secret_id: str) -> dict:
        """Retrieve and decrypt an active secret. Fails if expired."""
        db = await get_db()
        try:
            row = await db.execute("SELECT * FROM devplane_secrets WHERE id = ?", (secret_id,))
            record = await row.fetchone()
            
            if not record:
                return {"error": "Secret not found"}
                
            # Check expiration
            if record["expires_at"]:
                expires_at = datetime.fromisoformat(record["expires_at"])
                if datetime.utcnow() > expires_at:
                    return {"error": "Secret has expired"}
                    
            try:
                decrypted = self._decrypt(record["encrypted_value"])
                return {
                    "id": record["id"],
                    "name": record["name"],
                    "value": decrypted,
                    "expires_at": record["expires_at"]
                }
            except Exception as e:
                logger.error(f"Decryption failed for secret {secret_id}: {e}")
                return {"error": "Decryption failed (Master key changed?)"}
        finally:
            await db.close()

    async def revoke_secret(self, secret_id: str) -> bool:
        """Immediately destroy a secret."""
        db = await get_db()
        try:
            cursor = await db.execute("DELETE FROM devplane_secrets WHERE id = ?", (secret_id,))
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()

    async def clean_expired_secrets(self) -> int:
        """Run periodically to purge expired secrets mapping to dropped workers."""
        now = datetime.utcnow().isoformat()
        db = await get_db()
        try:
            cursor = await db.execute("DELETE FROM devplane_secrets WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            await db.commit()
            if cursor.rowcount > 0:
                logger.info(f"Purged {cursor.rowcount} expired secrets from Vault.")
            return cursor.rowcount
        finally:
            await db.close()

_vault_instance = None
def get_vault() -> DevPlaneVault:
    global _vault_instance
    if not _vault_instance:
        _vault_instance = DevPlaneVault()
    return _vault_instance
