# DevPlane Deployment Guide

Complete deployment instructions for DevPlane in various environments.

## Quick Start

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

### Docker Deployment

```bash
# 1. Build and run with Docker Compose
docker-compose up -d

# 2. With Cloudflare Tunnel (secure public access)
docker-compose --profile tunnel up -d

# 3. With Monitoring (Prometheus + Grafana)
docker-compose --profile monitoring up -d
```

### MCP Server Deployment

To run DevPlane's Model Context Protocol (MCP) server for local IDE integrations (Antigravity, Kilo Code, Continue.dev):

```bash
# 1. Start the MCP server process
python mcp_server_devplane.py

# Optional: Run in background or using PM2/systemd for persistent availability
pm2 start mcp_server_devplane.py --name "devplane-mcp"
```

If you are running the Mothership DevPlane on a remote Droplet or Fly.io, you can use **SSH port forwarding** or point your IDE extensions to the remote tunnel if the extension supports remote MCP servers.

### Fly.io Deployment

```bash
# 1. Install flyctl and login
curl -L https://fly.io/install.sh | sh
fly auth login

# 2. Create app and volume
fly apps create devplane
fly volumes create devplane_data --size 3

# 3. Set secrets
fly secrets set DIGITALOCEAN_TOKEN=...
fly secrets set CLOUDFLARE_API_KEY=...
# ... set other secrets from .env

# 4. Deploy
fly deploy
```

## Environment Configuration

### Required API Keys

| Service | Purpose | Get Key At |
|---------|---------|------------|
| DeepSeek | Free AI inference | https://platform.deepseek.com |
| Groq | Fast inference | https://console.groq.com |
| Gemini | Free Google AI | https://aistudio.google.com |
| OpenRouter | Multi-model access | https://openrouter.ai |
| DigitalOcean | VM provisioning | https://cloud.digitalocean.com |
| Cloudflare | DNS & tunnels | https://dash.cloudflare.com |

### Security Best Practices

1. **Use Cloudflare Tunnel** for secure access without opening ports
2. **Enable rate limiting** (configured in security.py)
3. **Use strong secrets** (generate with `openssl rand -hex 32`)
4. **Regular backups** of devplane.db
5. **Monitor audit logs** via `/api/health/detailed`

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

## Troubleshooting

### Common Issues

1. **MCP Connection Errors**: These are non-critical. The system works without MCP.
2. **Slack Not Connected**: Check SLACK_BOT_TOKEN and SLACK_APP_TOKEN format.
3. **Database Locked**: Ensure single SQLite access or use PostgreSQL.

### Logs

```bash
# Docker logs
docker-compose logs -f devplane

# Fly.io logs
fly logs
```

## Production Checklist

- [ ] All API keys configured in environment
- [ ] Database persistence configured
- [ ] Cloudflare Tunnel or SSL configured
- [ ] Monitoring enabled
- [ ] Backups scheduled
- [ ] Rate limiting tested
- [ ] Health checks passing

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

For more details, see `USER_GUIDE.md` and `devplane/infra/sandbox.py`.
