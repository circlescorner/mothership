# DevPlane Infrastructure & User Guide

## Overview

DevPlane is a unified, **Cloud-Native AI Control Plane**. It is designed to be fully remote—meaning you do not need to run any local software. Everything is controlled via your secure web domain or directly through your Slack workspace.

DevPlane manages AI agent orchestration, secure sandboxing for autonomous execution, cost-collapsing infrastructure (DigitalOcean/GPU instances), and persistent memory schemas.

---

## 🚀 Unified UX: The Slack-First Command Center

The core philosophy of DevPlane is **ChatOps**. Your Slack workspace is the primary terminal for interacting with the AI mesh and underlying infrastructure.

### Agent Routing & Execution
In any synced Slack channel, just mention the bot or use bang commands to route tasks:
*   `@DevPlane can you write a python script for...` - Runs the default 5-tier tournament evaluation.
*   `!mesh <prompt>` - Engages the God-Mode iterative loop (Architect → Worker → Critic).
*   `!mesh_route <prompt>` - Engages the **Agentic Mesh**, intelligently routing tasks across specialized MCP servers (LlamaIndex, Haystack, CrewAI, PydanticAI, Semantic Kernel).
*   `!kilo_code <prompt>` - Routes the prompt directly to your persistent Kilo Code cloud workspace.
*   **File Context**: Drag and drop Python files or logs directly into Slack. The bot automatically parses the attachments and feeds them as context to the AI mesh.

### Visual Flow & Observability
DevPlane provides a "single pane of glass" for configuring and monitoring your AI chains:
*   **Langflow**: Visual chain builder available at `http://localhost:7860`
*   **Flowise**: Alternative visual builder available at `http://localhost:3001`
*   **Langfuse**: Real-time execution tracing and observability available at `http://localhost:3002`

### Dashboard UI
The DevPlane web dashboard (`http://localhost:8000`) provides a comprehensive interface for managing the Agentic Mesh, infrastructure, and secrets:
*   **Agentic Mesh Configuration**: Configure execution modes (tournament, mesh, agent), MCP server status, and routing rules.
*   **Deployment Wizard**: Guided setup for provisioning DigitalOcean droplets, configuring Cloudflare DNS, and setting up API keys.
*   **Secrets Management**: Securely store and rotate API keys, tokens, and environment variables.
*   **Real-time Monitoring**: Live metrics on provider usage, budget consumption, and system health.

### Infrastructure Management (CloudOps)
You can control the physical servers powering your dev environments via Slack Block Kit interactive buttons or commands (coming soon):
*   `!spinup worker` - Instantiates an ephemeral DigitalOcean droplet for temporary compute.
*   `!status` - Returns a current readout of all active infrastructure, Cloudflare tunnels, and real-time billing costs.
*   `!sleep` - Triggers the **"Collapse & Persist"** protocol (takes snapshots of active workspaces and destroys the hardware to drop costs to $0/hr).
*   `!wake` - Restores your workspaces from the snapshots exactly as you left them.

---

## ☁️ Architecture & Persistence

DevPlane operates on a Secure **Gate Droplet** topology.

### The Gate Droplet
A lightweight, permanent server (e.g., $4/mo) acts as the brain. It runs the FastAPI backend and maintains the Cloudflare Zero Trust tunnel (`cp.yourdomain.com`). 
*   **Shared Database:** The core `devplane.db` (containing AI memory, cost tracking, and configurations) is mounted on a secure Volume attached to the Gate Droplet.
*   The Gate Droplet never executes untrusted code. It strictly orchestrates.

### Kasm Workspaces (The Fleet)
When you need a visual IDE (VS Code, Chrome), DevPlane deploys a Kasm Workspace droplet. Because of the unified UX, your Kasm workspaces are automatically attached to the DevPlane mesh. They use the Mothership MCP server to route all their AI requests back through the Gate Droplet, centralizing your token billing (OpenRouter, DeepSeek, etc.).

---

## 🛡️ Secure Sandboxing (Deploying Malicious/Untrusted Tools)

When running highly autonomous, full-access LLM tools (like `Clawbot`), security is paramount to prevent lateral movement or accidental destruction of the core server.

**The Sandbox Protocol:**
1.  **Isolation (Air-Gapping):** Untrusted agents are never run on the Gate Droplet. Instead, DevPlane deploys an ephemeral "Sandbox Droplet" in an isolated Virtual Private Cloud (VPC).
2.  **Egress Filtering:** The Sandbox has strict network policies. It cannot route back to the Gate Droplet's private IP. UFW (Firewall) rules restrict outbound access to prevent malicious network scanning.
3.  **Non-Root Execution:** Agents operate inside unprivileged Docker containers within the Sandbox.
4.  **Atomization:** Once the LLM completes its task (e.g., "Analyze this unverified GitHub repo"), the outputs are scraped via a constrained SSH pipe, and the Sandbox droplet is instantly destroyed. No persistent threats can survive.

---

## ⚙️ Configuration & Control Plan

All settings, API keys, and model roles are securely managed without needing to SSH into servers.

### Configuration Management System

DevPlane uses a **Pydantic Settings**-based configuration system (`devplane/core/config.py`) that loads configuration from multiple sources (in order of priority):

1.  **Environment Variables** (highest priority)
2.  **Environment-specific YAML files** (`config/environments/{dev,staging,production}.yaml`)
3.  **Default values** defined in Pydantic models

#### Environment Configuration Files

Configuration files are located in `config/environments/`:

*   `dev.yaml` - Development environment defaults
*   `staging.yaml` - Staging environment defaults
*   `production.yaml` - Production environment defaults

Example `config/environments/production.yaml`:
```yaml
ENV: production
DEPLOYMENT_DOMAIN: yourdomain.com
DEPLOYMENT_MODE: remote
CLOUDFLARE_API_TOKEN: ""
DIGITALOCEAN_TOKEN: ""
```

#### Key Configuration Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ENV` | Runtime environment | `development`, `staging`, `production` |
| `DEPLOYMENT_DOMAIN` | Primary domain for deployment | `yourdomain.com` |
| `DEPLOYMENT_MODE` | Deployment mode | `local`, `remote`, `docker` |
| `SECRET_KEY` | Secret key for session signing | (auto-generated if not set) |
| `DATABASE_URL` | Database connection URL | `sqlite+aiosqlite:///./devplane.db` |

All sensitive values are stored as `SecretStr` and are never printed in logs.

### Setting Up Your Environment

1.  **Copy the example environment file:**
    ```bash
    cp .env.example .env
    ```

2.  **Edit `.env` with your API keys and settings:**
    ```env
    ENV=production
    DEPLOYMENT_DOMAIN=yourdomain.com
    SECRET_KEY=$(openssl rand -hex 32)
    
    # AI Providers (configure at least 2-3)
    DEEPSEEK_API_KEY=sk-...
    GROQ_API_KEY=gsk_...
    GEMINI_API_KEY=...
    OPENROUTER_API_KEY=sk-or-v1-...
    
    # Infrastructure
    DIGITALOCEAN_TOKEN=dop_v1_...
    CLOUDFLARE_API_TOKEN=...
    CLOUDFLARE_ACCOUNT_ID=...
    CLOUDFLARE_ZONE_ID=...
    ```

3.  **The Lockhost Wizard:** Navigate to `https://cp.yourdomain.com/lockhost` to configure API keys and assign 5-way model fallbacks for roles (Architect, Worker, Fast).

4.  **Domain & Cloudflare:** DevPlane natively interacts with the Cloudflare API to dynamically create DNS records and manage tunnels for new workspaces.

To ensure your system remains up to industry best practices, we implement FastAPI Security Middleware, strict CORS policies tied only to your domain, and Cloudflare Access (Zero Trust) requiring email/MFA authentication before even reaching the DevPlane web server.

---

## 🚀 Deployment Pipeline

DevPlane uses a unified deployment orchestrator (`deployments/orchestrator.py`) that replaces the legacy deployment scripts.

### Phase-Based Deployment

The orchestrator supports phase-based execution with dry-run capability:

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

### Deployment Phases

1.  **discover** - Check existing resources (Cloudflare tunnels, DNS records, droplets)
2.  **provision** - Create missing infrastructure (droplets, tunnels, DNS records)
3.  **configure** - Generate environment-specific configuration files
4.  **deploy** - Deploy application (local Docker Compose or remote droplet)
5.  **verify** - Health checks and smoke tests
6.  **rollback** - Rollback to previous deployment snapshot

### Legacy Scripts

Old deployment scripts have been moved to `deployments/legacy/` for reference:
*   `deployments/legacy/deploy.py`
*   `deployments/legacy/provision-and-deploy.py`
*   `deployments/legacy/deploy-glondor.sh`

See [`deployments/DEPLOYMENT_GUIDE.md`](deployments/DEPLOYMENT_GUIDE.md) for detailed deployment instructions.

---

## 🛠️ MCP Server & Tool Integration

DevPlane exposes a suite of tools via the **Model Context Protocol (MCP)**, enabling IDEs like Antigravity, Kilo Code, and Continue.dev to interact with the AI mesh and infrastructure directly.

### Available MCP Tools
The MCP server (`devplane/infra/mcp_server.py`) exposes the following tools:

- **Agent Interoperation**:
    - `ask_kilo_code`: Routes heavy coding tasks to the DevPlane worker role (DeepSeek V3 / Qwen 2.5 Coder 32B).
    - `ask_continue_dev`: Routes rapid tasks to the DevPlane fast role (LLaMA 3.3 70B).
    - `ask_antigravity`: Routes complex architecture planning to the DevPlane architect role (Claude Sonnet 4).

- **God-Mode Mesh**:
    - `vibe_code`: Invokes the iterative AI pipeline (Architect → Worker → Critic) for code generation.
    - `run_chain`: Executes a predefined chain of AI tasks.

- **Infrastructure Management**:
    - `create_sandbox`: Spins up an isolated, firewalled sandbox droplet for untrusted code execution.
    - `run_sandbox_script`: Executes a script inside a sandbox droplet via SSH.
    - `destroy_sandbox`: Destroys a sandbox droplet and cleans up firewall rules.

- **Droplet Management**:
    - `create_droplet`: Creates a new DigitalOcean droplet.
    - `destroy_droplet`: Destroys a droplet.
    - `list_droplets`: Lists all active droplets.

- **Cloudflare & DNS**:
    - `configure_cloudflare`: Configures DNS records and SSL certificates.

### Using the MCP Server
1.  **Local Development**: Run `python devplane/infra/mcp_server.py` to start the stdio MCP server.
2.  **Remote Deployment**: Deploy the MCP server on a Gate Droplet or Kasm Workspace and use SSH port forwarding to access it from your IDE.
3.  **IDE Configuration**: Add the MCP server to your IDE's settings (e.g., `settings.json` for Antigravity).

### Example: Creating a Sandbox
To spin up a sandbox droplet for testing untrusted code:
```json
{
  "name": "create_sandbox",
  "arguments": {
    "name": "test-sandbox",
    "region": "nyc1",
    "size": "s-1vcpu-1gb",
    "system_type": "kiloclaw"
  }
}
```
This creates a sandbox droplet with the "kiloclaw" system type, pre-configured with Docker and CI/CD tooling.

### Example: Running a Script in a Sandbox
To execute a script inside a sandbox:
```json
{
  "name": "run_sandbox_script",
  "arguments": {
    "sandbox_id": "sandbox-12345",
    "script": "echo 'Hello from sandbox!'"
  }
}
```

---

## 🌀 Kiloclaw System (Multi-Instance Testing)

The **Kiloclaw System** is a specialized configuration for the sandbox that enables multi-instance interaction, perfect for deployable full-scale testing, coding, and debugging.

### Features
- **Multiple Instances**: Spin up multiple isolated sandbox instances that can communicate with each other (via a shared VPC).
- **MCP Integration**: Sandboxes can call the `vibe_code` tool to leverage the AI mesh for debugging and code generation.
- **Auto‑Cleanup**: Sandboxes are automatically destroyed after a configurable timeout or upon task completion.

### Use Cases
1.  **Distributed Testing**: Run multiple test runners in separate sandboxes and aggregate results.
2.  **Debugging**: Spin up a "debug" sandbox, use `run_sandbox_script` to inspect state, and call `vibe_code` for AI‑assisted analysis.
3.  **CI/CD Pipelines**: Create a temporary CI/CD environment for each build, run tests, and destroy the environment after.

### Spin‑Up Commands
- **Via Slack**: `!spinup kiloclaws count=3` (creates 3 kiloclaw instances).
- **Via MCP**: Use `create_sandbox` with `system_type: "kiloclaw"` and `count: 3`.

---

## 📚 Additional Resources

- **API Documentation**: See `devplane/api/` for FastAPI endpoints.
- **Chain Engine**: See `devplane/chain/engine.py` for chain execution logic.
- **Memory & Caching**: See `devplane/memory/store.py` for persistent memory schemas.
- **Security**: See `devplane/security/` for secrets management and encryption.
- **Configuration**: See `devplane/core/config.py` for Pydantic settings configuration.
- **Deployment**: See `deployments/DEPLOYMENT_GUIDE.md` for detailed deployment instructions.

For more information, refer to [`DEPLOYMENT.md`](DEPLOYMENT.md), [`README.md`](README.md), and the project documentation.
