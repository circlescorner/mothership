"""DevPlane SSO Module — OAuth2/OIDC Integration.

This module provides Single Sign-On (SSO) capabilities using OAuth2 and OIDC.

Components:
- provider: OAuth2/OIDC provider implementation
- jwt: JWT token management
- session: Session handling for SSO

Supported Providers:
- Google
- GitHub
- Microsoft Azure AD
- Okta
- Generic OIDC providers
"""

from devplane.sso.provider import (
    SSOProvider,
    OAuth2Provider,
    OIDCProvider,
    ProviderType,
    get_sso_provider,
    configure_provider
)
from devplane.sso.jwt import (
    JWTManager,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    verify_token,
    decode_token
)
from devplane.sso.session import (
    SSOSessionManager,
    SessionStore,
    create_sso_session,
    validate_sso_session
)

__all__ = [
    # Provider
    "SSOProvider",
    "OAuth2Provider", 
    "OIDCProvider",
    "ProviderType",
    "get_sso_provider",
    "configure_provider",
    # JWT
    "JWTManager",
    "TokenPayload",
    "create_access_token",
    "create_refresh_token", 
    "verify_token",
    "decode_token",
    # Session
    "SSOSessionManager",
    "SessionStore",
    "create_sso_session",
    "validate_sso_session"
]
