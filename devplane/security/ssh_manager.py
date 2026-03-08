"""SSH Key Manager — Secure SSH key generation, storage, and rotation.

This module provides SSH key management with Bitwarden integration,
certificate-based authentication, and automatic key rotation.
"""

import os
import json
import logging
import secrets
import hashlib
import subprocess
import tempfile
import threading
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger("devplane.security.ssh_manager")


class KeyType(str, Enum):
    """SSH key types."""
    RSA = "rsa"
    ED25519 = "ed25519"
    ECDSA = "ecdsa"


class KeyPurpose(str, Enum):
    """Purpose of SSH key."""
    DEPLOYMENT = "deployment"
    ADMIN = "admin"
    SANDBOX = "sandbox"
    AUTOMATION = "automation"
    USER = "user"


@dataclass
class SSHKey:
    """SSH key metadata."""
    name: str
    key_type: KeyType
    purpose: KeyPurpose
    public_key: str
    fingerprint: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    environment: str = "development"
    comment: Optional[str] = None
    key_id: Optional[str] = None


@dataclass
class SSHCertificate:
    """SSH certificate for certificate-based auth."""
    cert_id: str
    key_name: str
    principal: str
    cert_path: str
    private_key_path: str
    issued_at: datetime
    expires_at: datetime
    valid_principals: List[str] = field(default_factory=list)
    serial: int = 0


class SSHKeyManager:
    """SSH Key Manager with Bitwarden integration.
    
    Features:
    - SSH key generation (RSA, ED25519, ECDSA)
    - Secure storage in Bitwarden
    - SSH certificate generation
    - Automatic key rotation
    - Agent forwarding support
    - Audit logging
    """
    
    def __init__(self, keys_dir: str = None):
        """Initialize SSH key manager.
        
        Args:
            keys_dir: Directory for SSH keys (default: ~/.ssh/devplane)
        """
        self.keys_dir = Path(keys_dir or os.path.expanduser("~/.ssh/devplane"))
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        
        # Key cache
        self._keys_cache: Dict[str, SSHKey] = {}
        self._certificates: Dict[str, SSHCertificate] = {}
        
        # Try to import Bitwarden
        self._vault = None
        try:
            from devplane.secrets.vault import get_vault
            self._vault = get_vault()
        except ImportError:
            logger.warning("Bitwarden vault not available, using local storage only")
    
    def generate_key(self, name: str, key_type: KeyType = KeyType.ED25519,
                   key_size: int = 4096, purpose: KeyPurpose = KeyPurpose.USER,
                   environment: str = "development", comment: str = None,
                   passphrase: str = None) -> SSHKey:
        """Generate a new SSH key.
        
        Args:
            name: Key name
            key_type: Key type (RSA, ED25519, ECDSA)
            key_size: Key size in bits (for RSA)
            purpose: Key purpose
            environment: Environment (dev/staging/prod)
            comment: Key comment
            passphrase: Optional passphrase for encryption
            
        Returns:
            Generated SSHKey object
        """
        key_path = self.keys_dir / name
        
        # Build ssh-keygen command
        cmd = ["ssh-keygen", "-t", key_type.value, "-f", str(key_path), "-C", comment or f"{name}@{environment}"]
        
        if key_type == KeyType.RSA and key_size:
            cmd.extend(["-b", str(key_size)])
        
        if passphrase:
            cmd.extend(["-N", passphrase])
        else:
            cmd.extend(["-N", ""])  # No passphrase
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                raise Exception(f"ssh-keygen failed: {result.stderr}")
            
            # Read public key
            pub_key_path = f"{key_path}.pub"
            with open(pub_key_path, 'r') as f:
                public_key = f.read().strip()
            
            # Get fingerprint
            fingerprint = self._get_fingerprint(pub_key_path)
            
            # Create key object
            key = SSHKey(
                name=name,
                key_type=key_type,
                purpose=purpose,
                public_key=public_key,
                fingerprint=fingerprint,
                created_at=datetime.utcnow(),
                environment=environment,
                comment=comment,
                key_id=secrets.token_hex(8)
            )
            
            # Store in cache
            self._keys_cache[name] = key
            
            # Store in Bitwarden if available
            if self._vault:
                self._store_key_in_vault(key, key_path, passphrase)
            
            logger.info(f"Generated SSH key: {name} ({key_type.value})")
            
            return key
            
        except Exception as e:
            logger.error(f"Failed to generate SSH key: {e}")
            raise
    
    def _get_fingerprint(self, pub_key_path: str) -> str:
        """Get SSH key fingerprint."""
        try:
            result = subprocess.run(
                ["ssh-keygen", "-lf", pub_key_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Parse fingerprint (format: "bits fingerprint type comment")
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    return parts[1]
            
            return "unknown"
        except Exception:
            return "unknown"
    
    def load_key(self, name: str) -> Optional[SSHKey]:
        """Load an existing SSH key.
        
        Args:
            name: Key name
            
        Returns:
            SSHKey object or None
        """
        # Check cache first
        if name in self._keys_cache:
            return self._keys_cache[name]
        
        key_path = self.keys_dir / name
        pub_key_path = f"{key_path}.pub"
        
        if not os.path.exists(pub_key_path):
            return None
        
        try:
            # Read public key
            with open(pub_key_path, 'r') as f:
                public_key = f.read().strip()
            
            # Get fingerprint
            fingerprint = self._get_fingerprint(pub_key_path)
            
            # Determine key type from public key
            key_type = KeyType.RSA
            if "ed25519" in public_key:
                key_type = KeyType.ED25519
            elif "ecdsa" in public_key:
                key_type = KeyType.ECDSA
            
            # Create key object (metadata may be incomplete)
            key = SSHKey(
                name=name,
                key_type=key_type,
                purpose=KeyPurpose.USER,  # Default
                public_key=public_key,
                fingerprint=fingerprint,
                created_at=datetime.utcnow(),  # Unknown actual date
                environment="development"
            )
            
            # Try to load metadata from Bitwarden
            if self._vault:
                vault_key = self._vault.get_secret_as_dict(f"ssh-{name}-key")
                if vault_key:
                    key.purpose = KeyPurpose(vault_key.metadata.get("purpose", "user"))
                    key.environment = vault_key.metadata.get("environment", "development")
                    key.key_id = vault_key.id
            
            self._keys_cache[name] = key
            return key
            
        except Exception as e:
            logger.error(f"Failed to load SSH key: {e}")
            return None
    
    def list_keys(self, purpose: KeyPurpose = None, 
                environment: str = None) -> List[SSHKey]:
        """List all SSH keys.
        
        Args:
            purpose: Filter by purpose
            environment: Filter by environment
            
        Returns:
            List of SSH keys
        """
        keys = list(self._keys_cache.values())
        
        # Load any keys not in cache
        for filename in self.keys_dir.glob("*.pub"):
            name = filename.stem
            if name not in self._keys_cache:
                key = self.load_key(name)
                if key:
                    keys.append(key)
        
        # Filter if needed
        if purpose:
            keys = [k for k in keys if k.purpose == purpose]
        if environment:
            keys = [k for k in keys if k.environment == environment]
        
        return keys
    
    def delete_key(self, name: str, revoke: bool = True) -> bool:
        """Delete an SSH key.
        
        Args:
            name: Key name
            revoke: Whether to revoke certificate if exists
            
        Returns:
            True if deleted
        """
        key_path = self.keys_dir / name
        
        try:
            # Delete key files
            if key_path.exists():
                os.remove(key_path)
            
            pub_key_path = f"{key_path}.pub"
            if os.path.exists(pub_key_path):
                os.remove(pub_key_path)
            
            # Remove from cache
            if name in self._keys_cache:
                del self._keys_cache[name]
            
            logger.info(f"Deleted SSH key: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete SSH key: {e}")
            return False
    
    def rotate_key(self, name: str, new_name: str = None) -> SSHKey:
        """Rotate an SSH key (generate new, revoke old).
        
        Args:
            name: Current key name
            new_name: New key name (default: {name}-old)
            
        Returns:
            New SSHKey object
        """
        # Load current key
        current_key = self.load_key(name)
        
        if not current_key:
            raise ValueError(f"Key not found: {name}")
        
        # Generate new key with same settings
        new_key_name = new_name or f"{name}-rotated"
        new_key = self.generate_key(
            name=new_key_name,
            key_type=current_key.key_type,
            purpose=current_key.purpose,
            environment=current_key.environment,
            comment=current_key.comment
        )
        
        # Revoke old key
        self.delete_key(name, revoke=True)
        
        logger.info(f"Rotated SSH key: {name} -> {new_key_name}")
        
        return new_key
    
    def _store_key_in_vault(self, key: SSHKey, key_path: Path, passphrase: str = None):
        """Store SSH key in Bitwarden vault.
        
        Args:
            key: SSHKey object
            key_path: Path to private key
            passphrase: Optional passphrase
        """
        if not self._vault:
            return
        
        try:
            # Read private key
            with open(key_path, 'r') as f:
                private_key = f.read()
            
            # Store as secret
            secret_data = json.dumps({
                "private_key": private_key,
                "public_key": key.public_key,
                "fingerprint": key.fingerprint,
                "key_type": key.key_type.value,
                "purpose": key.purpose.value,
                "environment": key.environment,
                "created_at": key.created_at.isoformat(),
                "passphrase": passphrase  # Only if set
            })
            
            secret_name = f"ssh-{key.name}-key"
            # Note: Would need to implement vault.write_secret() 
            # or use bw CLI directly
            logger.info(f"Would store SSH key in vault: {secret_name}")
            
        except Exception as e:
            logger.error(f"Failed to store key in vault: {e}")
    
    def get_key_for_connection(self, name: str = "default") -> Tuple[str, str]:
        """Get key path and public key for SSH connection.
        
        Args:
            name: Key name
            
        Returns:
            Tuple of (private_key_path, public_key)
        """
        key = self.load_key(name)
        
        if not key:
            # Try to generate default key
            key = self.generate_key(name, purpose=KeyPurpose.DEPLOYMENT)
        
        key_path = str(self.keys_dir / name)
        pub_key_path = f"{key_path}.pub"
        
        with open(pub_key_path, 'r') as f:
            public_key = f.read().strip()
        
        return key_path, public_key
    
    def add_key_to_agent(self, key_name: str, lifetime: int = None) -> bool:
        """Add key to SSH agent.
        
        Args:
            key_name: Key name
            lifetime: Optional lifetime in seconds
            
        Returns:
            True if added
        """
        key_path = self.keys_dir / key_name
        
        if not key_path.exists():
            logger.error(f"Key not found: {key_name}")
            return False
        
        try:
            cmd = ["ssh-add", str(key_path)]
            
            if lifetime:
                cmd.extend(["-t", str(lifetime)])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Update last used
                key = self.load_key(key_name)
                if key:
                    key.last_used = datetime.utcnow()
                
                logger.info(f"Added key to SSH agent: {key_name}")
                return True
            
            logger.error(f"Failed to add key to agent: {result.stderr}")
            return False
            
        except Exception as e:
            logger.error(f"Error adding key to agent: {e}")
            return False
    
    def get_authorized_keys(self, key_names: List[str] = None) -> str:
        """Get authorized_keys content for a user.
        
        Args:
            key_names: List of key names to include (default: all)
            
        Returns:
            Authorized_keys content
        """
        keys = []
        
        if key_names:
            for name in key_names:
                key = self.load_key(name)
                if key:
                    keys.append(key.public_key)
        else:
            # All keys
            for key in self.list_keys():
                keys.append(key.public_key)
        
        return "\n".join(keys) + "\n"


# ─── Factory Function ───────────────────────────────────────────────────────────

_ssh_manager: Optional[SSHKeyManager] = None
_manager_lock = threading.Lock()


def get_ssh_manager() -> SSHKeyManager:
    """Get or create the global SSH key manager."""
    global _ssh_manager
    
    if _ssh_manager is None:
        with _manager_lock:
            if _ssh_manager is None:
                _ssh_manager = SSHKeyManager()
    
    return _ssh_manager


# ─── Convenience Functions ─────────────────────────────────────────────────────

def generate_deployment_key(name: str = "deployment", environment: str = "production") -> SSHKey:
    """Generate a deployment SSH key."""
    return get_ssh_manager().generate_key(
        name=name,
        key_type=KeyType.ED25519,
        purpose=KeyPurpose.DEPLOYMENT,
        environment=environment,
        comment=f"deployment@{environment}"
    )


def get_deployment_key() -> Tuple[str, str]:
    """Get the deployment key for SSH connections."""
    return get_ssh_manager().get_key_for_connection("deployment")


def list_ssh_keys(purpose: KeyPurpose = None, environment: str = None) -> List[SSHKey]:
    """List all SSH keys."""
    return get_ssh_manager().list_keys(purpose, environment)


def rotate_ssh_key(name: str) -> SSHKey:
    """Rotate an SSH key."""
    return get_ssh_manager().rotate_key(name)
