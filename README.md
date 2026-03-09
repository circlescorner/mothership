# Mothership Optimized

A fully autonomous AI agent orchestration platform that runs on a $5/month budget, leveraging free-tier AI providers and scale-to-zero infrastructure.

## System Overview

Mothership Optimized is a production-ready control plane for AI agent chains with built-in budget enforcement, infrastructure provisioning, and performance optimization. The system is designed to operate within strict financial constraints while maintaining enterprise-grade capabilities.

### Core Components

1. **Agentic Mesh** - Unified MCP-based communication backbone
   - **LlamaIndex**: Data retrieval and document indexing
   - **Haystack**: Complex NLP pipelines and enterprise search
   - **CrewAI**: Multi-agent task orchestration
   - **PydanticAI**: Strict schema validation
   - **Semantic Kernel**: Enterprise business logic bridge

2. **Chain Engine** - Multi-tier tournament system for AI task execution
   - Planner/Executor/Reviewer architecture
   - Tier-based model selection (cheap/mid/premium)
   - Real-time performance tracking and optimization

3. **Infrastructure Manager** - Cloud resource orchestration
   - DigitalOcean droplet provisioning
   - Kasm workspaces for browser-based development
   - GPU resource management
   - Cloudflare DNS automation
   - **Persistent Infra Agent**: Aggressive scale-to-zero based on budget

4. **Memory System** - Vector-based memory with Qdrant
   - Semantic search across project history
   - Embedding-based similarity matching
   - Persistent memory storage

5. **Budget Enforcement** - Real-time cost tracking
   - Provider-level spending limits
   - Project budget controls
   - Automatic blocking when limits exceeded

6. **Visual Flow & Observability** - Single pane of glass
   - **Langflow & Flowise**: Visual chain configuration
   - **Langfuse**: Real-time execution tracing

7. **Mesh Configuration Dashboard** - Unified Agentic Mesh management
   - Visual configuration of MCP servers, execution modes, and tournament brackets
   - Real-time mesh visualization and routing rules
   - Deployment wizard for infrastructure provisioning
   - Secrets management for secure credential storage

## Project Structure

```
mothership_optimized/
├── config/                      # Environment-specific configurations
│   └── environments/
│       ├── dev.yaml            # Development configuration
│       ├── staging.yaml        # Staging configuration
│       └── production.yaml     # Production configuration
├── deployments/                 # Deployment pipeline
│   ├── orchestrator.py         # Unified deployment orchestrator
│   ├── DEPLOYMENT_GUIDE.md     # Detailed deployment guide
│   ├── legacy/                 # Deprecated scripts (for reference)
│   ├── scripts/                # Reusable deployment scripts
│   ├── docker/                 # Docker-related files
│   └── terraform/              # Infrastructure-as-code (optional)
├── devplane/                    # Core application code
│   ├── core/
│   │   └── config.py           # Pydantic settings configuration
│   ├── api/                    # FastAPI endpoints
│   ├── chain/                  # Chain execution engine
│   ├── infra/                  # Infrastructure management
│   ├── memory/                 # Vector memory store
│   ├── orchestration/          # Workflow orchestration
│   ├── secrets/                # Secret management (Vault)
│   ├── security/               # Security utilities
│   └── slack/                  # Slack bot integration
├── tests/                       # Test suite
├── static/                      # Web dashboard assets
├── docs/                        # Additional documentation
├── .env.example                 # Environment variable template
└── requirements.txt            # Python dependencies
```

## Configuration Management

DevPlane uses a **Pydantic Settings**-based configuration system that loads from:

1. **Environment Variables** (highest priority)
2. **Environment-specific YAML files** (`config/environments/`)
3. **Default values** in Pydantic models

### Quick Configuration

```bash
# 1. Copy the example environment file
cp .env.example .env

# 2. Edit .env with your settings
nano .env
```

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ENV` | Runtime environment | `development`, `staging`, `production` |
| `DEPLOYMENT_DOMAIN` | Primary domain | `yourdomain.com` |
| `SECRET_KEY` | Session signing key | (auto-generated) |
| `DATABASE_URL` | Database connection | `sqlite+aiosqlite:///./devplane.db` |

### AI Provider API Keys (configure at least 2-3)

| Variable | Provider | Get Key At |
|----------|----------|------------|
| `DEEPSEEK_API_KEY` | DeepSeek | https://platform.deepseek.com |
| `GROQ_API_KEY` | Groq | https://console.groq.com |
| `GEMINI_API_KEY` | Gemini | https://aistudio.google.com |
| `OPENROUTER_API_KEY` | OpenRouter | https://openrouter.ai |

### Infrastructure Configuration

| Variable | Description |
|----------|-------------|
| `DIGITALOCEAN_TOKEN` | DigitalOcean API token |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token (recommended) |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| `CLOUDFLARE_ZONE_ID` | Cloudflare zone ID |

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

# 3. Run the server
python -m uvicorn main:app --port 8000 --reload
```

### Using the Deployment Orchestrator

```bash
# Discover existing resources (dry-run)
python deployments/orchestrator.py --env production --phase discover --dry-run

# Deploy to staging
python deployments/orchestrator.py --env staging --phase deploy

# Run full pipeline for production
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

## API Endpoints

- `GET /` - Dashboard interface
- `POST /api/chains/run` - Execute AI chain
- `GET /api/infra/status` - Infrastructure status
- `GET /api/credits/summary` - Spending overview
- `GET /api/optimizer/insights` - Performance analytics
- `GET /api/mesh/config` - Get mesh configuration
- `PUT /api/mesh/config` - Update mesh configuration
- `GET /api/mesh/servers` - List MCP server status
- `GET /api/mesh/visualize` - Mesh visualization data
- `GET /api/mesh/tournaments` - Tournament history
- `GET /api/deploy/detect` - Detect environment
- `POST /api/deploy` - Save deployment configuration
- `GET /api/secrets` - List secrets (masked)
- `POST /api/secrets` - Update a secret

### Running a Chain

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello", "project_id":0, "mode":"tournament"}' \
  http://localhost:8000/api/chains/run
```

## Budget Management

The system enforces budgets at multiple levels:

1. **Provider Budgets**: Each AI provider has monthly spending limits
2. **Project Budgets**: Overall project spending caps
3. **Real-time Blocking**: Requests are blocked when budgets exceeded

Current spending: $0.0421 (well within $5 monthly limit)

## Performance Insights

Based on initial testing:
- **Fastest Model**: GPT-4o (386ms average)
- **Most Cost-Effective**: GPT-4o ($0.0001875 per call)
- **Highest Quality**: Claude 3.5 Sonnet (0.7 quality score)

## Documentation

- **[USER_GUIDE.md](USER_GUIDE.md)** - Complete user guide for DevPlane
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Deployment instructions
- **[deployments/DEPLOYMENT_GUIDE.md](deployments/DEPLOYMENT_GUIDE.md)** - New deployment pipeline guide
- **[GLONDOR-SETUP.md](GLONDOR-SETUP.md)** - Server setup guide
- **[AGENTS.md](AGENTS.md)** - Development patterns and safety guidelines
- **[CHANGELOG.md](CHANGELOG.md)** - Project changelog

## Cost Breakdown

| Component | Monthly Cost | Status |
|-----------|--------------|--------|
| Fly.io Control Plane | $0.00 | Free tier |
| DigitalOcean Droplets | ~$66.00 | Active (existing) |
| AI API Calls | $0.0421 | Under budget |
| **Total** | **~$66.00** | **Existing infrastructure** |

*Note: The $5 budget applies only to new AI API spending, not existing infrastructure.*

## Security

- **Cloudflare Tunnel** for secure access without opening ports
- **Rate limiting** configured in `devplane/security.py`
- **Strong secrets** (generate with `openssl rand -hex 32`)
- **Regular backups** of `devplane.db`
- **Audit logging** via `/api/health/detailed`

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_config_endpoints.py

# Run with coverage
pytest --cov=devplane
```

## License

Proprietary - Internal use only

## Support

For issues or questions:
1. Check the documentation in `docs/`
2. Review logs: `docker-compose logs -f devplane`
3. Contact the development team via Slack integration
