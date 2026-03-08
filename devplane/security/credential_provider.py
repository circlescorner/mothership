"""Credential Provider — Least Privilege Credentials Management.

This module implements the principle of least privilege for credentials:
- Role-based access control (RBAC)
- Credential scoping by environment
- Time-limited credentials
- Credential borrowing with approval workflow
- Full audit logging
"""

import os
import json
import logging
import secrets
import hashlib
import threading
from typing import Optional, Dict, List, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger("devplane.security.credential_provider")


class Role(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    OPERATOR = "operator"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    SANDBOX = "sandbox"
    AUTOMATION = "automation"


class CredentialScope(str, Enum):
    """Credential access scope."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    EXECUTE = "execute"


class CredentialType(str, Enum):
    """Types of credentials."""
    API_KEY = "api_key"
    DATABASE = "database"
    SSH_KEY = "ssh_key"
    CERTIFICATE = "certificate"
    TOKEN = "token"
    PASSWORD = "password"


@dataclass
class Credential:
    """Credential metadata."""
    id: str
    name: str
    credential_type: CredentialType
    scope: CredentialScope
    environment: str
    required_roles: Set[Role]
    required_scope: CredentialScope
    ttl_minutes: int  # Time-to-live for borrowed credentials
    max_borrow_duration: int  # Maximum borrow time in minutes
    requires_approval: bool
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    secret_path: Optional[str] = None  # Path in vault


@dataclass
class BorrowedCredential:
    """A borrowed credential with expiry."""
    credential_id: str
    borrow_id: str
    user_id: str
    borrowed_at: datetime
    expires_at: datetime
    revoked: bool = False
    approved_by: Optional[str] = None
    purpose: Optional[str] = None


@dataclass
class AccessRequest:
    """Credential access request."""
    request_id: str
    credential_id: str
    user_id: str
    requested_at: datetime
    status: str  # pending, approved, denied
    purpose: str
    duration_minutes: int
    approved_by: Optional[str] = None
    denied_by: Optional[str] = None
    denial_reason: Optional[str] = None


class RBACManager:
    """Role-Based Access Control Manager.
    
    Manages user roles and permissions for credential access.
    """
    
    def __init__(self):
        self._roles: Dict[str, Set[Role]] = defaultdict(set)
        self._role_permissions: Dict[Role, Dict[CredentialType, Set[CredentialScope]]] = {}
        self._init_default_permissions()
    
    def _init_default_permissions(self):
        """Initialize default role permissions."""
        # Admin: Full access to everything
        self._role_permissions[Role.ADMIN] = {
            ct: {CredentialScope.READ, CredentialScope.WRITE, CredentialScope.ADMIN, CredentialScope.EXECUTE}
            for ct in CredentialType
        }
        
        # Operator: Read/Write to most, no admin
        self._role_permissions[Role.OPERATOR] = {
            CredentialType.API_KEY: {CredentialScope.READ, CredentialScope.WRITE, CredentialScope.EXECUTE},
            CredentialType.DATABASE: {CredentialScope.READ, CredentialScope.WRITE, CredentialScope.EXECUTE},
            CredentialType.SSH_KEY: {CredentialScope.READ, CredentialScope.WRITE, CredentialScope.EXECUTE},
            CredentialType.CERTIFICATE: {CredentialScope.READ, CredentialScope.WRITE},
            CredentialType.TOKEN: {CredentialScope.READ, CredentialScope.WRITE, CredentialScope.EXECUTE},
            CredentialType.PASSWORD: {CredentialScope.READ, CredentialScope.WRITE},
        }
        
        # Developer: Read access, limited write
        self._role_permissions[Role.DEVELOPER] = {
            CredentialType.API_KEY: {CredentialScope.READ},
            CredentialType.DATABASE: {CredentialScope.READ},
            CredentialType.SSH_KEY: {CredentialScope.READ},
            CredentialType.CERTIFICATE: {CredentialScope.READ},
            CredentialType.TOKEN: {CredentialScope.READ},
            CredentialType.PASSWORD: {CredentialScope.READ},
        }
        
        # Viewer: Read-only access to non-sensitive
        self._role_permissions[Role.VIEWER] = {
            CredentialType.CERTIFICATE: {CredentialScope.READ},
        }
        
        # Sandbox: Limited to sandbox-specific resources
        self._role_permissions[Role.SANDBOX] = {
            CredentialType.API_KEY: {CredentialScope.EXECUTE},
            CredentialType.SSH_KEY: {CredentialScope.EXECUTE},
        }
        
        # Automation: Execute-only for specific tasks
        self._role_permissions[Role.AUTOMATION] = {
            CredentialType.API_KEY: {CredentialScope.EXECUTE},
            CredentialType.SSH_KEY: {CredentialScope.EXECUTE},
            CredentialType.TOKEN: {CredentialScope.EXECUTE},
        }
    
    def assign_role(self, user_id: str, role: Role):
        """Assign a role to a user."""
        self._roles[user_id].add(role)
        logger.info(f"Assigned role {role.value} to user {user_id}")
    
    def remove_role(self, user_id: str, role: Role):
        """Remove a role from a user."""
        self._roles[user_id].discard(role)
        logger.info(f"Removed role {role.value} from user {user_id}")
    
    def get_user_roles(self, user_id: str) -> Set[Role]:
        """Get all roles for a user."""
        return self._roles.get(user_id, set())
    
    def has_permission(self, user_id: str, credential_type: CredentialType, 
                      required_scope: CredentialScope) -> bool:
        """Check if user has permission for a credential."""
        user_roles = self.get_user_roles(user_id)
        
        for role in user_roles:
            permissions = self._role_permissions.get(role, {})
            scopes = permissions.get(credential_type, set())
            
            if required_scope in scopes:
                return True
        
        return False


class CredentialProvider:
    """Least Privilege Credential Provider.
    
    Features:
    - RBAC for credential access
    - Environment scoping
    - Time-limited credential borrowing
    - Approval workflow for sensitive credentials
    - Full audit logging
    """
    
    def __init__(self):
        self._credentials: Dict[str, Credential] = {}
        self._borrowed: Dict[str, BorrowedCredential] = {}
        self._requests: Dict[str, AccessRequest] = {}
        self._audit_log: List[Dict] = []
        self._audit_lock = threading.Lock()
        self._rbac = RBACManager()
        
        # Initialize default credentials
        self._init_default_credentials()
    
    def _init_default_credentials(self):
        """Initialize default credential definitions."""
        default_credentials = [
            Credential(
                id="api-openrouter",
                name="OpenRouter API Key",
                credential_type=CredentialType.API_KEY,
                scope=CredentialScope.EXECUTE,
                environment="production",
                required_roles={Role.ADMIN, Role.OPERATOR, Role.AUTOMATION},
                required_scope=CredentialScope.EXECUTE,
                ttl_minutes=60,
                max_borrow_duration=60,
                requires_approval=False,
                description="OpenRouter API for LLM calls",
                secret_path="production/openrouter-api-key"
            ),
            Credential(
                id="api-together",
                name="TogetherAI API Key",
                credential_type=CredentialType.API_KEY,
                scope=CredentialScope.EXECUTE,
                environment="production",
                required_roles={Role.ADMIN, Role.OPERATOR, Role.AUTOMATION},
                required_scope=CredentialScope.EXECUTE,
                ttl_minutes=60,
                max_borrow_duration=60,
                requires_approval=False,
                description="TogetherAI API for LLM calls",
                secret_path="production/together-api-key"
            ),
            Credential(
                id="api-deepseek",
                name="DeepSeek API Key",
                credential_type=CredentialType.API_KEY,
                scope=CredentialScope.EXECUTE,
                environment="production",
                required_roles={Role.ADMIN, Role.OPERATOR, Role.AUTOMATION},
                required_scope=CredentialScope.EXECUTE,
                ttl_minutes=60,
                max_borrow_duration=60,
                requires_approval=False,
                description="DeepSeek API for LLM calls",
                secret_path="production/deepseek-api-key"
            ),
            Credential(
                id="db-primary",
                name="Primary Database Credentials",
                credential_type=CredentialType.DATABASE,
                scope=CredentialScope.WRITE,
                environment="production",
                required_roles={Role.ADMIN, Role.OPERATOR},
                required_scope=CredentialScope.WRITE,
                ttl_minutes=30,
                max_borrow_duration=30,
                requires_approval=True,
                description="Production database primary credentials"
            ),
            Credential(
                id="ssh-deployment",
                name="Deployment SSH Key",
                credential_type=CredentialType.SSH_KEY,
                scope=CredentialScope.EXECUTE,
                environment="production",
                required_roles={Role.ADMIN, Role.OPERATOR, Role.AUTOMATION},
                required_scope=CredentialScope.EXECUTE,
                ttl_minutes=120,
                max_borrow_duration=120,
                requires_approval=False,
                description="SSH key for deployment"
            ),
        ]
        
        for cred in default_credentials:
            self._credentials[cred.id] = cred
    
    def register_credential(self, credential: Credential):
        """Register a new credential."""
        self._credentials[credential.id] = credential
        self._audit("register", credential.id, "system", True, 
                   f"Registered credential: {credential.name}")
    
    def list_credentials(self, user_id: str = None, 
                        environment: str = None,
                        credential_type: CredentialType = None) -> List[Credential]:
        """List available credentials (filtered by permissions)."""
        credentials = []
        
        for cred in self._credentials.values():
            # Filter by environment
            if environment and cred.environment != environment:
                continue
            
            # Filter by type
            if credential_type and cred.credential_type != credential_type:
                continue
            
            # Filter by permissions if user provided
            if user_id:
                if not self.can_access(user_id, cred.id):
                    continue
            
            credentials.append(cred)
        
        return credentials
    
    def can_access(self, user_id: str, credential_id: str) -> bool:
        """Check if user can access a credential."""
        cred = self._credentials.get(credential_id)
        
        if not cred:
            return False
        
        user_roles = self._rbac.get_user_roles(user_id)
        
        # Check if user has required role
        if not user_roles.intersection(cred.required_roles):
            return False
        
        # Check if user has required scope
        return self._rbac.has_permission(user_id, cred.credential_type, cred.required_scope)
    
    def borrow_credential(self, user_id: str, credential_id: str, 
                        purpose: str, duration_minutes: int = None) -> Optional[BorrowedCredential]:
        """Borrow a credential for temporary use."""
        cred = self._credentials.get(credential_id)
        
        if not cred:
            self._audit("borrow", credential_id, user_id, False, "Credential not found")
            return None
        
        # Check permissions
        if not self.can_access(user_id, credential_id):
            self._audit("borrow", credential_id, user_id, False, "Permission denied")
            return None
        
        # Check if approval is required
        if cred.requires_approval:
            # Create approval request instead
            request = self.request_access(user_id, credential_id, purpose, duration_minutes)
            if request:
                self._audit("borrow", credential_id, user_id, False, 
                           f"Approval required: {request.request_id}")
            return None
        
        # Determine duration
        duration = duration_minutes or cred.ttl_minutes
        duration = min(duration, cred.max_borrow_duration)
        
        # Create borrowed credential
        borrow_id = secrets.token_hex(8)
        borrowed = BorrowedCredential(
            credential_id=credential_id,
            borrow_id=borrow_id,
            user_id=user_id,
            borrowed_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=duration),
            purpose=purpose
        )
        
        self._borrowed[borrow_id] = borrowed
        
        self._audit("borrow", credential_id, user_id, True, 
                   f"Borrowed for {duration} minutes: {purpose}")
        
        logger.info(f"User {user_id} borrowed credential {credential_id} for {duration} minutes")
        
        return borrowed
    
    def get_borrowed_credential(self, borrow_id: str) -> Optional[BorrowedCredential]:
        """Get a borrowed credential."""
        borrowed = self._borrowed.get(borrow_id)
        
        if not borrowed:
            return None
        
        # Check if expired
        if datetime.utcnow() > borrowed.expires_at:
            return None
        
        # Check if revoked
        if borrowed.revoked:
            return None
        
        return borrowed
    
    def revoke_borrowed(self, borrow_id: str, revoked_by: str = None) -> bool:
        """Revoke a borrowed credential."""
        borrowed = self._borrowed.get(borrow_id)
        
        if not borrowed:
            return False
        
        borrowed.revoked = True
        
        self._audit("revoke", borrowed.credential_id, borrowed.user_id, True,
                   f"Revoked by {revoked_by or 'system'}")
        
        return True
    
    def request_access(self, user_id: str, credential_id: str,
                     purpose: str, duration_minutes: int = None) -> Optional[AccessRequest]:
        """Request access to a credential (requires approval)."""
        cred = self._credentials.get(credential_id)
        
        if not cred or not cred.requires_approval:
            return None
        
        # Check basic permissions
        user_roles = self._rbac.get_user_roles(user_id)
        if not user_roles.intersection(cred.required_roles):
            return None
        
        request_id = secrets.token_hex(8)
        duration = duration_minutes or cred.ttl_minutes
        
        request = AccessRequest(
            request_id=request_id,
            credential_id=credential_id,
            user_id=user_id,
            requested_at=datetime.utcnow(),
            status="pending",
            purpose=purpose,
            duration_minutes=duration
        )
        
        self._requests[request_id] = request
        
        self._audit("request", credential_id, user_id, True,
                   f"Access requested for {duration} minutes")
        
        return request
    
    def approve_request(self, request_id: str, approved_by: str) -> bool:
        """Approve an access request."""
        request = self._requests.get(request_id)
        
        if not request or request.status != "pending":
            return False
        
        # Approve and borrow
        request.status = "approved"
        request.approved_by = approved_by
        
        # Create borrowed credential
        borrowed = self.borrow_credential(
            request.user_id,
            request.credential_id,
            request.purpose,
            request.duration_minutes
        )
        
        if borrowed:
            self._audit("approve", request.credential_id, request.user_id, True,
                       f"Approved by {approved_by}")
            return True
        
        return False
    
    def deny_request(self, request_id: str, denied_by: str, reason: str):
        """Deny an access request."""
        request = self._requests.get(request_id)
        
        if not request or request.status != "pending":
            return False
        
        request.status = "denied"
        request.denied_by = denied_by
        request.denial_reason = reason
        
        self._audit("deny", request.credential_id, request.user_id, True,
                   f"Denied by {denied_by}: {reason}")
        
        return True
    
    def get_pending_requests(self, approver_id: str = None) -> List[AccessRequest]:
        """Get pending access requests."""
        requests = [r for r in self._requests.values() if r.status == "pending"]
        
        # If approver_id provided, filter to their credentials
        if approver_id:
            # For now, admins can approve all
            pass
        
        return requests
    
    def _audit(self, action: str, credential_id: str, user_id: str, 
              success: bool, details: str = None):
        """Log an audit entry."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "credential_id": credential_id,
            "user_id": user_id,
            "success": success,
            "details": details
        }
        
        with self._audit_lock:
            self._audit_log.append(entry)
            
            # Keep last 10000 entries
            if len(self._audit_log) > 10000:
                self._audit_log = self._audit_log[-10000:]
    
    def get_audit_log(self, user_id: str = None, 
                     credential_id: str = None,
                     limit: int = 100) -> List[Dict]:
        """Get audit log entries."""
        entries = self._audit_log[-limit:]
        
        if user_id:
            entries = [e for e in entries if e.get("user_id") == user_id]
        
        if credential_id:
            entries = [e for e in entries if e.get("credential_id") == credential_id]
        
        return entries
    
    def cleanup_expired(self) -> int:
        """Clean up expired borrowed credentials."""
        now = datetime.utcnow()
        expired = []
        
        for borrow_id, borrowed in self._borrowed.items():
            if now > borrowed.expires_at:
                expired.append(borrow_id)
        
        for borrow_id in expired:
            del self._borrowed[borrow_id]
        
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired borrowed credentials")
        
        return len(expired)
    
    # ─── RBAC Methods ─────────────────────────────────────────────────────────────
    
    def assign_role(self, user_id: str, role: Role):
        """Assign a role to a user."""
        self._rbac.assign_role(user_id, role)
    
    def remove_role(self, user_id: str, role: Role):
        """Remove a role from a user."""
        self._rbac.remove_role(user_id, role)
    
    def get_user_roles(self, user_id: str) -> Set[Role]:
        """Get user roles."""
        return self._rbac.get_user_roles(user_id)


# ─── Factory Function ───────────────────────────────────────────────────────────

_credential_provider: Optional[CredentialProvider] = None
_provider_lock = threading.Lock()


def get_credential_provider() -> CredentialProvider:
    """Get or create the global credential provider."""
    global _credential_provider
    
    if _credential_provider is None:
        with _provider_lock:
            if _credential_provider is None:
                _credential_provider = CredentialProvider()
    
    return _credential_provider


# ─── Convenience Functions ─────────────────────────────────────────────────────

def can_access_credential(user_id: str, credential_id: str) -> bool:
    """Check if user can access a credential."""
    return get_credential_provider().can_access(user_id, credential_id)


def borrow_credential(user_id: str, credential_id: str, 
                     purpose: str, duration: int = None) -> Optional[BorrowedCredential]:
    """Borrow a credential."""
    return get_credential_provider().borrow_credential(user_id, credential_id, purpose, duration)


def get_credential(borrow_id: str) -> Optional[BorrowedCredential]:
    """Get a borrowed credential."""
    return get_credential_provider().get_borrowed_credential(borrow_id)


def assign_role(user_id: str, role: Role):
    """Assign a role to a user."""
    get_credential_provider().assign_role(user_id, role)


def get_audit_log(limit: int = 100) -> List[Dict]:
    """Get audit log."""
    return get_credential_provider().get_audit_log(limit=limit)
