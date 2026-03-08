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

### Script Execution Order
1. `scripts/deploy-infrastructure.py --discover` - Verify resources
2. `scripts/deploy-infrastructure.py --dry-run` - Preview changes
3. `scripts/deploy-infrastructure.py --deploy` - Create infrastructure
4. `scripts/setup-gate-droplet.sh` - Run ON the gate droplet via SSH
5. `scripts/setup-devplane-control.sh` - Run ON the control droplet via SSH
6. `scripts/configure-cloudflare.py` - Configure DNS/SSL

## OpenSpec Workflow

This project uses the OpenSpec change management workflow:
- `.kilocode/skills/` - Contains skill definitions for changes
- `openspec/changes/` - Active change specifications
- Use the `opsx-propose`, `opsx-explore`, `opsx-apply`, `opsx-archive` commands

## Safety Resources

- `scripts/.kilocode-safety-wrapper.sh` - Source this for timeout aliases
- `.vscode/EMERGENCY_CHEAT_SHEET.md` - Terminal hang emergency procedures
- `docs/TERMINAL_HANG_SOLUTIONS.md` - Comprehensive prevention guide
