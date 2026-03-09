# DevPlane Deployment Guide

Complete deployment instructions for DevPlane in various environments.

> **Note:** This guide has been updated to reflect the new deployment pipeline. For the legacy deployment documentation, see `deployments/legacy/` directory. For detailed information about the new orchestrator, see [`deployments/DEPLOYMENT_GUIDE.md`](deployments/DEPLOYMENT_GUIDE.md).

---

## Quick Start (New Deployment Pipeline)

The new deployment pipeline uses `deployments/orchestrator.py` with environment-specific configuration.

### Local Development

```bash
# 1. Clone and setup
git clone <repo-url>
cd mothership_optimized
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Run
python -m uvicorn main:app --reload --port 8000
```

### Using the Deployment Orchestrator

```bash
# Discover existing resources (dry-run friendly)
python deployments/orchestrator.py --env production --phase discover --dry-run

# Provision infrastructure
python deployments/orchestrator.py --env staging --phase provision

# Deploy application
python deployments/orchestrator.py --env production --phase deploy

# Run full pipeline
python deployments/orchestrator.py --env production --phase all
```

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up -d

# With Cloudflare Tunnel (secure public access)
docker-compose --profile tunnel up -d

# With Monitoring (Prometheus + Grafana)
docker-compose --profile monitoring up -d
```

---

## Configuration Management

DevPlane uses a **Pydantic Settings**-based configuration system (`devplane/core/config.py`).

### Configuration Sources (Priority Order)

1. **Environment Variables** (highest priority)
2. **Environment-specific YAML files** (`config/environments/`)
3. **Default values** in Pydantic models

### Environment Configuration Files

| File | Environment |
|------|-------------|
| `config/environments/dev.yaml` | Development |
| `config/environments/staging.yaml` | Staging |
| `config/environments/production.yaml` | Production |

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ENV` | Runtime environment | `production` |
| `DEPLOYMENT_DOMAIN` | Primary domain | `yourdomain.com` |
| `DEPLOYMENT_MODE` | Deployment mode | `local`, `remote`, `docker` |
| `SECRET_KEY` | Session signing key | (auto-generated if not set) |
| `DATABASE_URL` | Database connection | `sqlite+aiosqlite:///./devplane.db` |

### AI Provider API Keys

| Service | Purpose | Get Key At |
|---------|---------|------------|
| DeepSeek | Free AI inference | https://platform.deepseek.com |
| Groq | Fast inference | https://console.groq.com |
| Gemini | Free Google AI | https://aistudio.google.com |
| OpenRouter | Multi-model access | https://openrouter.ai |
| DigitalOcean | VM provisioning | https://cloud.digitalocean.com |
| Cloudflare | DNS & tunnels | https://dash.cloudflare.com |

---

## Deployment Phases

The orchestrator supports the following phases:

1. **discover** - Check existing resources (Cloudflare tunnels, DNS records, droplets). Dry-run friendly.
2. **provision** - Create missing infrastructure (droplets, tunnels, DNS records).
3. **configure** - Generate environment-specific configuration files (`.env.deploy`, `docker-compose.prod.yml`).
4. **deploy** - Deploy application (local Docker Compose or remote droplet).
5. **verify** - Health checks and smoke tests.
6. **rollback** - Rollback to previous deployment snapshot.

### Examples

```bash
# Development (Local)
export ENV=development
python deployments/orchestrator.py --env development --phase discover --dry-run
python deployments/orchestrator.py --env development --phase deploy

# Staging (Remote)
export ENV=staging
export DEPLOYMENT_DOMAIN=staging.yourdomain.com
export DIGITALOCEAN_TOKEN=...
export CLOUDFLARE_API_TOKEN=...
python deployments/orchestrator.py --env staging --phase all

# Production (Full Pipeline)
python deployments/orchestrator.py --env production --phase discover --dry-run
python deployments/orchestrator.py --env production --phase provision
python deployments/orchestrator.py --env production --phase configure
python deployments/orchestrator.py --env production --phase deploy
python deployments/orchestrator.py --env production --phase verify
```

---

## MCP Server Deployment

To run DevPlane's Model Context Protocol (MCP) server for local IDE integrations (Antigravity, Kilo Code, Continue.dev):

```bash
# 1. Start the MCP server process
python mcp_server_devplane.py

# Optional: Run in background or using PM2/systemd for persistent availability
pm2 start mcp_server_devplane.py --name "devplane-mcp"
```

If you are running the Mothership DevPlane on a remote Droplet or Fly.io, you can use **SSH port forwarding** or point your IDE extensions to the remote tunnel if the extension supports remote MCP servers.

---

## Fly.io Deployment

```bash
# 1. Install flyctl and login
curl -L https://fly.io/install.sh | sh
fly auth login

# 2. Create app and volume
fly apps create devplane
fly volumes create devplane_data --size 3

# 3. Set secrets
fly secrets set DIGITALOCEAN_TOKEN=...
fly secrets set CLOUDFLARE_API_TOKEN=...
# ... set other secrets from .env

# 4. Deploy
fly deploy
```

---

## Security Best Practices

1. **Use Cloudflare Tunnel** for secure access without opening ports
2. **Enable rate limiting** (configured in `devplane/security.py`)
3. **Use strong secrets** (generate with `openssl rand -hex 32`)
4. **Regular backups** of `devplane.db`
5. **Monitor audit logs** via `/api/health/detailed`

---

## Monitoring

### Health Endpoints

- `GET /api/health` - Basic health check
- `GET /api/health/detailed` - Full service health
- `GET /api/status` - System status overview
- `GET /api/metrics` - Prometheus metrics

### Alerts

Configure alerts in Prometheus for:
- High error rates (>5%)
- High latency (>2s p95)
- Budget thresholds (80% of monthly limit)

---

## Legacy Deployment Scripts (Deprecated)

The following scripts have been moved to `deployments/legacy/` and are deprecated:

- `deployments/legacy/deploy.py` - Old deployment script
- `deployments/legacy/provision-and-deploy.py` - Old provisioning script
- `deployments/legacy/deploy-glondor.sh` - Old Glondor deployment script
- `deployments/legacy/deploy-glondor-prod.sh` - Old production deployment script

The root `deploy.py` script is now a wrapper that calls the orchestrator, maintaining backward compatibility with the previous CLI interface.

---

## 🛠️ Sandbox & Kiloclaw System Deployment

DevPlane supports spinning up isolated sandbox droplets for running untrusted code, as well as "Kiloclaw" systems for multi-instance testing, debugging, and full-scale deployable testing.

### Spinning Up a Sandbox

You can create a sandbox droplet via the MCP server or directly via the API.

#### Via MCP Server

1. **Start the MCP server**:
   ```bash
   python devplane/infra/mcp_server.py
   ```

2. **Invoke the `create_sandbox` tool** (e.g., via Antigravity, Kilo Code, or Continue.dev):
   ```json
   {
     "name": "create_sandbox",
     "arguments": {
       "name": "my-sandbox",
       "region": "nyc1",
       "size": "s-1vcpu-1gb",
       "system_type": "kiloclaw"
     }
   }
   ```

3. **Run a script inside the sandbox**:
   ```json
   {
     "name": "run_sandbox_script",
     "arguments": {
       "sandbox_id": "sandbox-12345",
       "script": "echo 'Hello from sandbox!'"
     }
   }
   ```

4. **Destroy the sandbox**:
   ```json
   {
     "name": "destroy_sandbox",
     "arguments": {
       "sandbox_id": "sandbox-12345"
     }
   }
   ```

#### Via Slack Commands (Coming Soon)

- `!spinup sandbox` – Creates a generic sandbox.
- `!spinup kiloclaw count=3` – Creates 3 kiloclaw instances.

### Kiloclaw System (Multi-Instance Testing)

The Kiloclaw system is a specialized sandbox configuration that allows you to run multiple interacting instances for distributed testing, debugging, and CI/CD pipelines.

#### Features
- **Multiple Instances**: Spin up N isolated sandboxes that can communicate via a shared VPC.
- **MCP Integration**: Sandboxes can call the `vibe_code` tool (via `run_sandbox_script`) to leverage the AI mesh for debugging and code generation.
- **Auto‑Cleanup**: Sandboxes are automatically destroyed after a configurable timeout or upon task completion.

#### Use Cases
1. **Distributed Testing**: Run multiple test runners in separate sandboxes and aggregate results.
2. **Debugging**: Spin up a "debug" sandbox, use `run_sandbox_script` to inspect state, and call `vibe_code` for AI‑assisted analysis.
3. **CI/CD Pipelines**: Create a temporary CI/CD environment for each build, run tests, and destroy the environment after.

#### Security Considerations
- **Isolation**: Sandboxes are deployed in an isolated VPC and cannot access the Gate Droplet's private IP.
- **Egress Filtering**: UFW rules restrict outbound access to prevent malicious network scanning.
- **Non‑Root Execution**: Agents operate inside unprivileged Docker containers.

### Deploying the MCP Server on a Remote Droplet

If you want to use the MCP server from a remote Droplet (e.g., Gate Droplet), you can use SSH port forwarding:

1. **On your local machine**, run:
   ```bash
   ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no -L localhost:8000:localhost:8000 root@<DROPLET_IP>
   ```

2. **Start the MCP server on the Droplet**:
   ```bash
   ssh root@<DROPLET_IP> 'cd /path/to/mothership_optimized && python devplane/infra/mcp_server.py'
   ```

3. **Configure your IDE** to connect to `localhost:8000` (the forwarded port).

### Troubleshooting Sandbox Issues

- **Droplet Creation Fails**: Check your DigitalOcean API token and region availability.
- **SSH Timeout**: Ensure the droplet has finished provisioning (wait 60s).
- **UFW Rules Not Applied**: Verify that the `create_firewalled_sandbox` function completed successfully.
- **Sandbox Not Destroyed**: Check the `destroy_sandbox` function for errors; manual cleanup may be required via the DigitalOcean API.

---

## Troubleshooting

### Common Issues

1. **Missing environment variables** – The orchestrator validates required variables for each environment. Run `python deployments/orchestrator.py --env production --phase discover --dry-run` to see missing variables.

2. **Cloudflare tunnel creation fails** – Ensure `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_ZONE_ID` are set correctly.

3. **DigitalOcean droplet creation fails** – Check `DIGITALOCEAN_TOKEN` and ensure SSH key is configured.

4. **Timeout errors** – Increase timeout settings in `devplane/core/config.py` (`SSH_CONNECT_TIMEOUT`, `APT_TIMEOUT`, etc.).

5. **MCP Connection Errors**: These are non-critical. The system works without MCP.
6. **Slack Not Connected**: Check SLACK_BOT_TOKEN and SLACK_APP_TOKEN format.
7. **Database Locked**: Ensure single SQLite access or use PostgreSQL.

### Logs

```bash
# Docker logs
docker-compose logs -f devplane

# Fly.io logs
fly logs

# Verbose orchestrator output
python deployments/orchestrator.py --env production --phase deploy --verbose
```

---

## Production Checklist

- [ ] All API keys configured in environment
- [ ] Database persistence configured
- [ ] Cloudflare Tunnel or SSL configured
- [ ] Monitoring enabled
- [ ] Backups scheduled
- [ ] Rate limiting tested
- [ ] Health checks passing
- [ ] Configuration validated with `--dry-run`

---

## References

- [`deployments/DEPLOYMENT_GUIDE.md`](deployments/DEPLOYMENT_GUIDE.md) - Detailed deployment pipeline documentation
- [`USER_GUIDE.md`](USER_GUIDE.md) - Complete user guide
- [`AGENTS.md`](AGENTS.md) - Terminal hang prevention patterns
- [`devplane/core/config.py`](devplane/core/config.py) - Configuration system source
- [`devplane/secrets/vault.py`](devplane/secrets/vault.py) - Bitwarden Vault integration

For more details, see `USER_GUIDE.md` and `devplane/infra/sandbox.py`.
