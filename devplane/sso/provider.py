"""SSO Provider — OAuth2/OIDC Implementation.

This module implements OAuth2 and OIDC authentication providers for DevPlane.
Supports multiple identity providers including Google, GitHub, Microsoft, Okta, and generic OIDC.
"""

import os
import json
import logging
import secrets
import urllib.parse
import hashlib
import base64
import asyncio
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlencode, quote

import aiohttp

logger = logging.getLogger("devplane.sso.provider")


class ProviderType(str, Enum):
    """Supported SSO providers."""
    GOOGLE = "google"
    GITHUB = "github"
    MICROSOFT = "microsoft"
    OKTA = "okta"
    OIDC = "oidc"
    GENERIC = "generic"


@dataclass
class UserInfo:
    """User information from identity provider."""
    id: str
    email: str
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    picture: Optional[str] = None
    locale: Optional[str] = None
    provider: Optional[str] = None
    raw: Optional[Dict] = None


@dataclass
class AuthorizationCode:
    """OAuth2 authorization code exchange result."""
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    id_token: Optional[str] = None


class SSOProvider:
    """Base SSO Provider class."""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, 
                 scopes: List[str] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes or ["openid", "profile", "email"]
        self._state_store: Dict[str, Dict] = {}
    
    def generate_state(self) -> str:
        """Generate and store OAuth state parameter."""
        state = secrets.token_urlsafe(32)
        self._state_store[state] = {
            "created_at": datetime.utcnow(),
            "used": False
        }
        return state
    
    def validate_state(self, state: str) -> bool:
        """Validate OAuth state parameter."""
        if state not in self._state_store:
            return False
        
        state_data = self._state_store[state]
        
        # Check if already used
        if state_data.get("used"):
            return False
        
        # Check if expired (10 minutes)
        created_at = state_data.get("created_at")
        if created_at and datetime.utcnow() - created_at > timedelta(minutes=10):
            del self._state_store[state]
            return False
        
        # Mark as used
        state_data["used"] = True
        return True
    
    def get_authorization_url(self, state: str, nonce: str = None) -> str:
        """Get the OAuth2 authorization URL.
        
        Must be implemented by subclasses.
        """
        raise NotImplementedError
    
    async def exchange_code(self, code: str) -> AuthorizationCode:
        """Exchange authorization code for tokens.
        
        Must be implemented by subclasses.
        """
        raise NotImplementedError
    
    async def get_user_info(self, access_token: str) -> UserInfo:
        """Get user information from provider.
        
        Must be implemented by subclasses.
        """
        raise NotImplementedError
    
    async def refresh_access_token(self, refresh_token: str) -> AuthorizationCode:
        """Refresh access token.
        
        Must be implemented by subclasses.
        """
        raise NotImplementedError


class GoogleProvider(SSOProvider):
    """Google OAuth2 Provider."""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        super().__init__(client_id, client_secret, redirect_uri, 
                        ["openid", "profile", "email"])
        self.auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    def get_authorization_url(self, state: str, nonce: str = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent"
        }
        if nonce:
            params["nonce"] = nonce
        return f"{self.auth_url}?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> AuthorizationCode:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    raise Exception(f"Token exchange failed: {result}")
                
                return AuthorizationCode(
                    access_token=result["access_token"],
                    token_type=result.get("token_type", "Bearer"),
                    expires_in=result.get("expires_in", 3600),
                    refresh_token=result.get("refresh_token"),
                    scope=result.get("scope"),
                    id_token=result.get("id_token")
                )
    
    async def get_user_info(self, access_token: str) -> UserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.userinfo_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                return UserInfo(
                    id=result["id"],
                    email=result["email"],
                    name=result.get("name"),
                    given_name=result.get("given_name"),
                    family_name=result.get("family_name"),
                    picture=result.get("picture"),
                    locale=result.get("locale"),
                    provider="google",
                    raw=result
                )


class GitHubProvider(SSOProvider):
    """GitHub OAuth2 Provider."""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        super().__init__(client_id, client_secret, redirect_uri,
                        ["read:user", "user:email"])
        self.auth_url = "https://github.com/login/oauth/authorize"
        self.token_url = "https://github.com/login/oauth/access_token"
        self.userinfo_url = "https://api.github.com/user"
        self.useremails_url = "https://api.github.com/user/emails"
    
    def get_authorization_url(self, state: str, nonce: str = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state
        }
        return f"{self.auth_url}?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> AuthorizationCode:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code
        }
        
        headers = {"Accept": "application/json"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    raise Exception(f"Token exchange failed: {result}")
                
                return AuthorizationCode(
                    access_token=result["access_token"],
                    token_type=result.get("token_type", "Bearer"),
                    expires_in=result.get("expires_in", 3600),
                    refresh_token=result.get("refresh_token"),
                    scope=result.get("scope")
                )
    
    async def get_user_info(self, access_token: str) -> UserInfo:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        async with aiohttp.ClientSession() as session:
            # Get user info
            async with session.get(self.userinfo_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
            
            # Get primary email
            email = result.get("email")
            if not email:
                async with session.get(self.useremails_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    emails = await resp.json()
                    for e in emails:
                        if e.get("primary"):
                            email = e.get("email")
                            break
            
            return UserInfo(
                id=str(result["id"]),
                email=email or "",
                name=result.get("name"),
                given_name=result.get("login"),
                picture=result.get("avatar_url"),
                provider="github",
                raw=result
            )


class MicrosoftProvider(SSOProvider):
    """Microsoft Azure AD OAuth2 Provider."""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, tenant_id: str = "common"):
        super().__init__(client_id, client_secret, redirect_uri,
                        ["openid", "profile", "email"])
        self.tenant_id = tenant_id
        self.auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        self.token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self.userinfo_url = "https://graph.microsoft.com/v1.0/me"
    
    def get_authorization_url(self, state: str, nonce: str = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "response_mode": "query"
        }
        return f"{self.auth_url}?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> AuthorizationCode:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes)
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    raise Exception(f"Token exchange failed: {result}")
                
                return AuthorizationCode(
                    access_token=result["access_token"],
                    token_type=result.get("token_type", "Bearer"),
                    expires_in=result.get("expires_in", 3600),
                    refresh_token=result.get("refresh_token"),
                    scope=result.get("scope"),
                    id_token=result.get("id_token")
                )
    
    async def get_user_info(self, access_token: str) -> UserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(self.userinfo_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                return UserInfo(
                    id=result.get("id", ""),
                    email=result.get("mail") or result.get("userPrincipalName", ""),
                    name=result.get("displayName"),
                    given_name=result.get("givenName"),
                    family_name=result.get("surname"),
                    provider="microsoft",
                    raw=result
                )


class OIDCProvider(SSOProvider):
    """Generic OIDC Provider."""
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str,
                 issuer_url: str, scopes: List[str] = None):
        super().__init__(client_id, client_secret, redirect_uri, 
                        scopes or ["openid", "profile", "email"])
        self.issuer_url = issuer_url.rstrip("/")
        self._jwks: Optional[Dict] = None
    
    async def _discover(self) -> Dict:
        """Fetch OIDC discovery document."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.issuer_url}/.well-known/openid-configuration", 
                                  timeout=aiohttp.ClientTimeout(total=30)) as resp:
                return await resp.json()
    
    async def get_authorization_url(self, state: str, nonce: str = None) -> str:
        discovery = await self._discover()
        self._auth_endpoint = discovery.get("authorization_endpoint")
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state
        }
        if nonce:
            params["nonce"] = nonce
        
        return f"{self._auth_endpoint}?{urlencode(params)}"
    
    async def exchange_code(self, code: str) -> AuthorizationCode:
        discovery = await self._discover()
        token_endpoint = discovery.get("token_endpoint")
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(token_endpoint, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    raise Exception(f"Token exchange failed: {result}")
                
                return AuthorizationCode(
                    access_token=result["access_token"],
                    token_type=result.get("token_type", "Bearer"),
                    expires_in=result.get("expires_in", 3600),
                    refresh_token=result.get("refresh_token"),
                    scope=result.get("scope"),
                    id_token=result.get("id_token")
                )
    
    async def get_user_info(self, access_token: str) -> UserInfo:
        discovery = await self._discover()
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(userinfo_endpoint, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                return UserInfo(
                    id=result.get("sub", ""),
                    email=result.get("email", ""),
                    name=result.get("name"),
                    given_name=result.get("given_name"),
                    family_name=result.get("family_name"),
                    picture=result.get("picture"),
                    locale=result.get("locale"),
                    provider="oidc",
                    raw=result
                )


# ─── Provider Factory ───────────────────────────────────────────────────────────

_provider_cache: Dict[ProviderType, SSOProvider] = {}


def get_sso_provider(provider_type: ProviderType = None) -> Optional[SSOProvider]:
    """Get the configured SSO provider.
    
    Args:
        provider_type: Type of provider (defaults to env var SSO_PROVIDER)
        
    Returns:
        Configured SSO provider or None
    """
    if provider_type is None:
        provider_type = os.environ.get("SSO_PROVIDER", "google").lower()
        try:
            provider_type = ProviderType(provider_type)
        except ValueError:
            logger.error(f"Invalid SSO provider: {provider_type}")
            return None
    
    if provider_type in _provider_cache:
        return _provider_cache[provider_type]
    
    return None


def configure_provider(provider_type: ProviderType, **config) -> SSOProvider:
    """Configure an SSO provider.
    
    Args:
        provider_type: Type of provider
        **config: Provider configuration (client_id, client_secret, redirect_uri, etc.)
        
    Returns:
        Configured SSO provider
    """
    client_id = config.get("client_id") or os.environ.get(f"SSO_{provider_type.value.upper()}_CLIENT_ID")
    client_secret = config.get("client_secret") or os.environ.get(f"SSO_{provider_type.value.upper()}_CLIENT_SECRET")
    redirect_uri = config.get("redirect_uri") or os.environ.get("SSO_REDIRECT_URI")
    
    if not all([client_id, client_secret, redirect_uri]):
        raise ValueError(f"Missing required config for {provider_type.value}")
    
    provider: SSOProvider
    
    if provider_type == ProviderType.GOOGLE:
        provider = GoogleProvider(client_id, client_secret, redirect_uri)
    elif provider_type == ProviderType.GITHUB:
        provider = GitHubProvider(client_id, client_secret, redirect_uri)
    elif provider_type == ProviderType.MICROSOFT:
        tenant_id = config.get("tenant_id") or os.environ.get("SSO_MICROSOFT_TENANT_ID", "common")
        provider = MicrosoftProvider(client_id, client_secret, redirect_uri, tenant_id)
    elif provider_type == ProviderType.OIDC:
        issuer_url = config.get("issuer_url") or os.environ.get("SSO_OIDC_ISSUER_URL")
        if not issuer_url:
            raise ValueError("OIDC issuer_url required")
        provider = OIDCProvider(client_id, client_secret, redirect_uri, issuer_url)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    
    _provider_cache[provider_type] = provider
    return provider


def get_configured_providers() -> List[SSOProvider]:
    """Get all configured SSO providers.
    
    Returns:
        List of configured providers
    """
    providers = []
    
    for provider_type in ProviderType:
        try:
            provider = configure_provider(provider_type)
            providers.append(provider)
        except ValueError:
            continue
    
    return providers
