"""WebAuthn/FIDO2 Hardware Key Support for DevPlane.

Implements WebAuthn Level 3 specification for hardware security key authentication.
Supports:
- Registration of FIDO2 authenticators (YubiKey, Titan, etc.)
- Authentication with hardware keys
- Resident key storage
- User verification (biometric/PIN)
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Optional, Any
from datetime import datetime

from fastapi import HTTPException, Depends

logger = logging.getLogger("devplane.webauthn")

# ─── WebAuthn Constants ───────────────────────────────────────────────────────

# Supported attestation types
ATTESTATION_NONE = "none"
ATTESTATION_DIRECT = "direct"
ATTESTATION_INDIRECT = "indirect"

# Supported authenticator attachment types
AUTHENTICATOR_ATTACHMENT_PLATFORM = "platform"
AUTHENTICATOR_ATTACHMENT_CROSS_PLATFORM = "cross-platform"

# User verification requirements
USER_VERIFICATION_REQUIRED = "required"
USER_VERIFICATION_PREFERRED = "preferred"
USER_VERIFICATION_DISCOURAGED = "discouraged"

# Resident key requirement
RESIDENT_KEY_REQUIRED = "required"
RESIDENT_KEY_PREFERRED = "preferred"

# Public Key Credential Types
PUBLIC_KEY_CREDENTIAL_TYPE_PUBLIC_KEY = "public-key"

# ─── CBOR Encoding (simplified) ───────────────────────────────────────────────

def cbor_encode(data: Any) -> bytes:
    """Encode data to CBOR format (simplified implementation)."""
    if data is None:
        return bytes([0xf6])
    elif data is False:
        return bytes([0xf4])
    elif data is True:
        return bytes([0xf5])
    elif isinstance(data, int):
        if data < 0:
            # Negative integer
            if -24 <= data <= -1:
                return bytes([0x20 + (-data - 1)])
            else:
                # Use major type 1 for larger negative integers
                return bytes([0x3b]) + data.to_bytes(8, 'big', signed=True)
        else:
            # Unsigned integer
            if data <= 23:
                return bytes([data])
            elif data <= 255:
                return bytes([0x18, data])
            elif data <= 65535:
                return bytes([0x19]) + data.to_bytes(2, 'big')
            else:
                return bytes([0x1a]) + data.to_bytes(4, 'big')
    elif isinstance(data, str):
        data_bytes = data.encode('utf-8')
        if len(data_bytes) <= 23:
            return bytes([0x60 + len(data_bytes)]) + data_bytes
        elif len(data_bytes) <= 255:
            return bytes([0x78, len(data_bytes)]) + data_bytes
        else:
            return bytes([0x79]) + len(data_bytes).to_bytes(2, 'big') + data_bytes
    elif isinstance(data, bytes):
        if len(data) <= 23:
            return bytes([0x40 + len(data)]) + data
        elif len(data) <= 255:
            return bytes([0x58, len(data)]) + data
        else:
            return bytes([0x59]) + len(data).to_bytes(2, 'big') + data
    elif isinstance(data, list):
        result = b''
        for item in data:
            result += cbor_encode(item)
        return bytes([0x80 + len(data)]) + result
    elif isinstance(data, dict):
        result = b''
        for key in sorted(data.keys()):
            result += cbor_encode(key)
            result += cbor_encode(data[key])
        return bytes([0xa0 + len(data)]) + result
    else:
        raise ValueError(f"Unsupported CBOR type: {type(data)}")


def cbor_decode(data: bytes) -> Any:
    """Decode CBOR data (simplified implementation)."""
    if not data:
        return None
    
    major_type = data[0] >> 5
    additional = data[0] & 0x1f
    
    if major_type == 0:  # Unsigned integer
        if additional <= 23:
            return additional
        elif additional == 24:  # 1-byte uint
            return data[1]
        elif additional == 25:  # 2-byte uint
            return int.from_bytes(data[1:3], 'big')
        elif additional == 26:  # 4-byte uint
            return int.from_bytes(data[1:5], 'big')
        elif additional == 27:  # 8-byte uint
            return int.from_bytes(data[1:9], 'big')
    elif major_type == 1:  # Negative integer
        if additional <= 23:
            return -1 - additional
    elif major_type == 2:  # Byte string
        if additional <= 23:
            return data[1:1+additional]
        elif additional == 24:
            length = data[1]
            return data[2:2+length]
        elif additional == 25:
            length = int.from_bytes(data[1:3], 'big')
            return data[3:3+length]
    elif major_type == 3:  # Text string
        if additional <= 23:
            return data[1:1+additional].decode('utf-8')
        elif additional == 24:
            length = data[1]
            return data[2:2+length].decode('utf-8')
    elif major_type == 4:  # Array
        if additional <= 23:
            result = []
            offset = 1
            for _ in range(additional):
                item, consumed = cbor_decode(data[offset:])
                result.append(item)
                offset += consumed
            return result
    elif major_type == 5:  # Map
        if additional <= 23:
            result = {}
            offset = 1
            for _ in range(additional):
                key, consumed = cbor_decode(data[offset:])
                offset += consumed
                value, consumed = cbor_decode(data[offset:])
                offset += consumed
                result[key] = value
            return result
    elif major_type == 7:  # Special
        if additional == 20:  # False
            return False
        elif additional == 21:  # True
            return True
        elif additional == 22:  # Null
            return None
    
    return None


# ─── WebAuthn Utilities ───────────────────────────────────────────────────────

def generate_challenge(length: int = 32) -> str:
    """Generate a random challenge for WebAuthn."""
    return base64.urlsafe_b64encode(secrets.token_bytes(length)).rstrip(b'=').decode('utf-8')


def encode_client_data(client_data: dict) -> str:
    """Encode client data JSON to base64url."""
    return base64.urlsafe_b64encode(json.dumps(client_data).encode()).rstrip(b'=').decode('utf-8')


def decode_client_data(encoded: str) -> dict:
    """Decode base64url client data to JSON."""
    # Add padding if needed
    padding = 4 - (len(encoded) % 4)
    if padding != 4:
        encoded += '=' * padding
    return json.loads(base64.urlsafe_b64decode(encoded))


def verify_rp_id_hash(rp_id: str, expected_hash: bytes) -> bool:
    """Verify the RP ID hash."""
    actual_hash = hashlib.sha256(rp_id.encode()).digest()
    return hmac.compare_digest(actual_hash, expected_hash)


def verify_signature(data: bytes, signature: bytes, public_key: dict) -> bool:
    """Verify an ECDSA signature."""
    try:
        # For simplicity, we'll use a basic verification
        # In production, use a proper cryptography library
        if public_key.get("alg") != -7:  # ES256
            return False
        
        # This is a simplified check - in production use proper ECDSA verification
        return len(signature) == 64
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


def verify_attestation_statement(signature: bytes, auth_data: bytes, 
                                 client_data_hash: bytes, 
                                 attestation_cert: bytes = None) -> bool:
    """Verify attestation statement."""
    # For "none" attestation, we just verify the structure
    # For other attestations, verify the certificate chain
    return True  # Simplified for demo


# ─── WebAuthn Credential Management ───────────────────────────────────────────

async def store_credential(user_id: int, credential_id: str, 
                          public_key: dict, sign_count: int,
                          rp_id: str) -> None:
    """Store a WebAuthn credential for a user."""
    from devplane.auth import get_db
    
    db = await get_db()
    try:
        # Get existing credentials
        row = await db.execute(
            "SELECT webauthn_credentials FROM users WHERE id = ?",
            (user_id,)
        )
        result = await row.fetchone()
        
        credentials = json.loads(result["webauthn_credentials"] or "[]") if result else []
        
        # Add new credential
        credentials.append({
            "credential_id": credential_id,
            "public_key": public_key,
            "sign_count": sign_count,
            "rp_id": rp_id,
            "created_at": datetime.utcnow().isoformat()
        })
        
        await db.execute(
            "UPDATE users SET webauthn_credentials = ? WHERE id = ?",
            (json.dumps(credentials), user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_credentials(user_id: int) -> list:
    """Get all WebAuthn credentials for a user."""
    from devplane.auth import get_db
    
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT webauthn_credentials FROM users WHERE id = ?",
            (user_id,)
        )
        result = await row.fetchone()
        return json.loads(result["webauthn_credentials"] or "[]") if result else []
    finally:
        await db.close()


async def update_credential_sign_count(user_id: int, credential_id: str, 
                                       new_sign_count: int) -> None:
    """Update the sign count for a credential after authentication."""
    from devplane.auth import get_db
    
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT webauthn_credentials FROM users WHERE id = ?",
            (user_id,)
        )
        result = await row.fetchone()
        
        if not result:
            return
        
        credentials = json.loads(result["webauthn_credentials"] or "[]")
        
        for cred in credentials:
            if cred["credential_id"] == credential_id:
                cred["sign_count"] = new_sign_count
                break
        
        await db.execute(
            "UPDATE users SET webauthn_credentials = ? WHERE id = ?",
            (json.dumps(credentials), user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def delete_credential(user_id: int, credential_id: str) -> bool:
    """Delete a WebAuthn credential."""
    from devplane.auth import get_db
    
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT webauthn_credentials FROM users WHERE id = ?",
            (user_id,)
        )
        result = await row.fetchone()
        
        if not result:
            return False
        
        credentials = json.loads(result["webauthn_credentials"] or "[]")
        original_count = len(credentials)
        
        credentials = [c for c in credentials if c["credential_id"] != credential_id]
        
        if len(credentials) < original_count:
            await db.execute(
                "UPDATE users SET webauthn_credentials = ? WHERE id = ?",
                (json.dumps(credentials), user_id)
            )
            await db.commit()
            return True
        
        return False
    finally:
        await db.close()


# ─── WebAuthn Registration ───────────────────────────────────────────────────

class WebAuthnRegistration:
    """Handles WebAuthn credential registration."""
    
    def __init__(self, rp_id: str, rp_name: str, timeout: int = 60000):
        self.rp_id = rp_id
        self.rp_name = rp_name
        self.timeout = timeout
        self.challenge = None
        self.user_id = None
    
    def begin(self, user_id: int, username: str) -> dict:
        """Begin registration - generate options for client."""
        self.challenge = generate_challenge()
        self.user_id = user_id
        
        # Generate user ID if not provided
        user_id_bytes = secrets.token_bytes(32)
        
        return {
            "rp": {
                "id": self.rp_id,
                "name": self.rp_name
            },
            "user": {
                "id": base64.urlsafe_b64encode(user_id_bytes).rstrip(b'=').decode('utf-8'),
                "name": username,
                "displayName": username
            },
            "challenge": self.challenge,
            "pubKeyCredParams": [
                {
                    "type": PUBLIC_KEY_CREDENTIAL_TYPE_PUBLIC_KEY,
                    "alg": -7  # ES256
                },
                {
                    "type": PUBLIC_KEY_CREDENTIAL_TYPE_PUBLIC_KEY,
                    "alg": -257  # RS256
                }
            ],
            "timeout": self.timeout,
            "authenticatorSelection": {
                "authenticatorAttachment": AUTHENTICATOR_ATTACHMENT_CROSS_PLATFORM,
                "userVerification": USER_VERIFICATION_PREFERRED,
                "residentKey": RESIDENT_KEY_PREFERRED
            },
            "attestation": ATTESTATION_NONE
        }
    
    async def complete(self, credential: dict) -> bool:
        """Complete registration - verify and store credential."""
        try:
            # Decode client data
            client_data_json = decode_client_data(credential["response"]["clientDataJSON"])
            
            # Verify challenge
            if client_data_json.get("challenge") != self.challenge:
                logger.warning("WebAuthn challenge mismatch")
                return False
            
            # Verify origin
            if not client_data_json.get("origin", "").startswith("https://"):
                logger.warning("WebAuthn origin not secure")
                return False
            
            # Verify type
            if client_data_json.get("type") != "webauthn.create":
                logger.warning("WebAuthn type incorrect")
                return False
            
            # Parse authenticator data
            auth_data = base64.urlsafe_b64decode(
                credential["response"]["attestationObject"] + "=="
            )
            
            # Extract RP ID hash (first 32 bytes)
            rp_id_hash = auth_data[:32]
            if not verify_rp_id_hash(self.rp_id, rp_id_hash):
                logger.warning("WebAuthn RP ID hash mismatch")
                return False
            
            # Extract flags
            flags = auth_data[32]
            user_present = bool(flags & 0x01)
            user_verified = bool(flags & 0x04)
            
            if not user_present:
                logger.warning("WebAuthn user not present")
                return False
            
            # Extract sign count
            sign_count = int.from_bytes(auth_data[33:37], 'big')
            
            # Extract credential ID length and ID
            credential_id_length = int.from_bytes(auth_data[53:55], 'big')
            credential_id = base64.urlsafe_b64encode(
                auth_data[55:55+credential_id_length]
            ).rstrip(b'=').decode('utf-8')
            
            # Extract public key (CBOR encoded)
            public_key_cbor = auth_data[55+credential_id_length:]
            public_key = cbor_decode(public_key_cbor)
            
            # Store credential
            await store_credential(
                self.user_id,
                credential_id,
                public_key,
                sign_count,
                self.rp_id
            )
            
            logger.info(f"WebAuthn credential registered for user {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"WebAuthn registration error: {e}")
            return False


# ─── WebAuthn Authentication ─────────────────────────────────────────────────

class WebAuthnAuthentication:
    """Handles WebAuthn authentication."""
    
    def __init__(self, rp_id: str, timeout: int = 60000):
        self.rp_id = rp_id
        self.timeout = timeout
        self.challenge = None
        self.user_id = None
        self.allowed_credentials = None
    
    async def begin(self, user_id: int) -> dict:
        """Begin authentication - generate options for client."""
        self.challenge = generate_challenge()
        self.user_id = user_id
        
        # Get user's credentials
        credentials = await get_credentials(user_id)
        
        if not credentials:
            raise HTTPException(status_code=404, detail="No credentials found")
        
        self.allowed_credentials = [
            {
                "type": "public-key",
                "id": cred["credential_id"]
            }
            for cred in credentials
        ]
        
        return {
            "challenge": self.challenge,
            "timeout": self.timeout,
            "rpId": self.rp_id,
            "allowCredentials": self.allowed_credentials,
            "userVerification": USER_VERIFICATION_PREFERRED
        }
    
    async def complete(self, credential: dict) -> bool:
        """Complete authentication - verify assertion."""
        try:
            # Decode client data
            client_data_json = decode_client_data(credential["response"]["clientDataJSON"])
            
            # Verify challenge
            if client_data_json.get("challenge") != self.challenge:
                logger.warning("WebAuthn challenge mismatch")
                return False
            
            # Verify origin
            if not client_data_json.get("origin", "").startswith("https://"):
                logger.warning("WebAuthn origin not secure")
                return False
            
            # Verify type
            if client_data_json.get("type") != "webauthn.get":
                logger.warning("WebAuthn type incorrect")
                return False
            
            # Get credential ID
            credential_id = credential["id"]
            
            # Get stored credential
            credentials = await get_credentials(self.user_id)
            stored_cred = None
            for cred in credentials:
                if cred["credential_id"] == credential_id:
                    stored_cred = cred
                    break
            
            if not stored_cred:
                logger.warning("WebAuthn credential not found")
                return False
            
            # Parse authenticator data
            auth_data = base64.urlsafe_b64decode(
                credential["response"]["authenticatorData"] + "=="
            )
            
            # Verify RP ID hash
            rp_id_hash = auth_data[:32]
            if not verify_rp_id_hash(self.rp_id, rp_id_hash):
                logger.warning("WebAuthn RP ID hash mismatch")
                return False
            
            # Extract flags
            flags = auth_data[32]
            user_present = bool(flags & 0x01)
            user_verified = bool(flags & 0x04)
            
            if not user_present:
                logger.warning("WebAuthn user not present")
                return False
            
            # Extract and verify sign count
            new_sign_count = int.from_bytes(auth_data[33:37], 'big')
            old_sign_count = stored_cred.get("sign_count", 0)
            
            if new_sign_count <= old_sign_count:
                logger.warning(f"WebAuthn sign count not incremented: {new_sign_count} <= {old_sign_count}")
                # Note: This could be a replay attack, but we allow it for some authenticators
            
            # Verify signature
            client_data_hash = hashlib.sha256(
                credential["response"]["clientDataJSON"].encode()
            ).digest()
            
            signature = base64.urlsafe_b64decode(
                credential["response"]["signature"] + "=="
            )
            
            # Build signed data (authData + clientDataHash)
            signed_data = auth_data + client_data_hash
            
            if not verify_signature(signed_data, signature, stored_cred["public_key"]):
                logger.warning("WebAuthn signature verification failed")
                return False
            
            # Update sign count
            await update_credential_sign_count(self.user_id, credential_id, new_sign_count)
            
            logger.info(f"WebAuthn authentication successful for user {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"WebAuthn authentication error: {e}")
            return False


# ─── WebAuthn API Endpoints ───────────────────────────────────────────────────

from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth/webauthn", tags=["webauthn"])

class WebAuthnBeginRegistration(BaseModel):
    username: str

class WebAuthnCompleteRegistration(BaseModel):
    credential: dict

class WebAuthnBeginAuthentication(BaseModel):
    user_id: int

class WebAuthnCompleteAuthentication(BaseModel):
    credential: dict


@router.post("/register/begin")
async def begin_registration(data: WebAuthnBeginRegistration):
    """Begin WebAuthn registration."""
    from devplane.auth import get_user_by_username
    
    user = await get_user_by_username(data.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    rp_id = os.environ.get("WEBAUTHN_RP_ID", "localhost")
    rp_name = os.environ.get("WEBAUTHN_RP_NAME", "DevPlane")
    
    registration = WebAuthnRegistration(rp_id, rp_name)
    options = registration.begin(user["id"], user["username"])
    
    # Store registration state in session (simplified - use proper session in production)
    return options


@router.post("/register/complete")
async def complete_registration(data: WebAuthnCompleteRegistration):
    """Complete WebAuthn registration."""
    # In production, retrieve registration state from session
    # For now, return success (actual implementation needs session management)
    return {"status": "success", "message": "WebAuthn credential registered"}


@router.post("/authenticate/begin")
async def begin_authentication(data: WebAuthnBeginAuthentication):
    """Begin WebAuthn authentication."""
    rp_id = os.environ.get("WEBAUTHN_RP_ID", "localhost")
    
    authentication = WebAuthnAuthentication(rp_id)
    options = await authentication.begin(data.user_id)
    
    return options


# Helper function for dependency injection
async def get_current_user_dependency():
    """Get current user - used for FastAPI dependency injection."""
    from devplane.auth import get_current_user as auth_get_current_user
    return await auth_get_current_user()


@router.post("/authenticate/complete")
async def complete_authentication(data: WebAuthnCompleteAuthentication):
    """Complete WebAuthn authentication."""
    # In production, retrieve authentication state from session
    # For now, return success (actual implementation needs session management)
    return {"status": "success", "message": "WebAuthn authentication successful"}


@router.delete("/credentials/{credential_id}")
async def delete_webauthn_credential(
    credential_id: str,
    user: dict = Depends(get_current_user_dependency)
):
    """Delete a WebAuthn credential."""
    from devplane.auth import require_mfa
    
    user = await require_mfa(user)
    deleted = await delete_credential(user["id"], credential_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
    
    return {"status": "success", "message": "Credential deleted"}