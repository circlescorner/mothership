"""
Configuration management for DevPlane using Pydantic Settings.

Loads configuration from:
1. Environment variables (highest priority)
2. Environment-specific YAML files (`config/environments/`)
3. Default values defined in Pydantic models

Also provides integration with secret managers (Vault) for sensitive values.
"""

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import Field, SecretStr, validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("devplane.core.config")


class Settings(BaseSettings):
    """Main configuration model for DevPlane."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore extra env vars
        case_sensitive=False,
    )
    
    # ==================== Environment & Deployment ====================
    ENV: str = Field(default="development", description="Runtime environment: development, staging, production")
    DEPLOYMENT_DOMAIN: str = Field(default="localhost", description="Primary domain for deployment")
    DEPLOYMENT_MODE: str = Field(default="local", description="Deployment mode: local, remote, docker")
    HOST: str = Field(default="0.0.0.0", description="Host to bind the API server")
    PORT: int = Field(default=8000, description="Port to bind the API server")
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:8000", description="Allowed CORS origins (comma-separated)")
    
    # ==================== Database ====================
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./devplane.db", description="Database connection URL")
    DEVPLANE_DB_PATH: str = Field(default="./devplane.db", description="Path to SQLite database file")
    
    # ==================== Secrets & Security ====================
    SECRET_KEY: SecretStr = Field(default="", description="Secret key for session signing and encryption")
    JWT_SECRET: SecretStr = Field(default="", description="Secret key for JWT signing")
    VAULT_MASTER_KEY: SecretStr = Field(default="", description="Master encryption key for Vault")
    
    # ==================== Cloudflare ====================
    CLOUDFLARE_API_KEY: SecretStr = Field(default="", description="Cloudflare API key (legacy)")
    CLOUDFLARE_API_TOKEN: SecretStr = Field(default="", description="Cloudflare API token (recommended)")
    CLOUDFLARE_EMAIL: str = Field(default="", description="Cloudflare account email")
    CLOUDFLARE_ACCOUNT_ID: str = Field(default="", description="Cloudflare account ID")
    CLOUDFLARE_ZONE_ID: str = Field(default="", description="Cloudflare zone ID")
    CLOUDFLARE_DOMAIN: str = Field(default="", description="Cloudflare domain name")
    TUNNEL_TOKEN: SecretStr = Field(default="", description="Cloudflare tunnel token")
    TUNNEL_NAME: str = Field(default="devplane-tunnel", description="Cloudflare tunnel name")
    
    # ==================== DigitalOcean ====================
    DIGITALOCEAN_TOKEN: SecretStr = Field(default="", description="DigitalOcean API token")
    DIGITALOCEAN_REGION: str = Field(default="nyc1", description="Default region for droplets")
    DROPLET_NAME: str = Field(default="devplane-vps", description="Default droplet name")
    DROPLET_IMAGE: str = Field(default="ubuntu-22-04-x64", description="Default droplet image")
    DROPLET_REGION: str = Field(default="nyc1", description="Default droplet region")
    DEPLOY_DIR: str = Field(default="/opt/devplane", description="Deployment directory on remote server")
    
    # ==================== AI Provider API Keys ====================
    OPENROUTER_API_KEY: SecretStr = Field(default="")
    DEEPSEEK_API_KEY: SecretStr = Field(default="")
    GROQ_API_KEY: SecretStr = Field(default="")
    GEMINI_API_KEY: SecretStr = Field(default="")
    TOGETHERAI_API_KEY: SecretStr = Field(default="")
    CEREBRAS_API_KEY: SecretStr = Field(default="")
    FIREWORKS_AI_API_KEY: SecretStr = Field(default="")
    OPENAI_API_KEY: SecretStr = Field(default="")
    
    # ==================== Slack ====================
    SLACK_BOT_TOKEN: SecretStr = Field(default="")
    SLACK_APP_TOKEN: SecretStr = Field(default="")
    
    # ==================== Vector Database ====================
    QDRANT_URL: str = Field(default="http://localhost:6333")
    QDRANT_KEY: SecretStr = Field(default="")
    
    # ==================== SSO / OAuth ====================
    SSO_PROVIDER: str = Field(default="google")
    SSO_GOOGLE_CLIENT_ID: SecretStr = Field(default="")
    SSO_GOOGLE_CLIENT_SECRET: SecretStr = Field(default="")
    SSO_GITHUB_CLIENT_ID: SecretStr = Field(default="")
    SSO_GITHUB_CLIENT_SECRET: SecretStr = Field(default="")
    SSO_MICROSOFT_CLIENT_ID: SecretStr = Field(default="")
    SSO_MICROSOFT_CLIENT_SECRET: SecretStr = Field(default="")
    SSO_MICROSOFT_TENANT_ID: SecretStr = Field(default="")
    SSO_OIDC_ISSUER_URL: str = Field(default="")
    SSO_REDIRECT_URI: str = Field(default="")
    
    # ==================== Twilio (SMS MFA) ====================
    TWILIO_ACCOUNT_SID: SecretStr = Field(default="")
    TWILIO_AUTH_TOKEN: SecretStr = Field(default="")
    TWILIO_PHONE_NUMBER: str = Field(default="")
    
    # ==================== Sandbox Security ====================
    SANDBOX_SSH_KEY_NAME: str = Field(default="deployment")
    
    # ==================== Bitwarden Vault (optional) ====================
    BITWARDEN_MASTER_PASSWORD: SecretStr = Field(default="")
    BITWARDEN_CLIENT_ID: SecretStr = Field(default="")
    BITWARDEN_CLIENT_SECRET: SecretStr = Field(default="")
    BITWARDEN_ORG_ID: SecretStr = Field(default="")
    
    # ==================== Timeouts & Safety ====================
    SSH_CONNECT_TIMEOUT: int = Field(default=10, description="SSH connection timeout in seconds")
    SSH_SERVER_ALIVE_INTERVAL: int = Field(default=5, description="SSH server alive interval")
    SSH_SERVER_ALIVE_COUNT_MAX: int = Field(default=3, description="SSH server alive count max")
    SUBPROCESS_TIMEOUT: int = Field(default=30, description="Default subprocess timeout in seconds")
    APT_TIMEOUT: int = Field(default=300, description="APT command timeout in seconds")
    
    # ==================== Computed Properties ====================
    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        return self.ENV.lower() == "development"
    
    @property
    def is_staging(self) -> bool:
        return self.ENV.lower() == "staging"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string into list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
    
    # ==================== Validators ====================
    @validator("SECRET_KEY", pre=True)
    def ensure_secret_key(cls, v):
        """Generate a secret key if not provided."""
        if not v:
            import secrets
            v = secrets.token_hex(32)
            logger.warning("SECRET_KEY not set, generating a temporary one.")
        return v


# Global settings instance
_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """Singleton factory for settings."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def load_env_file(env_path: str = ".env") -> None:
    """
    Load environment variables from a .env file.
    This is a safety wrapper used by scripts to ensure env vars are loaded.
    """
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key, value)


def load_config_from_yaml(env: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from environment-specific YAML file.
    Returns dict that can be used to update settings.
    """
    env = env or os.environ.get("ENV", "development")
    config_dir = Path("config") / "environments"
    yaml_path = config_dir / f"{env}.yaml"
    
    if not yaml_path.exists():
        logger.debug(f"No YAML config found at {yaml_path}")
        return {}
    
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        logger.info(f"Loaded configuration from {yaml_path}")
        return data or {}
    except ImportError:
        logger.warning("PyYAML not installed, skipping YAML config.")
    except Exception as e:
        logger.error(f"Failed to load YAML config: {e}")
    
    return {}


# Convenience alias
settings = get_settings()