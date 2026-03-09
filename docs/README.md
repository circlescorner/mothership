# DevPlane Documentation

Welcome to the DevPlane documentation. This directory contains comprehensive guides and references for the DevPlane platform.

## Quick Navigation

### Getting Started
- **[../README.md](../README.md)** - Project overview and quick start
- **[../USER_GUIDE.md](../USER_GUIDE.md)** - Complete user guide for DevPlane
- **[../GLONDOR-SETUP.md](../GLONDOR-SETUP.md)** - Server setup instructions

### Deployment
- **[../DEPLOYMENT.md](../DEPLOYMENT.md)** - Deployment guide (legacy format)
- **[../deployments/DEPLOYMENT_GUIDE.md](../deployments/DEPLOYMENT_GUIDE.md)** - New deployment pipeline guide
- **[../CHANGELOG.md](../CHANGELOG.md)** - Project changelog and migration guide

### Development
- **[../AGENTS.md](../AGENTS.md)** - Development patterns and safety guidelines
- **[AGENTIC_MESH.md](AGENTIC_MESH.md)** - Agentic Mesh architecture documentation

### Configuration
- **[../.env.example](../.env.example)** - Environment variable template
- **[../config/environments/](../config/environments/)** - Environment-specific configurations
  - `dev.yaml` - Development configuration
  - `staging.yaml` - Staging configuration
  - `production.yaml` - Production configuration

## Documentation Structure

```
docs/
├── README.md              # This file - documentation index
├── AGENTIC_MESH.md        # Agentic Mesh architecture
└── (additional docs...)

Root Documentation:
├── README.md              # Project overview
├── USER_GUIDE.md          # User guide
├── DEPLOYMENT.md          # Deployment guide
├── GLONDOR-SETUP.md       # Server setup
├── AGENTS.md              # Development patterns
├── CHANGELOG.md           # Changelog
└── .env.example           # Environment template

Deployment Documentation:
deployments/
├── DEPLOYMENT_GUIDE.md    # New deployment pipeline
└── legacy/                # Legacy scripts (deprecated)

Configuration:
config/
└── environments/
    ├── dev.yaml
    ├── staging.yaml
    └── production.yaml
```

## Key Concepts

### Configuration Management
DevPlane uses a Pydantic Settings-based configuration system:
- Configuration loaded from environment variables (highest priority)
- Environment-specific YAML files (`config/environments/`)
- Default values in Pydantic models

See `devplane/core/config.py` for the configuration system implementation.

### Deployment Pipeline
The new deployment pipeline uses `deployments/orchestrator.py`:
- Phase-based execution (discover, provision, configure, deploy, verify, rollback)
- Environment-specific configuration
- Dry-run capability
- Timeout protection for all remote commands

### Agentic Mesh
The Agentic Mesh is a unified MCP-based communication backbone that integrates:
- LlamaIndex (Data retrieval)
- Haystack (NLP pipelines)
- CrewAI (Multi-agent orchestration)
- PydanticAI (Schema validation)
- Semantic Kernel (Enterprise logic)

## Safety Guidelines

All development must follow the safety patterns in [AGENTS.md](../AGENTS.md):
- SSH commands with timeout protection
- Subprocess commands with 30s timeout
- APT commands with non-interactive mode

## Support

For issues or questions:
1. Check the relevant documentation above
2. Review the [CHANGELOG.md](../CHANGELOG.md) for recent changes
3. Contact the development team via Slack integration
