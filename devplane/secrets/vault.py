"""Bitwarden Vault Integration — Secure secrets retrieval from Bitwarden.

This module provides a secure interface to Bitwarden CLI (bw) for programmatic
secret retrieval. All secrets are retrieved at runtime from the Bitwarden vault,
never stored in code or configuration files.

Usage:
    from devplane.secrets.vault import BitwardenVault, get_vault
    
    vault = get_vault()
    api_key = vault.get_secret("openrouter-api-key")
"""

import os
import json
import subprocess
import logging
import hashlib
import threading
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("devplane.secrets.vault")


class SecretType(str, Enum):
    """Types of secrets stored in the vault."""
    API_KEY = "api_key"
    PASSWORD = "password"
    SSH_KEY = "ssh_key"
    CERTIFICATE = "certificate"
    TOKEN = "token"
    DATABASE = "database"
    NOTE = "note"


class SecretEnvironment(str, Enum):
    """Environment scoping for secrets."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    SANDBOX = "sandbox"


@dataclass
class VaultSecret:
    """Represents a secret retrieved from the vault."""
    id: str
    name: str
    value: str
    secret_type: SecretType
    environment: SecretEnvironment
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    notes: Optional[str] = None
    expires_at: Optional[str] = None


@dataclass
class AuditEntry:
    """Audit log entry for secret access."""
    timestamp: str
    secret_name: str
    action: str
    user: str
    success: bool
    details: Optional[str] = None


class BitwardenVault:
    """Bitwarden CLI wrapper for secret management.
    
    Implements:
    - Bitwarden CLI integration
    - Session caching with automatic lock
    - Secret sync and environment injection
    - Full audit logging
    - Timeout protection (30s max)
    """
    
    def __init__(self, vault_url: str = "https://vault.bitwarden.com"):
        """Initialize the Bitwarden vault.
        
        Args:
            vault_url: Bitwarden vault URL (default: bitwarden.com)
        """
        self.vault_url = vault_url
        self._session = None
        self._session_lock = threading.Lock()
        self._session_expiry: Optional[datetime] = None
        self._audit_log: List[AuditEntry] = []
        self._audit_lock = threading.Lock()
        
        # Configuration from environment
        self._master_password = os.environ.get("BITWARDEN_MASTER_PASSWORD")
        self._organization_id = os.environ.get("BITWARDEN_ORG_ID")
        self._client_id = os.environ.get("BITWARDEN_CLIENT_ID")
        self._client_secret = os.environ.get("BITWARDEN_CLIENT_SECRET")
        
        # Check if vault is configured
        self._configured = bool(self._master_password or 
                              (self._client_id and self._client_secret))
    
    @property
    def is_configured(self) -> bool:
        """Check if vault is properly configured."""
        return self._configured
    
    def _run_bw_command(self, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a Bitwarden CLI command with timeout protection.
        
        Args:
            args: Command arguments (without 'bw')
            timeout: Command timeout in seconds (default: 30)
            
        Returns:
            CompletedProcess result
        """
        cmd = ["bw"] + args
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "BW_SESSION": self._session} if self._session else os.environ
            )
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Bitwarden command timed out after {timeout}s: {' '.join(args)}")
            raise TimeoutError(f"Bitwarden command timed out: {' '.join(args)}")
        except FileNotFoundError:
            logger.error("Bitwarden CLI (bw) not found. Install with: npm install -g @bitwarden/cli")
            raise RuntimeError("Bitwarden CLI not installed")
    
    def _log_audit(self, secret_name: str, action: str, success: bool, details: str = None):
        """Log secret access for audit purposes."""
        entry = AuditEntry(
            timestamp=datetime.utcnow().isoformat(),
            secret_name=secret_name,
            action=action,
            user=os.environ.get("USER", "unknown"),
            success=success,
            details=details
        )
        
        with self._audit_lock:
            self._audit_log.append(entry)
            # Keep only last 1000 entries in memory
            if len(self._audit_log) > 1000:
                self._audit_log = self._audit_log[-1000:]
    
    def unlock(self, password: Optional[str] = None) -> bool:
        """Unlock the vault with master password or API key.
        
        Args:
            password: Master password (or uses BITWARDEN_MASTER_PASSWORD env)
            
        Returns:
            True if unlocked successfully
        """
        if not self._configured:
            logger.warning("Bitwarden vault not configured")
            return False
        
        with self._session_lock:
            # Check if already unlocked
            if self._session and self._session_expiry and datetime.now() < self._session_expiry:
                return True
            
            pwd = password or self._master_password
            if not pwd:
                logger.error("No master password provided")
                return False
            
            try:
                # Try to unlock with master password
                result = self._run_bw_command(["unlock", pwd, "--response"])
                
                if result.returncode == 0:
                    # Parse session token from output
                    try:
                        data = json.loads(result.stdout.strip())
                        self._session = data.get("data")
                        self._session_expiry = datetime.now() + timedelta(minutes=30)
                        self._log_audit("vault", "unlock", True, "Vault unlocked successfully")
                        logger.info("Bitwarden vault unlocked")
                        return True
                    except json.JSONDecodeError:
                        # Fallback: session might be in stdout directly
                        self._session = result.stdout.strip()
                        self._session_expiry = datetime.now() + timedelta(minutes=30)
                        return True
                else:
                    self._log_audit("vault", "unlock", False, result.stderr)
                    logger.error(f"Failed to unlock vault: {result.stderr}")
                    return False
                    
            except Exception as e:
                self._log_audit("vault", "unlock", False, str(e))
                logger.error(f"Vault unlock error: {e}")
                return False
    
    def lock(self):
        """Lock the vault and clear session."""
        with self._session_lock:
            if self._session:
                self._run_bw_command(["lock"], timeout=10)
            self._session = None
            self._session_expiry = None
            self._log_audit("vault", "lock", True)
            logger.info("Bitwarden vault locked")
    
    def sync(self) -> bool:
        """Sync vault with server.
        
        Returns:
            True if sync successful
        """
        if not self._session:
            logger.warning("Cannot sync: vault not unlocked")
            return False
        
        try:
            result = self._run_bw_command(["sync"], timeout=60)
            success = result.returncode == 0
            self._log_audit("vault", "sync", success)
            return success
        except Exception as e:
            logger.error(f"Vault sync error: {e}")
            return False
    
    def get_secret(self, secret_name: str, environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT) -> Optional[str]:
        """Retrieve a secret by name from the vault.
        
        Args:
            secret_name: Name of the secret (matches 'name' field in Bitwarden)
            environment: Environment scope (development/staging/production/sandbox)
            
        Returns:
            Secret value or None if not found
        """
        if not self._session:
            if not self.unlock():
                return None
        
        # Build search query - use folder/collection prefix for environment scoping
        # Format: {environment}/{secret_name} or just secret_name
        search_name = f"{environment.value}/{secret_name}" if environment != SecretEnvironment.DEVELOPMENT else secret_name
        
        try:
            # List items and find matching one
            result = self._run_bw_command(["list", "items", "--search", secret_name], timeout=30)
            
            if result.returncode != 0:
                self._log_audit(secret_name, "get", False, "Failed to list items")
                return None
            
            try:
                items = json.loads(result.stdout)
            except json.JSONDecodeError:
                self._log_audit(secret_name, "get", False, "Invalid JSON response")
                return None
            
            # Find the matching item
            matched_item = None
            for item in items:
                # Match by name, considering environment prefix
                item_name = item.get("name", "")
                if item_name == search_name or item_name == secret_name:
                    matched_item = item
                    break
            
            if not matched_item:
                # Try without environment prefix
                for item in items:
                    if secret_name.lower() in item.get("name", "").lower():
                        matched_item = item
                        break
            
            if not matched_item:
                self._log_audit(secret_name, "get", False, "Secret not found")
                logger.warning(f"Secret not found: {secret_name}")
                return None
            
            # Get the secret value
            item_id = matched_item.get("id")
            result = self._run_bw_command(["get", "item", item_id], timeout=30)
            
            if result.returncode != 0:
                self._log_audit(secret_name, "get", False, "Failed to get item")
                return None
            
            try:
                item_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                self._log_audit(secret_name, "get", False, "Invalid item JSON")
                return None
            
            # Extract secret value from login or secure note
            value = None
            if item_data.get("login"):
                value = item_data["login"].get("password") or item_data["login"].get("username")
            elif item_data.get("secureNote"):
                value = item_data["secureNote"].get("notes")
            elif item_data.get("card"):
                value = json.dumps(item_data["card"])
            
            if value:
                self._log_audit(secret_name, "get", True, f"Environment: {environment.value}")
                logger.info(f"Retrieved secret: {secret_name} ({environment.value})")
                return value
            
            self._log_audit(secret_name, "get", False, "No value found in item")
            return None
            
        except Exception as e:
            self._log_audit(secret_name, "get", False, str(e))
            logger.error(f"Error retrieving secret {secret_name}: {e}")
            return None
    
    def get_secret_as_dict(self, secret_name: str, environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT) -> Optional[Dict]:
        """Retrieve a secret as a dictionary with metadata.
        
        Args:
            secret_name: Name of the secret
            environment: Environment scope
            
        Returns:
            VaultSecret object or None
        """
        if not self._session:
            if not self.unlock():
                return None
        
        try:
            result = self._run_bw_command(["list", "items", "--search", secret_name], timeout=30)
            
            if result.returncode != 0:
                return None
            
            items = json.loads(result.stdout)
            
            for item in items:
                if item.get("name") == secret_name:
                    item_id = item.get("id")
                    detail_result = self._run_bw_command(["get", "item", item_id], timeout=30)
                    
                    if detail_result.returncode == 0:
                        item_data = json.loads(detail_result.stdout)
                        
                        value = None
                        secret_type = SecretType.NOTE
                        
                        if item_data.get("login"):
                            value = item_data["login"].get("password")
                            secret_type = SecretType.API_KEY if "api" in secret_name.lower() else SecretType.PASSWORD
                        elif item_data.get("secureNote"):
                            value = item_data["secureNote"].get("notes")
                        
                        return VaultSecret(
                            id=item_id,
                            name=item.get("name"),
                            value=value or "",
                            secret_type=secret_type,
                            environment=environment,
                            created_at=item_data.get("creationDate"),
                            updated_at=item_data.get("revisionDate"),
                            notes=item_data.get("notes")
                        )
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving secret dict {secret_name}: {e}")
            return None
    
    def list_secrets(self, environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT) -> List[str]:
        """List all secret names in the vault (or filtered by environment).
        
        Args:
            environment: Environment filter
            
        Returns:
            List of secret names
        """
        if not self._session:
            if not self.unlock():
                return []
        
        try:
            result = self._run_bw_command(["list", "items"], timeout=30)
            
            if result.returncode != 0:
                return []
            
            items = json.loads(result.stdout)
            
            secrets = []
            for item in items:
                name = item.get("name", "")
                # Filter by environment prefix
                if environment.value == SecretEnvironment.DEVELOPMENT.value:
                    secrets.append(name)
                elif name.startswith(environment.value + "/"):
                    secrets.append(name.replace(environment.value + "/", ""))
            
            return secrets
            
        except Exception as e:
            logger.error(f"Error listing secrets: {e}")
            return []
    
    def inject_env_variables(self, environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT, 
                           secret_prefix: str = "DEVPLANE_") -> int:
        """Inject secrets as environment variables.
        
        This method retrieves secrets and sets them in os.environ.
        Secrets are named with prefix (e.g., DEVPLANE_OPENROUTER_API_KEY).
        
        Args:
            environment: Environment scope
            secret_prefix: Prefix for environment variable names
            
        Returns:
            Number of secrets injected
        """
        secrets = self.list_secrets(environment)
        injected = 0
        
        for secret_name in secrets:
            # Convert secret name to env var format
            env_name = secret_name.upper().replace("-", "_").replace(" ", "_")
            env_name = f"{secret_prefix}{env_name}"
            
            value = self.get_secret(secret_name, environment)
            if value:
                os.environ[env_name] = value
                injected += 1
                logger.debug(f"Injected env var: {env_name}")
        
        logger.info(f"Injected {injected} environment variables from vault")
        return injected
    
    def get_audit_log(self, limit: int = 100) -> List[AuditEntry]:
        """Get recent audit log entries.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of audit entries
        """
        with self._audit_lock:
            return self._audit_log[-limit:]
    
    def clear_audit_log(self):
        """Clear the in-memory audit log."""
        with self._audit_lock:
            self._audit_log.clear()


# ─── Factory Function ───────────────────────────────────────────────────────────

_vault_instance: Optional[BitwardenVault] = None
_vault_lock = threading.Lock()


def get_vault(vault_url: str = "https://vault.bitwarden.com") -> BitwardenVault:
    """Get or create the global Bitwarden vault instance.
    
    Args:
        vault_url: Bitwarden vault URL
        
    Returns:
        BitwardenVault instance
    """
    global _vault_instance
    
    if _vault_instance is None:
        with _vault_lock:
            if _vault_instance is None:
                _vault_instance = BitwardenVault(vault_url)
    
    return _vault_instance


def configure_vault(master_password: str = None, client_id: str = None, 
                   client_secret: str = None, organization_id: str = None):
    """Configure the vault with credentials.
    
    Args:
        master_password: Bitwarden master password
        client_id: Bitwarden client ID (for API key auth)
        client_secret: Bitwarden client secret
        organization_id: Organization ID for shared vault
    """
    vault = get_vault()
    
    if master_password:
        os.environ["BITWARDEN_MASTER_PASSWORD"] = master_password
        vault._master_password = master_password
        vault._configured = True
    
    if client_id:
        os.environ["BITWARDEN_CLIENT_ID"] = client_id
        vault._client_id = client_id
    
    if client_secret:
        os.environ["BITWARDEN_CLIENT_SECRET"] = client_secret
        vault._client_secret = client_secret
    
    if organization_id:
        os.environ["BITWARDEN_ORG_ID"] = organization_id
        vault._organization_id = organization_id


# ─── Environment Loading Pattern ─────────────────────────────────────────────────

def load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from .env file.
    
    This follows the AGENTS.md pattern for safe environment loading.
    
    Args:
        env_path: Path to .env file
    """
    if not os.path.exists(env_path):
        return
    
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key, value)


# ─── Convenience Functions ─────────────────────────────────────────────────────

def get_api_key(provider: str, environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT) -> Optional[str]:
    """Convenience function to get an API key from the vault.
    
    Args:
        provider: Provider name (e.g., "openrouter", "together", "deepseek")
        environment: Environment scope
        
    Returns:
        API key or None
    """
    vault = get_vault()
    secret_name = f"{provider}-api-key"
    return vault.get_secret(secret_name, environment)


def get_database_credential(db_name: str = "default", 
                           environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT) -> Optional[Dict]:
    """Convenience function to get database credentials.
    
    Args:
        db_name: Database name
        environment: Environment scope
        
    Returns:
        Dict with host, port, username, password or None
    """
    vault = get_vault()
    secret = vault.get_secret_as_dict(f"database-{db_name}", environment)
    
    if secret and secret.value:
        try:
            return json.loads(secret.value)
        except json.JSONDecodeError:
            return {"connection_string": secret.value}
    
    return None


def get_ssh_key(key_name: str = "default", 
               environment: SecretEnvironment = SecretEnvironment.DEVELOPMENT) -> Optional[str]:
    """Convenience function to get an SSH private key.
    
    Args:
        key_name: SSH key name
        environment: Environment scope
        
    Returns:
        SSH private key content or None
    """
    vault = get_vault()
    secret_name = f"ssh-{key_name}-key"
    return vault.get_secret(secret_name, environment)
