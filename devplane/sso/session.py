"""SSO Session Management.

This module provides session handling for SSO authentication flows.
"""

import os
import json
import logging
import secrets
import hashlib
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("devplane.sso.session")


class SessionStatus(str, Enum):
    """SSO session states."""
    PENDING = "pending"           # Authorization initiated, waiting for callback
    AUTHENTICATED = "authenticated"  # User authenticated, tokens available
    ACTIVE = "active"             # Session active
    EXPIRED = "expired"           # Session expired
    REVOKED = "revoked"           # Session manually revoked
    FAILED = "failed"             # Authentication failed


@dataclass
class SSOSession:
    """SSO Session data."""
    session_id: str
    state: str
    provider: str
    status: SessionStatus
    created_at: datetime
    expires_at: datetime
    user_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    nonce: Optional[str] = None
    redirect_uri: Optional[str] = None
    scope: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionStore:
    """In-memory session store.
    
    Note: For production, use Redis or database-backed storage.
    """
    
    def __init__(self, default_ttl: int = 600):
        """Initialize session store.
        
        Args:
            default_ttl: Default session TTL in seconds (default: 10 minutes)
        """
        self._sessions: Dict[str, SSOSession] = {}
        self._state_sessions: Dict[str, str] = {}  # state -> session_id mapping
        self.default_ttl = default_ttl
    
    def create_session(self, state: str, provider: str, redirect_uri: str,
                      scope: List[str] = None, nonce: str = None,
                      ttl: int = None) -> SSOSession:
        """Create a new SSO session.
        
        Args:
            state: OAuth state parameter
            provider: SSO provider type
            redirect_uri: OAuth redirect URI
            scope: Requested scopes
            nonce: OIDC nonce
            ttl: Session TTL in seconds
            
        Returns:
            Created SSO session
        """
        session_id = secrets.token_urlsafe(32)
        ttl = ttl or self.default_ttl
        
        session = SSOSession(
            session_id=session_id,
            state=state,
            provider=provider,
            status=SessionStatus.PENDING,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            redirect_uri=redirect_uri,
            scope=scope or [],
            nonce=nonce
        )
        
        self._sessions[session_id] = session
        self._state_sessions[state] = session_id
        
        logger.debug(f"Created SSO session: {session_id[:8]}... for {provider}")
        
        return session
    
    def get_session_by_id(self, session_id: str) -> Optional[SSOSession]:
        """Get session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session or None if not found/expired
        """
        session = self._sessions.get(session_id)
        
        if not session:
            return None
        
        # Check expiration
        if datetime.utcnow() > session.expires_at:
            session.status = SessionStatus.EXPIRED
            return None
        
        return session
    
    def get_session_by_state(self, state: str) -> Optional[SSOSession]:
        """Get session by OAuth state.
        
        Args:
            state: OAuth state parameter
            
        Returns:
            Session or None
        """
        session_id = self._state_sessions.get(state)
        
        if not session_id:
            return None
        
        return self.get_session_by_id(session_id)
    
    def update_session(self, session_id: str, **updates) -> Optional[SSOSession]:
        """Update session with new data.
        
        Args:
            session_id: Session identifier
            **updates: Fields to update
            
        Returns:
            Updated session or None
        """
        session = self.get_session_by_id(session_id)
        
        if not session:
            return None
        
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        
        return session
    
    def complete_session(self, session_id: str, user_id: str, email: str,
                        access_token: str, refresh_token: str = None,
                        id_token: str = None, name: str = None) -> Optional[SSOSession]:
        """Mark session as authenticated with tokens.
        
        Args:
            session_id: Session identifier
            user_id: User ID from provider
            email: User email
            access_token: Access token
            refresh_token: Refresh token (optional)
            id_token: ID token (optional)
            name: User name
            
        Returns:
            Updated session or None
        """
        session = self.get_session_by_id(session_id)
        
        if not session:
            return None
        
        session.user_id = user_id
        session.email = email
        session.name = name
        session.access_token = access_token
        session.refresh_token = refresh_token
        session.id_token = id_token
        session.status = SessionStatus.AUTHENTICATED
        
        # Extend session for authenticated state (1 hour)
        session.expires_at = datetime.utcnow() + timedelta(hours=1)
        
        logger.info(f"SSO session authenticated: {session_id[:8]}... for {email}")
        
        return session
    
    def revoke_session(self, session_id: str) -> bool:
        """Revoke a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if revoked
        """
        session = self.get_session_by_id(session_id)
        
        if not session:
            return False
        
        session.status = SessionStatus.REVOKED
        
        # Clear tokens
        session.access_token = None
        session.refresh_token = None
        session.id_token = None
        
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted
        """
        session = self._sessions.get(session_id)
        
        if not session:
            return False
        
        # Remove state mapping
        if session.state in self._state_sessions:
            del self._state_sessions[session.state]
        
        # Remove session
        del self._sessions[session_id]
        
        return True
    
    def cleanup_expired(self) -> int:
        """Clean up expired sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        now = datetime.utcnow()
        expired_ids = []
        
        for session_id, session in self._sessions.items():
            if now > session.expires_at:
                expired_ids.append(session_id)
        
        for session_id in expired_ids:
            session = self._sessions.get(session_id)
            if session and session.state in self._state_sessions:
                del self._state_sessions[session.state]
            if session_id in self._sessions:
                del self._sessions[session_id]
        
        if expired_ids:
            logger.debug(f"Cleaned up {len(expired_ids)} expired SSO sessions")
        
        return len(expired_ids)
    
    def get_active_sessions(self, user_id: str = None) -> List[SSOSession]:
        """Get active sessions.
        
        Args:
            user_id: Filter by user ID (optional)
            
        Returns:
            List of active sessions
        """
        now = datetime.utcnow()
        sessions = []
        
        for session in self._sessions.values():
            if now <= session.expires_at and session.status in [SessionStatus.AUTHENTICATED, SessionStatus.ACTIVE]:
                if user_id is None or session.user_id == user_id:
                    sessions.append(session)
        
        return sessions


class SSOSessionManager:
    """SSO Session Manager.
    
    Manages SSO authentication flows and sessions.
    """
    
    def __init__(self, default_ttl: int = 600):
        """Initialize SSO session manager.
        
        Args:
            default_ttl: Default session TTL in seconds
        """
        self.store = SessionStore(default_ttl)
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start_auth_flow(self, provider: str, redirect_uri: str,
                            scope: List[str] = None) -> Dict[str, str]:
        """Start an SSO authentication flow.
        
        Args:
            provider: SSO provider type
            redirect_uri: Redirect URI after auth
            scope: OAuth scopes
            
        Returns:
            Dict with session_id, state, and authorization_url
        """
        from devplane.sso.provider import get_sso_provider, ProviderType
        
        sso_provider = get_sso_provider(ProviderType(provider))
        
        if not sso_provider:
            raise ValueError(f"Provider not configured: {provider}")
        
        # Generate state and nonce
        state = sso_provider.generate_state()
        nonce = secrets.token_urlsafe(16) if "openid" in (scope or []) else None
        
        # Create session
        session = self.store.create_session(
            state=state,
            provider=provider,
            redirect_uri=redirect_uri,
            scope=scope,
            nonce=nonce
        )
        
        # Get authorization URL
        auth_url = sso_provider.get_authorization_url(state, nonce)
        
        return {
            "session_id": session.session_id,
            "state": state,
            "authorization_url": auth_url
        }
    
    async def handle_callback(self, state: str, code: str) -> Optional[Dict]:
        """Handle OAuth callback.
        
        Args:
            state: OAuth state parameter
            code: Authorization code
            
        Returns:
            Session data with tokens or None
        """
        from devplane.sso.provider import get_sso_provider, ProviderType
        
        # Validate state
        session = self.store.get_session_by_state(state)
        
        if not session:
            logger.warning(f"No session found for state: {state}")
            return None
        
        # Get provider
        try:
            provider_type = ProviderType(session.provider)
        except ValueError:
            logger.error(f"Invalid provider: {session.provider}")
            return None
        
        sso_provider = get_sso_provider(provider_type)
        
        if not sso_provider:
            logger.error(f"Provider not configured: {session.provider}")
            return None
        
        # Validate state parameter
        if not sso_provider.validate_state(state):
            logger.warning(f"Invalid state parameter: {state}")
            return None
        
        try:
            # Exchange code for tokens
            tokens = await sso_provider.exchange_code(code)
            
            # Get user info
            user_info = await sso_provider.get_user_info(tokens.access_token)
            
            # Complete session
            self.store.complete_session(
                session_id=session.session_id,
                user_id=user_info.id,
                email=user_info.email,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                id_token=tokens.id_token,
                name=user_info.name
            )
            
            # Return session data
            return {
                "session_id": session.session_id,
                "user_id": user_info.id,
                "email": user_info.email,
                "name": user_info.name,
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "id_token": tokens.id_token,
                "provider": session.provider
            }
            
        except Exception as e:
            logger.error(f"SSO callback error: {e}")
            session.status = SessionStatus.FAILED
            return None
    
    def get_session(self, session_id: str) -> Optional[SSOSession]:
        """Get session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session or None
        """
        return self.store.get_session_by_id(session_id)
    
    def revoke_session(self, session_id: str) -> bool:
        """Revoke a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if revoked
        """
        return self.store.revoke_session(session_id)
    
    def start_cleanup_task(self):
        """Start periodic cleanup of expired sessions."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def _cleanup_loop(self):
        """Periodic cleanup loop."""
        while True:
            await asyncio.sleep(60)  # Every minute
            try:
                self.store.cleanup_expired()
            except Exception as e:
                logger.error(f"Session cleanup error: {e}")


# ─── Factory Functions ───────────────────────────────────────────────────────────

_session_manager: Optional[SSOSessionManager] = None


def get_sso_session_manager() -> SSOSessionManager:
    """Get or create the global SSO session manager."""
    global _session_manager
    
    if _session_manager is None:
        _session_manager = SSOSessionManager()
    
    return _session_manager


def create_sso_session(provider: str, redirect_uri: str, scope: List[str] = None) -> Dict:
    """Convenience function to start SSO flow."""
    return asyncio.run(get_sso_session_manager().start_auth_flow(provider, redirect_uri, scope))


def validate_sso_session(session_id: str) -> bool:
    """Convenience function to validate session."""
    session = get_sso_session_manager().get_session(session_id)
    return session is not None and session.status in [SessionStatus.AUTHENTICATED, SessionStatus.ACTIVE]
