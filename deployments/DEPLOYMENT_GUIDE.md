# DevPlane Deployment Guide

This document describes the new unified deployment pipeline for DevPlane, which replaces the overlapping scripts (`deploy.py`, `provision‑and‑deploy.py`, `deploy‑glondor.sh`, etc.) with a modular, environment‑aware system.

## Overview

The new deployment pipeline is built around:

1. **Configuration‑over‑code** – All environment‑specific values are defined in environment variables or YAML configuration files.
2. **Phase‑based execution** – Deployment is broken into distinct phases (discovery, provisioning, configuration, deployment, verification, rollback).
3. **Timeout protection** – All remote commands (SSH, APT, subprocess) include mandatory timeout safeguards to prevent terminal hangs.
4. **Secret injection** – Secrets are sourced from environment variables, `.env` files, or Bitwarden Vault, never hardcoded.
5. **Multi‑environment support** – Separate configurations for development, staging, and production environments.

## Directory Structure

```
mothership_optimized/
├── config/
│   ├── environments/
│   │   ├── dev.yaml          # Development configuration
│   │   ├── staging.yaml      # Staging configuration
│   │   ├── production.yaml   # Production configuration
├── deployments/
│   ├── orchestrator.py       # Unified deployment orchestrator
│   ├── scripts/              # Reusable deployment scripts
│   ├── terraform/            # Infrastructure‑as‑code (optional)
│   ├── docker/               # Docker‑related files
│   ├── legacy/               # Old deployment scripts (deprecated)
│   ├── DEPLOYMENT_GUIDE.md   # This document
├── devplane/
│   ├── core/
│   │   ├── config.py         # Pydantic settings configuration loader
```

## Configuration Management

The configuration system uses Pydantic Settings to load settings from:

1. Environment variables (highest priority)
2. Environment‑specific YAML files (`config/environments/`)
3. Default values defined in Pydantic models

### Key Configuration Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ENV` | Runtime environment (`development`, `staging`, `production`) | `production` |
| `DEPLOYMENT_DOMAIN` | Primary domain for deployment | `glondor.xyz` |
| `DEPLOYMENT_MODE` | Deployment mode (`local`, `remote`, `docker`) | `remote` |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token (recommended) | `...` |
| `DIGITALOCEAN_TOKEN` | DigitalOcean API token | `...` |
| `SECRET_KEY` | Secret key for session signing | `...` |
| `TUNNEL_TOKEN` | Cloudflare tunnel token | `...` |

All sensitive values are stored as `SecretStr` and are never printed in logs.

### Environment YAML Files

Each environment has a corresponding YAML file in `config/environments/`. These files define default values for that environment, which can be overridden by environment variables.

Example: `config/environments/production.yaml`

```yaml
ENV: production
DEPLOYMENT_DOMAIN: yourdomain.com
DEPLOYMENT_MODE: remote
CLOUDFLARE_API_TOKEN: ""
DIGITALOCEAN_TOKEN: ""
```

## Deployment Orchestrator

The main deployment entrypoint is `deployments/orchestrator.py`. It supports phase‑based execution with dry‑run capability.

### Usage

```bash
python deployments/orchestrator.py --env production --phase discover --dry-run
python deployments/orchestrator.py --env staging --phase deploy
python deployments/orchestrator.py --env dev --phase rollback
```

### Phases

1. **discover** – Check existing resources (Cloudflare tunnels, DNS records, droplets). Dry‑run friendly.
2. **provision** – Create missing infrastructure (droplets, tunnels, DNS records).
3. **configure** – Generate environment‑specific configuration files (`.env.deploy`, `docker‑compose.prod.yml`).
4. **deploy** – Deploy application (local Docker Compose or remote droplet).
5. **verify** – Health checks and smoke tests.
6. **rollback** – Rollback to previous deployment snapshot (not fully implemented yet).

### Safety Features

The orchestrator includes timeout protection for all remote operations:

- **SSH commands** use `-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3`
- **Subprocess commands** have a default timeout of 30 seconds
- **APT commands** run with `DEBIAN_FRONTEND=noninteractive` and a timeout of 300 seconds

## Legacy Script Migration

The old deployment scripts have been moved to `deployments/legacy/`:

- `deployments/legacy/deploy.py`
- `deployments/legacy/provision‑and‑deploy.py`
- `deployments/legacy/deploy‑glondor.sh`
- `deployments/legacy/deploy‑glondor‑prod.sh`

The root `deploy.py` script is now a wrapper that calls the orchestrator, maintaining backward compatibility with the previous CLI interface.

## Secret Management

### Bitwarden Vault Integration

DevPlane includes a Bitwarden Vault integration (`devplane/secrets/vault.py`) for secure secret retrieval. Secrets are fetched at runtime from Bitwarden and injected into environment variables.

To use Bitwarden:

1. Install Bitwarden CLI (`npm install -g @bitwarden/cli`)
2. Set environment variables:
   - `BITWARDEN_MASTER_PASSWORD`
   - `BITWARDEN_CLIENT_ID` / `BITWARDEN_CLIENT_SECRET` (optional)
   - `BITWARDEN_ORG_ID` (optional)

3. Secrets are stored in Bitwarden with names like `openrouter‑api‑key`, `digitalocean‑token`, etc.

### Environment Variables Fallback

If Bitwarden is not configured, secrets are loaded from `.env` file (following AGENTS.md safety pattern).

**Important:** The `.env` file should never be committed to version control. Use `.env.example` as a template.

## Timeout Protection Patterns

All deployment scripts follow the terminal‑hang prevention patterns described in AGENTS.md:

### SSH Commands

```bash
ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no root@IP 'command'
```

### Python Subprocess

```python
subprocess.run(cmd, capture_output=True, text=True, timeout=30)
```

### APT Commands

```bash
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none
timeout 300 apt-get update
```

The safety wrapper `scripts/.kilocode‑safety‑wrapper.sh` provides aliases and functions for timeout protection.

## Deployment Examples

### Development (Local)

```bash
# Load development configuration
export ENV=development

# Discover resources (dry‑run)
python deployments/orchestrator.py --env development --phase discover --dry-run

# Deploy locally with Docker Compose
python deployments/orchestrator.py --env development --phase deploy
```

### Staging (Remote)

```bash
# Set staging environment variables
export ENV=staging
export DEPLOYMENT_DOMAIN=staging.yourdomain.com
export DIGITALOCEAN_TOKEN=...
export CLOUDFLARE_API_TOKEN=...

# Run full deployment pipeline
python deployments/orchestrator.py --env staging --phase all
```

### Production (Full Pipeline)

```bash
# Validate configuration first
python deployments/orchestrator.py --env production --phase discover --dry-run

# Provision infrastructure
python deployments/orchestrator.py --env production --phase provision

# Configure and deploy
python deployments/orchestrator.py --env production --phase configure
python deployments/orchestrator.py --env production --phase deploy

# Verify deployment health
python deployments/orchestrator.py --env production --phase verify
```

## Troubleshooting

### Common Issues

1. **Missing environment variables** – The orchestrator validates required variables for each environment. Run `python deployments/orchestrator.py --env production --phase discover --dry-run` to see missing variables.

2. **Cloudflare tunnel creation fails** – Ensure `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_ZONE_ID` are set correctly.

3. **DigitalOcean droplet creation fails** – Check `DIGITALOCEAN_TOKEN` and ensure SSH key is configured.

4. **Timeout errors** – Increase timeout settings in `devplane/core/config.py` (`SSH_CONNECT_TIMEOUT`, `APT_TIMEOUT`, etc.).

### Logging

Deployment logs are written to stdout with timestamps. Use `--verbose` flag for debug‑level logging.

```bash
python deployments/orchestrator.py --env production --phase deploy --verbose
```

## Next Steps

The deployment pipeline is modular and extensible. Future improvements could include:

- **Kubernetes deployment** – Add a `kubernetes` deployment mode.
- **Terraform integration** – Use Terraform for infrastructure provisioning.
- **Advanced rollback** – Implement snapshot‑based rollback with database backup.
- **CI/CD integration** – Integrate with GitHub Actions or GitLab CI.

## References

- AGENTS.md – Terminal hang prevention patterns
- plans/architecture_audit.md – Original audit report
- devplane/core/config.py – Configuration system source
- devplane/secrets/vault.py – Bitwarden Vault integration