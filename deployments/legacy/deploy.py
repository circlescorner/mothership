#!/usr/bin/env python3
"""
DevPlane Deployment Script

Cross-platform deployment script that:
- Creates Cloudflare Tunnels via API
- Manages DNS records
- Deploys with Docker Compose
- Works on Windows, macOS, and Linux

Usage:
    python deploy.py setup      # Initial setup (tunnel, DNS, .env)
    python deploy.py deploy     # Deploy with docker-compose
    python deploy.py status     # Show deployment status
    python deploy.py logs       # Show logs
    python deploy.py destroy    # Remove deployment
"""

import os
import sys
import json
import argparse
import subprocess
import asyncio
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

# Add devplane to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from devplane.infra.cloudflare import CloudflareManager


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

DOMAIN = os.environ.get("DEPLOYMENT_DOMAIN", "glondor.xyz")
TUNNEL_NAME = "devplane-tunnel"
COMPOSE_FILE = "docker-compose.yml"
COMPOSE_PROD_FILE = "docker-compose.prod.yml"
ENV_FILE = ".env"

# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_colored(text: str, color: str = ""):
    """Print colored text (disabled on Windows unless ANSICON or similar)."""
    if sys.platform == "win32" and not os.environ.get("ANSICON"):
        print(text)
    else:
        color_code = getattr(Colors, color.upper(), "")
        print(f"{color_code}{text}{Colors.ENDC}")


def print_section(title: str):
    """Print a section header."""
    print()
    print_colored("=" * 70, "header")
    print_colored(f"  {title}", "bold")
    print_colored("=" * 70, "header")
    print()


def print_success(message: str):
    """Print a success message."""
    print_colored(f"[OK] {message}", "green")


def print_error(message: str):
    """Print an error message."""
    print_colored(f"[ERROR] {message}", "fail")


def print_warning(message: str):
    """Print a warning message."""
    print_colored(f"[WARN] {message}", "warning")


def print_info(message: str):
    """Print an info message."""
    print_colored(f"[INFO] {message}", "cyan")


# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

def run_command(cmd: list[str], cwd: Optional[str] = None, capture: bool = False) -> tuple[int, str, str]:
    """
    Run a shell command and return (returncode, stdout, stderr).
    Cross-platform support for Windows and Unix.
    """
    try:
        if capture:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                shell=(sys.platform == "win32")
            )
            return result.returncode, result.stdout, result.stderr
        else:
            result = subprocess.run(cmd, cwd=cwd, shell=(sys.platform == "win32"))
            return result.returncode, "", ""
    except Exception as e:
        return 1, "", str(e)


def check_command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(command) is not None


def read_env_file(filepath: str = ENV_FILE) -> dict[str, str]:
    """Read .env file and return dict of key-value pairs."""
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars


def write_env_file(env_vars: dict[str, str], filepath: str = ENV_FILE):
    """Write dict to .env file, preserving existing comments if possible."""
    lines = []
    existing_keys = set()
    
    # Read existing file to preserve comments and structure
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}\n")
                        existing_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
    
    # Add new keys
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}\n")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def update_env_var(key: str, value: str, filepath: str = ENV_FILE):
    """Update a single environment variable in .env file."""
    env_vars = read_env_file(filepath)
    env_vars[key] = value
    write_env_file(env_vars, filepath)


# ═══════════════════════════════════════════════════════════════════════════════
# Cloudflare Tunnel Management
# ═══════════════════════════════════════════════════════════════════════════════

async def check_cloudflared_installed() -> bool:
    """Check if cloudflared CLI is installed."""
    return check_command_exists("cloudflared")


def print_cloudflared_install_instructions():
    """Print instructions for installing cloudflared."""
    print_section("Cloudflared Installation Required")
    print("Cloudflared is not installed. Please install it:")
    print()
    
    if sys.platform == "win32":
        print("Windows:")
        print("  1. Download from: https://github.com/cloudflare/cloudflared/releases")
        print("  2. Rename to cloudflared.exe and add to PATH")
        print("  3. Or use scoop: scoop install cloudflared")
        print()
        print("  PowerShell (Admin):")
        print('  Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "cloudflared.exe"')
        print(r'  Move-Item -Path ".\cloudflared.exe" -Destination "C:\Windows\System32\"')
    elif sys.platform == "darwin":
        print("macOS:")
        print("  brew install cloudflare/cloudflare/cloudflared")
    else:
        print("Linux:")
        print("  # Debian/Ubuntu")
        print("  wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb")
        print("  sudo dpkg -i cloudflared-linux-amd64.deb")
        print()
        print("  # Or use the install script:")
        print("  curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb")
        print("  sudo dpkg -i cloudflared.deb")
    
    print()
    print("After installation, run this script again.")


async def get_or_create_tunnel(cf: CloudflareManager) -> Optional[dict]:
    """Get existing tunnel or create a new one."""
    print_info("Checking for existing tunnels...")
    
    tunnels = await cf.list_tunnels()
    
    # Filter out error responses
    valid_tunnels = [t for t in tunnels if "error" not in t]
    
    # Look for existing tunnel with our name
    existing = next((t for t in valid_tunnels if t.get("name") == TUNNEL_NAME), None)
    
    if existing:
        print_success(f"Found existing tunnel: {existing['name']} (ID: {existing['id']})")
        return existing
    
    print_info(f"Creating new tunnel: {TUNNEL_NAME}")
    result = await cf.create_tunnel(TUNNEL_NAME)
    
    if "error" in result:
        print_error(f"Failed to create tunnel: {result['error']}")
        return None
    
    print_success(f"Created tunnel: {result['name']} (ID: {result['id']})")
    return result


async def get_tunnel_token(cf: CloudflareManager, tunnel_id: str) -> Optional[str]:
    """Get the token for a tunnel."""
    print_info("Fetching tunnel token...")
    
    result = await cf.get_tunnel_token(tunnel_id)
    
    if "error" in result:
        print_error(f"Failed to get tunnel token: {result['error']}")
        return None
    
    token = result.get("token")
    if token:
        print_success("Successfully retrieved tunnel token")
        return token
    
    print_error("No token in response")
    return None


async def create_dns_records(cf: CloudflareManager, tunnel_id: str) -> bool:
    """Create CNAME DNS records pointing to the tunnel."""
    print_section("DNS Record Management")
    
    # Records to create
    records_to_create = [
        ("@", f"{tunnel_id}.cfargotunnel.com"),
        ("www", f"{tunnel_id}.cfargotunnel.com"),
        ("api", f"{tunnel_id}.cfargotunnel.com"),
        ("app", f"{tunnel_id}.cfargotunnel.com"),
    ]
    
    success = True
    
    for subdomain, target in records_to_create:
        name = f"{subdomain}.{DOMAIN}" if subdomain != "@" else DOMAIN
        
        print_info(f"Creating DNS record: {name} → {target}")
        
        result = await cf.create_dns_record(name, target, record_type="CNAME", proxied=True)
        
        if "error" in result:
            # Check if it's a duplicate record error
            if "already exists" in str(result.get("error", "")).lower():
                print_warning(f"DNS record already exists: {name}")
            else:
                print_error(f"Failed to create DNS record {name}: {result['error']}")
                success = False
        else:
            print_success(f"Created DNS record: {name} → {target}")
    
    return success


# ═══════════════════════════════════════════════════════════════════════════════
# Docker Compose Management
# ═══════════════════════════════════════════════════════════════════════════════

def generate_prod_compose() -> bool:
    """Generate docker-compose.prod.yml with production settings."""
    print_section("Generating Production Compose File")
    
    compose_content = f'''# ═══════════════════════════════════════════════════════════════════════════════
# DevPlane Production Docker Compose Configuration
# Auto-generated by deploy.py on {datetime.now().isoformat()}
# ═══════════════════════════════════════════════════════════════════════════════

version: "3.8"

services:
  # Main DevPlane Application
  devplane:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    restart: always
    volumes:
      - ./data:/app/data
      - ./devplane.db:/app/devplane.db
      - ./static:/app/static
    environment:
      - DEVPLANE_DB_PATH=/app/devplane.db
      - ENV=production
      - HOST=0.0.0.0
      - PORT=8000
    healthcheck:
      test: [ "CMD", "curl", "-f", "http://localhost:8000/api/health" ]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    depends_on:
      - qdrant
    networks:
      - devplane-network

  # Qdrant Vector Database
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./data/qdrant:/qdrant/storage
    restart: always
    environment:
      - QDRANT__SERVICE__API_KEY=${{QDRANT_KEY:-}}
    networks:
      - devplane-network

  # Cloudflare Tunnel (secure public access)
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run --token ${{TUNNEL_TOKEN}}
    restart: always
    depends_on:
      - devplane
    environment:
      - TUNNEL_TOKEN=${{TUNNEL_TOKEN}}
    networks:
      - devplane-network

  # Prometheus (metrics collection)
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./data/prometheus:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    restart: always
    networks:
      - devplane-network

  # Grafana (visualization)
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - ./data/grafana:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${{GRAFANA_PASSWORD:-admin}}
    restart: always
    networks:
      - devplane-network

networks:
  devplane-network:
    driver: bridge
'''
    
    try:
        with open(COMPOSE_PROD_FILE, 'w', encoding='utf-8') as f:
            f.write(compose_content)
        print_success(f"Generated {COMPOSE_PROD_FILE}")
        return True
    except Exception as e:
        print_error(f"Failed to generate {COMPOSE_PROD_FILE}: {e}")
        return False


def docker_compose_command() -> str:
    """Get the correct docker compose command for the platform."""
    if check_command_exists("docker-compose"):
        return "docker-compose"
    elif check_command_exists("docker"):
        # Try docker compose (newer syntax)
        return "docker compose"
    return "docker-compose"


def deploy_docker_compose(use_prod: bool = True) -> bool:
    """Deploy using docker-compose."""
    print_section("Deploying with Docker Compose")
    
    compose_file = COMPOSE_PROD_FILE if use_prod and os.path.exists(COMPOSE_PROD_FILE) else COMPOSE_FILE
    compose_cmd = docker_compose_command()
    
    print_info(f"Using compose file: {compose_file}")
    
    # Pull latest images
    print_info("Pulling latest images...")
    cmd = compose_cmd.split() + ["-f", compose_file, "pull"]
    code, stdout, stderr = run_command(cmd, capture=True)
    if code != 0:
        print_warning(f"Pull warning: {stderr}")
    
    # Build if needed
    print_info("Building services...")
    cmd = compose_cmd.split() + ["-f", compose_file, "build"]
    code, _, stderr = run_command(cmd, capture=True)
    if code != 0:
        print_error(f"Build failed: {stderr}")
        return False
    
    # Start services
    print_info("Starting services...")
    cmd = compose_cmd.split() + ["-f", compose_file, "up", "-d", "--remove-orphans"]
    code, _, stderr = run_command(cmd, capture=True)
    if code != 0:
        print_error(f"Failed to start services: {stderr}")
        return False
    
    print_success("Services deployed successfully!")
    return True


def show_status() -> bool:
    """Show deployment status."""
    print_section("Deployment Status")
    
    compose_file = COMPOSE_PROD_FILE if os.path.exists(COMPOSE_PROD_FILE) else COMPOSE_FILE
    compose_cmd = docker_compose_command()
    
    # Check if containers are running
    print_info("Container Status:")
    cmd = compose_cmd.split() + ["-f", compose_file, "ps"]
    run_command(cmd)
    
    print()
    print_info("Service Health:")
    
    # Check health endpoint
    import urllib.request
    try:
        response = urllib.request.urlopen("http://localhost:8000/api/health", timeout=5)
        data = json.loads(response.read().decode())
        print_success(f"DevPlane API: Healthy")
        print(f"  Status: {data.get('status', 'unknown')}")
        print(f"  Database: {data.get('database', 'unknown')}")
    except Exception as e:
        print_error(f"DevPlane API: Not responding ({e})")
    
    # Check Cloudflare tunnel
    env_vars = read_env_file()
    if env_vars.get("TUNNEL_TOKEN"):
        print()
        print_info("Cloudflare Tunnel:")
        print(f"  Domain: https://{DOMAIN}")
        print(f"  Tunnel Token: {'[OK] Configured' if env_vars.get('TUNNEL_TOKEN') else '[MISSING] Not configured'}")
    
    return True


def show_logs(service: Optional[str] = None, follow: bool = False) -> bool:
    """Show logs for services."""
    compose_file = COMPOSE_PROD_FILE if os.path.exists(COMPOSE_PROD_FILE) else COMPOSE_FILE
    compose_cmd = docker_compose_command()
    
    cmd = compose_cmd.split() + ["-f", compose_file, "logs"]
    
    if follow:
        cmd.append("-f")
    else:
        cmd.append("--tail=100")
    
    if service:
        cmd.append(service)
    
    print_info(f"Showing logs{' (following)' if follow else ''}...")
    run_command(cmd)
    return True


def destroy_deployment() -> bool:
    """Destroy the deployment."""
    print_section("Destroying Deployment")
    
    compose_file = COMPOSE_PROD_FILE if os.path.exists(COMPOSE_PROD_FILE) else COMPOSE_FILE
    compose_cmd = docker_compose_command()
    
    print_warning("This will stop and remove all containers and volumes!")
    response = input("Are you sure? Type 'yes' to confirm: ")
    
    if response.lower() != "yes":
        print_info("Cancelled.")
        return False
    
    # Stop services
    print_info("Stopping services...")
    cmd = compose_cmd.split() + ["-f", compose_file, "down", "--volumes", "--remove-orphans"]
    code, _, stderr = run_command(cmd, capture=True)
    if code != 0:
        print_error(f"Failed to stop services: {stderr}")
        return False
    
    print_success("Deployment destroyed.")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Main Commands
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_setup(args):
    """Setup command: Create tunnel, DNS records, and configure .env."""
    print_section("DevPlane Setup")
    
    # Check prerequisites
    print_info("Checking prerequisites...")
    
    # Check .env file exists
    if not os.path.exists(ENV_FILE):
        if os.path.exists(".env.example"):
            print_warning(".env file not found. Copying from .env.example...")
            shutil.copy(".env.example", ENV_FILE)
            print_success("Created .env from .env.example")
            print_warning("Please edit .env and add your Cloudflare credentials, then run setup again.")
            return False
        else:
            print_error("No .env or .env.example file found!")
            return False
    
    # Check Cloudflare credentials
    env_vars = read_env_file()
    required_vars = ["CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL", "CLOUDFLARE_ZONE_ID", "CLOUDFLARE_ACCOUNT_ID"]
    
    missing = [v for v in required_vars if not env_vars.get(v)]
    if missing:
        print_error(f"Missing required environment variables: {', '.join(missing)}")
        print_info("Please add them to your .env file and run setup again.")
        return False
    
    print_success("Cloudflare credentials found")
    
    # Check cloudflared (optional but recommended)
    has_cloudflared = await check_cloudflared_installed()
    if has_cloudflared:
        print_success("cloudflared CLI is installed")
    else:
        print_warning("cloudflared CLI not found (optional for Docker deployment)")
        print_cloudflared_install_instructions()
    
    # Check Docker
    if not check_command_exists("docker"):
        print_error("Docker not found! Please install Docker first.")
        return False
    print_success("Docker is installed")
    
    # Initialize Cloudflare manager
    cf = CloudflareManager()
    
    if not cf.configured:
        print_error("Cloudflare manager not properly configured")
        return False
    
    try:
        # Create or get tunnel
        tunnel = await get_or_create_tunnel(cf)
        if not tunnel:
            return False
        
        tunnel_id = tunnel.get("id")
        
        # Get tunnel token
        token = await get_tunnel_token(cf, tunnel_id)
        if not token:
            print_warning("Could not get tunnel token. You may need to create it manually.")
        else:
            # Update .env with tunnel token
            update_env_var("TUNNEL_TOKEN", token)
            print_success(f"Updated {ENV_FILE} with TUNNEL_TOKEN")
        
        # Create DNS records
        await create_dns_records(cf, tunnel_id)
        
        # Generate production compose file
        generate_prod_compose()
        
        print_section("Setup Complete")
        print_success("DevPlane is configured")
        print()
        print("Next steps:")
        print("  1. Review your .env file and add any missing API keys")
        print("  2. Run: python deploy.py deploy")
        print()
        print(f"Your site will be available at: https://{DOMAIN}")
        
    finally:
        await cf.close()
    
    return True


async def cmd_deploy(args):
    """Deploy command: Deploy with docker-compose."""
    # Check if setup has been run
    env_vars = read_env_file()
    if not env_vars.get("TUNNEL_TOKEN"):
        print_error("TUNNEL_TOKEN not found in .env")
        print_info("Please run 'python deploy.py setup' first")
        return False
    
    # Generate prod compose if it doesn't exist
    if not os.path.exists(COMPOSE_PROD_FILE):
        generate_prod_compose()
    
    # Deploy
    if deploy_docker_compose():
        print_section("Deployment Complete")
        print_success("DevPlane is now running!")
        print()
        print("Access your services:")
        print(f"  🌐 Website:    https://{DOMAIN}")
        print(f"  📊 Grafana:    http://localhost:3000")
        print(f"  📈 Prometheus: http://localhost:9090")
        print(f"  🔧 API:        http://localhost:8000")
        print()
        print("Useful commands:")
        print("  python deploy.py status    # Check status")
        print("  python deploy.py logs      # View logs")
        print("  python deploy.py logs -f   # Follow logs")
        return True
    
    return False


async def cmd_status(args):
    """Status command: Show deployment status."""
    return show_status()


async def cmd_logs(args):
    """Logs command: Show service logs."""
    return show_logs(service=args.service, follow=args.follow)


async def cmd_destroy(args):
    """Destroy command: Remove deployment."""
    return destroy_deployment()


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="DevPlane Deployment Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy.py setup              # Initial setup
  python deploy.py deploy             # Deploy services
  python deploy.py status             # Check status
  python deploy.py logs               # Show logs
  python deploy.py logs -f            # Follow logs
  python deploy.py logs devplane      # Show devplane logs only
  python deploy.py destroy            # Remove deployment
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Initial setup (tunnel, DNS, .env)")
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy with docker-compose")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show deployment status")
    
    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Show service logs")
    logs_parser.add_argument("service", nargs="?", help="Service name (optional)")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    
    # Destroy command
    destroy_parser = subparsers.add_parser("destroy", help="Remove deployment")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Run the appropriate command
    commands = {
        "setup": cmd_setup,
        "deploy": cmd_deploy,
        "status": cmd_status,
        "logs": cmd_logs,
        "destroy": cmd_destroy,
    }
    
    command_func = commands.get(args.command)
    if command_func:
        try:
            success = asyncio.run(command_func(args))
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(1)
        except Exception as e:
            print_error(f"Error: {e}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
