"""JWT Token Management for SSO.

This module provides JWT token creation, validation, and management for SSO sessions.
"""

import os
import json
import logging
import hashlib
import base64
import time
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

import jwt

logger = logging.getLogger("devplane.sso.jwt")


class TokenType(str, Enum):
    """JWT token types."""
    ACCESS = "access"
    REFRESH = "refresh"
    ID = "id"


@dataclass
class TokenPayload:
    """JWT token payload."""
    sub: str  # Subject (user ID)
    email: str
    name: Optional[str] = None
    roles: List[str] = None
    token_type: TokenType = TokenType.ACCESS
    exp: Optional[int] = None
    iat: Optional[int] = None
    iss: Optional[str] = None
    aud: Optional[str] = None
    nonce: Optional[str] = None
    # Custom claims
    provider: Optional[str] = None
    provider_id: Optional[str] = None
    environment: Optional[str] = None
    scope: Optional[List[str]] = None


class JWTManager:
    """JWT Token Manager.
    
    Handles token creation, validation, and refresh for SSO.
    """
    
    def __init__(self, secret_key: str = None, algorithm: str = "HS256",
                 access_token_expire: int = 3600, refresh_token_expire: int = 604800):
        """Initialize JWT manager.
        
        Args:
            secret_key: Secret key for signing tokens (or use JWT_SECRET env)
            algorithm: Signing algorithm (default: HS256)
            access_token_expire: Access token expiry in seconds (default: 1 hour)
            refresh_token_expire: Refresh token expiry in seconds (default: 7 days)
        """
        self.secret_key = secret_key or os.environ.get("JWT_SECRET")
        self.algorithm = algorithm
        self.access_token_expire = access_token_expire
        self.refresh_token_expire = refresh_token_expire
        
        if not self.secret_key:
            # Generate a temporary key if not set
            self.secret_key = base64.b64encode(secrets.token_bytes(32)).decode()
            logger.warning("JWT_SECRET not set. Using ephemeral key.")
        
        # For RS256, load public/private keys
        self.private_key = os.environ.get("JWT_PRIVATE_KEY")
        self.public_key = os.environ.get("JWT_PUBLIC_KEY")
        
        if algorithm.startswith("RS") and not self.private_key:
            logger.warning("RS256 algorithm specified but JWT_PRIVATE_KEY not set, using HS256")
            self.algorithm = "HS256"
    
    def create_token_payload(self, user_id: str, email: str, 
                           token_type: TokenType = TokenType.ACCESS,
                           **extra_claims) -> Dict[str, Any]:
        """Create a JWT payload.
        
        Args:
            user_id: User identifier
            email: User email
            token_type: Type of token
            **extra_claims: Additional claims to include
            
        Returns:
            JWT payload dictionary
        """
        now = int(time.time())
        
        if token_type == TokenType.ACCESS:
            exp = now + self.access_token_expire
        elif token_type == TokenType.REFRESH:
            exp = now + self.refresh_token_expire
        else:
            exp = now + self.access_token_expire
        
        payload = {
            "sub": user_id,
            "email": email,
            "token_type": token_type.value,
            "iat": now,
            "exp": exp,
            "iss": os.environ.get("JWT_ISSUER", "devplane"),
            "aud": os.environ.get("JWT_AUDIENCE", "devplane")
        }
        
        # Add extra claims
        for key, value in extra_claims.items():
            if value is not None:
                payload[key] = value
        
        return payload
    
    def encode_token(self, payload: Dict[str, Any]) -> str:
        """Encode a JWT token.
        
        Args:
            payload: Token payload
            
        Returns:
            Encoded JWT string
        """
        try:
            if self.algorithm.startswith("RS"):
                # Use RSA private key
                import cryptography
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.backends import default_backend
                
                private_key = serialization.load_pem_private_key(
                    self.private_key.encode(),
                    password=None,
                    backend=default_backend()
                )
                return jwt.encode(payload, private_key, algorithm=self.algorithm)
            else:
                # Use HMAC
                return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        except Exception as e:
            logger.error(f"Token encoding failed: {e}")
            raise
    
    def decode_token(self, token: str, token_type: TokenType = None) -> Optional[Dict]:
        """Decode and validate a JWT token.
        
        Args:
            token: JWT string
            token_type: Expected token type (optional)
            
        Returns:
            Decoded payload or None if invalid
        """
        try:
            if self.algorithm.startswith("RS"):
                # Use RSA public key
                import cryptography
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.backends import default_backend
                
                public_key = serialization.load_pem_public_key(
                    self.public_key.encode(),
                    backend=default_backend()
                )
                payload = jwt.decode(token, public_key, algorithms=[self.algorithm],
                                   audience=os.environ.get("JWT_AUDIENCE", "devplane"),
                                   issuer=os.environ.get("JWT_ISSUER", "devplane"))
            else:
                payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm],
                                   audience=os.environ.get("JWT_AUDIENCE", "devplane"),
                                   issuer=os.environ.get("JWT_ISSUER", "devplane"))
            
            # Verify token type if specified
            if token_type and payload.get("token_type") != token_type.value:
                logger.warning(f"Token type mismatch: expected {token_type.value}")
                return None
            
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.debug("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None
        except Exception as e:
            logger.error(f"Token decode error: {e}")
            return None
    
    def create_access_token(self, user_id: str, email: str, 
                           name: str = None, roles: List[str] = None,
                           provider: str = None, scope: List[str] = None,
                           environment: str = None) -> str:
        """Create an access token.
        
        Args:
            user_id: User identifier
            email: User email
            name: User name
            roles: User roles
            provider: SSO provider
            scope: Token scope
            environment: Environment (dev/staging/prod)
            
        Returns:
            Encoded JWT access token
        """
        payload = self.create_token_payload(
            user_id=user_id,
            email=email,
            token_type=TokenType.ACCESS,
            name=name,
            roles=roles or [],
            provider=provider,
            scope=scope,
            environment=environment
        )
        
        return self.encode_token(payload)
    
    def create_refresh_token(self, user_id: str, email: str, 
                            provider: str = None) -> str:
        """Create a refresh token.
        
        Args:
            user_id: User identifier
            email: User email
            provider: SSO provider
            
        Returns:
            Encoded JWT refresh token
        """
        payload = self.create_token_payload(
            user_id=user_id,
            email=email,
            token_type=TokenType.REFRESH,
            provider=provider
        )
        
        return self.encode_token(payload)
    
    def create_id_token(self, user_id: str, email: str, 
                       name: str = None, nonce: str = None,
                       provider: str = None) -> str:
        """Create an ID token (for OIDC).
        
        Args:
            user_id: User identifier
            email: User email
            name: User name
            nonce: OIDC nonce
            provider: SSO provider
            
        Returns:
            Encoded JWT ID token
        """
        payload = self.create_token_payload(
            user_id=user_id,
            email=email,
            token_type=TokenType.ID,
            name=name,
            nonce=nonce,
            provider=provider
        )
        
        return self.encode_token(payload)
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify a token and return payload.
        
        Args:
            token: JWT string
            
        Returns:
            Verified payload or None
        """
        return self.decode_token(token)
    
    def refresh_access_token(self, refresh_token: str) -> Optional[Dict]:
        """Create new access token from refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            New access token or None
        """
        payload = self.decode_token(refresh_token, TokenType.REFRESH)
        
        if not payload:
            return None
        
        # Create new access token
        new_access_token = self.create_access_token(
            user_id=payload.get("sub"),
            email=payload.get("email"),
            name=payload.get("name"),
            roles=payload.get("roles", []),
            provider=payload.get("provider"),
            scope=payload.get("scope"),
            environment=payload.get("environment")
        )
        
        return {
            "access_token": new_access_token,
            "token_type": "Bearer",
            "expires_in": self.access_token_expire
        }
    
    def revoke_token(self, token: str) -> bool:
        """Revoke a token (add to blocklist).
        
        Note: This is a placeholder. In production, implement a proper
        token blocklist using Redis or database.
        
        Args:
            token: JWT string to revoke
            
        Returns:
            True if revoked
        """
        # In production, add token JTI to blocklist
        # For now, just log the revocation
        payload = self.decode_token(token)
        if payload:
            jti = payload.get("jti", payload.get("sub"))
            logger.info(f"Token revoked: {jti}")
        return True
    
    def get_token_claims(self, token: str) -> Optional[Dict]:
        """Get claims from token without verification.
        
        Warning: Only use for debugging/logging. Always verify for security.
        
        Args:
            token: JWT string
            
        Returns:
            Claims dictionary or None
        """
        try:
            # Decode without verification for inspection
            parts = token.split(".")
            if len(parts) != 3:
                return None
            
            # Decode payload
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload
        except Exception as e:
            logger.error(f"Failed to get token claims: {e}")
            return None


# ─── Factory Functions ───────────────────────────────────────────────────────────

_jwt_manager: Optional[JWTManager] = None


def get_jwt_manager() -> JWTManager:
    """Get or create the global JWT manager."""
    global _jwt_manager
    
    if _jwt_manager is None:
        _jwt_manager = JWTManager()
    
    return _jwt_manager


def create_access_token(user_id: str, email: str, **kwargs) -> str:
    """Convenience function to create an access token."""
    return get_jwt_manager().create_access_token(user_id, email, **kwargs)


def create_refresh_token(user_id: str, email: str, **kwargs) -> str:
    """Convenience function to create a refresh token."""
    return get_jwt_manager().create_refresh_token(user_id, email, **kwargs)


def verify_token(token: str) -> Optional[Dict]:
    """Convenience function to verify a token."""
    return get_jwt_manager().verify_token(token)


def decode_token(token: str) -> Optional[Dict]:
    """Convenience function to decode a token."""
    return get_jwt_manager().decode_token(token)
