#!/usr/bin/env python3
"""
DevPlane Deployment Script (Unified)

This script is now a wrapper around the new deployment orchestrator.
It maintains backward compatibility with the previous CLI interface.

For advanced usage, use `python deployments/orchestrator.py` directly.
"""

import argparse
import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from devplane.core.config import load_env_file
from deployments.orchestrator import DeploymentOrchestrator

logger = logging.getLogger("deploy")


async def cmd_setup(args):
    """Setup command: provision infrastructure and generate configuration."""
    logger.info("Running setup (provision + configure)...")
    orchestrator = DeploymentOrchestrator(env="production", dry_run=args.dry_run)
    await orchestrator.provision()
    await orchestrator.configure()
    logger.info("Setup complete.")


async def cmd_deploy(args):
    """Deploy command: deploy application."""
    logger.info("Running deployment...")
    orchestrator = DeploymentOrchestrator(env="production", dry_run=args.dry_run)
    await orchestrator.deploy()
    logger.info("Deployment complete.")


async def cmd_status(args):
    """Status command: verify deployment health."""
    logger.info("Checking deployment status...")
    orchestrator = DeploymentOrchestrator(env="production", dry_run=False)
    await orchestrator.verify()


async def cmd_logs(args):
    """Logs command: show service logs."""
    # Use docker compose logs for simplicity
    import subprocess
    compose_file = "docker-compose.prod.yml" if Path("docker-compose.prod.yml").exists() else "docker-compose.yml"
    compose_cmd = "docker-compose" if shutil.which("docker-compose") else "docker compose"
    
    cmd = [compose_cmd, "-f", compose_file, "logs"]
    if args.follow:
        cmd.append("-f")
    else:
        cmd.append("--tail=100")
    
    if args.service:
        cmd.append(args.service)
    
    subprocess.run(cmd)


async def cmd_destroy(args):
    """Destroy command: rollback and remove deployment."""
    logger.warning("Destroy command is mapped to rollback phase.")
    orchestrator = DeploymentOrchestrator(env="production", dry_run=args.dry_run)
    await orchestrator.rollback()


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
    setup_parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy with docker-compose")
    deploy_parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show deployment status")
    
    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Show service logs")
    logs_parser.add_argument("service", nargs="?", help="Service name (optional)")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    
    # Destroy command
    destroy_parser = subparsers.add_parser("destroy", help="Remove deployment")
    destroy_parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Load environment variables
    load_env_file()
    
    # Map command to async function
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
            asyncio.run(command_func(args))
            sys.exit(0)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error: {e}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()