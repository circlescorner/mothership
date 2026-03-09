# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

DevPlane Infrastructure - Python/Bash automation for deploying DigitalOcean infrastructure with Cloudflare edge protection.

## Critical Patterns (Non-Obvious)

### Terminal Hang Prevention (MANDATORY)
This project was created to solve terminal hang issues with Kilo Code. ALL remote commands MUST include timeout protection:

**SSH Commands** - Must use these exact flags:
```bash
ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no root@IP 'command'
```

**Python API Calls** - Must include timeout in subprocess:
```python
subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # 30s max
```

**APT Commands** - Must set non-interactive mode:
```bash
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none
timeout 300 apt-get update  # Always wrap with timeout
```

### Environment Loading Pattern
All Python scripts MUST call `load_env_file()` before accessing environment variables:
```python
def load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key, value)
```

### State File Management
Infrastructure state is tracked in JSON files (do not edit manually):
- `infrastructure-state.json` - Tracks droplet IDs, IPs, firewall rules
- `gate-droplet.json` - Gate droplet specific configuration
- `devplane-droplet.json` - Control plane configuration
- `gate-firewall.json` - Firewall rule definitions

### Script Execution Order (New Deployment Pipeline)

The new deployment pipeline uses `deployments/orchestrator.py`:

1. `python deployments/orchestrator.py --env production --phase discover --dry-run` - Verify resources
2. `python deployments/orchestrator.py --env production --phase provision` - Create infrastructure
3. `python deployments/orchestrator.py --env production --phase configure` - Generate configuration
4. `python deployments/orchestrator.py --env production --phase deploy` - Deploy application
5. `python deployments/orchestrator.py --env production --phase verify` - Health checks

### Legacy Scripts (Deprecated)

Old scripts have been moved to `deployments/legacy/`:
- `deployments/legacy/deploy.py`
- `deployments/legacy/provision-and-deploy.py`
- `deployments/legacy/deploy-glondor.sh`
- `deployments/legacy/deploy-glondor-prod.sh`

## OpenSpec Workflow

This project uses the OpenSpec change management workflow:
- `.kilocode/skills/` - Contains skill definitions for changes
- `openspec/changes/` - Active change specifications
- Use the `opsx-propose`, `opsx-explore`, `opsx-apply`, `opsx-archive` commands

## Safety Resources

- `scripts/.kilocode-safety-wrapper.sh` - Source this for timeout aliases
- `.vscode/EMERGENCY_CHEAT_SHEET.md` - Terminal hang emergency procedures
- `docs/TERMINAL_HANG_SOLUTIONS.md` - Comprehensive prevention guide
