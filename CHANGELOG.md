# Changelog

All notable changes to the DevPlane project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **New Configuration Management System** (`devplane/core/config.py`)
  - Pydantic Settings-based configuration
  - Environment-specific YAML configuration files (`config/environments/`)
  - Support for development, staging, and production environments
  - SecretStr for sensitive values (never logged)
  - Automatic secret key generation if not provided
  - Timeout configuration (SSH, subprocess, APT)

- **New Deployment Pipeline** (`deployments/orchestrator.py`)
  - Phase-based deployment (discover, provision, configure, deploy, verify, rollback)
  - Environment-specific configuration injection
  - Dry-run capability for safe testing
  - Timeout protection for all remote commands
  - Multi-environment support (dev, staging, production)

- **Environment Configuration Files**
  - `config/environments/dev.yaml` - Development defaults
  - `config/environments/staging.yaml` - Staging defaults
  - `config/environments/production.yaml` - Production defaults

- **Test Suite** (`tests/`)
  - Moved all test files to dedicated `tests/` directory
  - Added new test files for configuration endpoints

- **Documentation**
  - New comprehensive deployment guide (`deployments/DEPLOYMENT_GUIDE.md`)
  - Updated all documentation to reflect new architecture
  - Added CHANGELOG.md

### Changed

- **Project Structure**
  - Moved temporary files to appropriate locations
  - Consolidated deployment scripts into `deployments/` directory
  - Organized configuration files under `config/environments/`

- **Configuration Management**
  - Hardcoded domain configurations externalized to environment variables
  - Domain placeholders now use `yourdomain.com` instead of hardcoded values
  - Configuration loaded from YAML files with environment variable overrides

- **Documentation Updates**
  - `README.md` - Updated with new project structure and quick start instructions
  - `USER_GUIDE.md` - Added configuration management and deployment pipeline sections
  - `DEPLOYMENT.md` - Updated to reference new orchestrator and deprecated old scripts
  - `GLONDOR-SETUP.md` - Updated to use domain placeholders and new configuration system
  - `AGENTS.md` - Updated script execution order to reference new deployment pipeline

### Deprecated

- **Legacy Deployment Scripts** (moved to `deployments/legacy/`)
  - `deploy.py` - Use `deployments/orchestrator.py` instead
  - `provision-and-deploy.py` - Use `deployments/orchestrator.py` instead
  - `deploy-glondor.sh` - Use `deployments/orchestrator.py` instead
  - `deploy-glondor-prod.sh` - Use `deployments/orchestrator.py` instead

- **Old Configuration Approach**
  - Direct environment variable management in scripts
  - Hardcoded domain values in documentation

### Removed

- **Temporary Files**
  - Cleaned up temporary files from project root
  - Consolidated test files into `tests/` directory

### Security

- **Secret Management**
  - All sensitive values now use Pydantic `SecretStr`
  - Secrets never printed in logs or error messages
  - Support for Bitwarden Vault integration (`devplane/secrets/vault.py`)

- **Timeout Protection**
  - SSH commands use `-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3`
  - Subprocess commands have 30-second timeout
  - APT commands wrapped with `timeout 300`

## Migration Guide

### From Legacy Deployment Scripts

If you were using the old deployment scripts, migrate to the new orchestrator:

**Before:**
```bash
python deploy.py --production
python provision-and-deploy.py
```

**After:**
```bash
# Validate first
python deployments/orchestrator.py --env production --phase discover --dry-run

# Deploy
python deployments/orchestrator.py --env production --phase all
```

### From Hardcoded Configuration

If you had hardcoded domain values, update to use environment variables:

**Before:**
```python
DOMAIN = "glondor.xyz"
```

**After:**
```python
from devplane.core.config import get_settings
settings = get_settings()
domain = settings.DEPLOYMENT_DOMAIN
```

Or set in `.env`:
```env
DEPLOYMENT_DOMAIN=yourdomain.com
```

## [1.0.0] - 2024-XX-XX

### Added

- Initial release of DevPlane
- Agentic Mesh with MCP server integration
- Chain Engine with tournament evaluation
- Infrastructure Manager for DigitalOcean/Cloudflare
- Memory System with Qdrant vector storage
- Budget Enforcement system
- Slack bot integration
- Web dashboard with mesh configuration
- Sandbox system for secure code execution
- Kiloclaw system for multi-instance testing

---

## Notes

- All legacy scripts remain in `deployments/legacy/` for reference but are no longer maintained
- The new deployment pipeline is the recommended approach for all new deployments
- Configuration validation is performed automatically by the orchestrator
- See `deployments/DEPLOYMENT_GUIDE.md` for detailed deployment instructions
