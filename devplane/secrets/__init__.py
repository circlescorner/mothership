"""DevPlane Secrets Module.

This module provides comprehensive secrets management with Bitwarden integration.

Components:
- vault: Bitwarden CLI integration for secure secret retrieval
"""

from devplane.secrets.vault import (
    BitwardenVault,
    VaultSecret,
    SecretType,
    SecretEnvironment,
    get_vault,
    configure_vault,
    get_api_key,
    get_database_credential,
    get_ssh_key,
    load_env_file
)

__all__ = [
    "BitwardenVault",
    "VaultSecret", 
    "SecretType",
    "SecretEnvironment",
    "get_vault",
    "configure_vault",
    "get_api_key",
    "get_database_credential",
    "get_ssh_key",
    "load_env_file"
]
