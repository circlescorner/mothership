#!/usr/bin/env python3
"""
DevPlane VPS Provisioning and Deployment Script

Automates the complete process of:
1. Creating a DigitalOcean droplet
2. Setting up the server (Docker, cloudflared)
3. Deploying DevPlane application
4. Configuring Cloudflare tunnel and DNS
5. Verifying deployment

Usage:
    python provision-and-deploy.py --ssh-key-path ~/.ssh/id_rsa
    python provision-and-deploy.py --region nyc3 --size s-4vcpu-8gb
    python provision-and-deploy.py --destroy  # Destroy droplet

Prerequisites:
    - DIGITALOCEAN_TOKEN in .env file
    - CLOUDFLARE_API_KEY, CLOUDFLARE_EMAIL, CLOUDFLARE_ZONE_ID, CLOUDFLARE_ACCOUNT_ID in .env
    - SSH key pair for server access
"""

import os
import sys
import json
import time
import argparse
import subprocess
import asyncio
import tempfile
import shutil
import tarfile
from pathlib import Path
from typing import Optional
from datetime import datetime

# Add devplane to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    import httpx
    import paramiko
    from dotenv import load_dotenv
except ImportError:
    print("Installing required packages...")
    subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "paramiko", "python-dotenv"], check=True)
    import httpx
    import paramiko
    from dotenv import load_dotenv

from devplane.infra.cloudflare import CloudflareManager

# Load environment variables
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

DOMAIN = "glondor.xyz"
TUNNEL_NAME = "devplane-vps-tunnel"
DROPLET_NAME = "devplane-vps"
DROPLET_IMAGE = "ubuntu-22-04-x64"  # Ubuntu 22.04 LTS
DROPLET_REGION = "nyc1"  # New York 1
DEPLOY_DIR = "/opt/devplane"
SSH_USER = "root"

# Cost-optimized droplet sizes
DROPLET_SIZES = {
    "s-1vcpu-1gb": {"name": "s-1vcpu-1gb", "vcpus": 1, "memory": 1, "cost_monthly": 6},
    "s-1vcpu-2gb": {"name": "s-1vcpu-2gb", "vcpus": 1, "memory": 2, "cost_monthly": 12},
    "s-2vcpu-2gb": {"name": "s-2vcpu-2gb", "vcpus": 2, "memory": 2, "cost_monthly": 18},
    "s-2vcpu-4gb": {"name": "s-2vcpu-4gb", "vcpus": 2, "memory": 4, "cost_monthly": 24},
}

# Default sizes for cost-optimized deployment
SETUP_SIZE = "s-2vcpu-4gb"  # For initial setup (more resources for setup)
RUNTIME_SIZE = "s-1vcpu-1gb"  # For permanent running instance (cost-optimized)

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
        # On Windows, handle Unicode encoding issues
        try:
            print(text)
        except UnicodeEncodeError:
            # Replace Unicode characters with ASCII alternatives
            text = text.replace("→", "->").replace("←", "<-").replace("✓", "[OK]").replace("✗", "[FAIL]")
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
    print_colored(f"[!] {message}", "warning")


def print_info(message: str):
    """Print an info message."""
    print_colored(f"[i] {message}", "cyan")


def show_cost_estimate(setup_size: str, runtime_size: str, keep_snapshot: bool = True):
    """Display cost estimate for the deployment."""
    print_section("Cost Estimate")
    
    setup_info = DROPLET_SIZES.get(setup_size, {})
    runtime_info = DROPLET_SIZES.get(runtime_size, {})
    
    setup_cost = setup_info.get("cost_monthly", 0)
    runtime_cost = runtime_info.get("cost_monthly", 0)
    
    print_colored("Droplet Sizes:", "bold")
    print(f"  Setup size:   {setup_size} ({setup_info.get('vcpus')} vCPU, {setup_info.get('memory')}GB) - ${setup_cost}/mo")
    print(f"  Runtime size: {runtime_size} ({runtime_info.get('vcpus')} vCPU, {runtime_info.get('memory')}GB) - ${runtime_cost}/mo")
    print()
    
    print_colored("Monthly Cost:", "bold")
    print(f"  After setup (resized): ${runtime_cost}/mo")
    print()
    
    if keep_snapshot:
        # Snapshots cost $0.05/GB/month, assume ~20GB for a typical droplet
        snapshot_cost = 20 * 0.05
        print_colored("Additional Costs:", "bold")
        print(f"  Snapshot storage: ~${snapshot_cost:.2f}/mo (based on ~20GB)")
        print(f"  Total monthly:    ${runtime_cost + snapshot_cost:.2f}/mo")
    else:
        print(f"  Total monthly: ${runtime_cost}/mo")
    
    print()
    print_info("Cost optimization: Using larger size for setup, then resize to smaller for permanent runtime")


# ═══════════════════════════════════════════════════════════════════════════════
# DigitalOcean API Client
# ═══════════════════════════════════════════════════════════════════════════════

class DigitalOceanClient:
    """Client for DigitalOcean API."""

    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.digitalocean.com/v2"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _api(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make a DigitalOcean API request."""
        url = f"{self.base_url}/{endpoint}"
        client = self._get_client()
        try:
            resp = await client.request(method, url, headers=self.headers, json=data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            print_error(f"DigitalOcean API error: {e.response.status_code} - {e.response.text}")
            return {"error": f"HTTP {e.response.status_code}", "details": e.response.text}
        except httpx.RequestError as e:
            print_error(f"DigitalOcean API request failed: {e}")
            return {"error": str(e)}

    async def list_ssh_keys(self) -> list[dict]:
        """List all SSH keys in the account."""
        result = await self._api("GET", "account/keys")
        return result.get("ssh_keys", [])

    async def create_droplet(
        self,
        name: str,
        region: str,
        size: str,
        image: str,
        ssh_key_ids: list[int] = None,
        tags: list[str] = None
    ) -> dict:
        """Create a new droplet."""
        data = {
            "name": name,
            "region": region,
            "size": size,
            "image": image,
            "tags": tags or ["devplane", "production"],
            "monitoring": True,
            "backups": False,
        }
        if ssh_key_ids:
            data["ssh_keys"] = ssh_key_ids

        print_info(f"Creating droplet '{name}' in {region}...")
        result = await self._api("POST", "droplets", data)

        if "droplet" in result:
            droplet = result["droplet"]
            print_success(f"Created droplet: {droplet['name']} (ID: {droplet['id']})")
            return droplet
        else:
            print_error(f"Failed to create droplet: {result.get('error', 'Unknown error')}")
            return result

    async def get_droplet(self, droplet_id: int) -> dict:
        """Get droplet details."""
        result = await self._api("GET", f"droplets/{droplet_id}")
        return result.get("droplet", {})

    async def list_droplets(self, tag: str = None) -> list[dict]:
        """List all droplets, optionally filtered by tag."""
        endpoint = "droplets"
        if tag:
            endpoint += f"?tag_name={tag}"
        result = await self._api("GET", endpoint)
        return result.get("droplets", [])

    async def delete_droplet(self, droplet_id: int) -> bool:
        """Delete a droplet."""
        print_warning(f"Deleting droplet {droplet_id}...")
        result = await self._api("DELETE", f"droplets/{droplet_id}")
        if "error" not in result:
            print_success("Droplet deleted successfully")
            return True
        else:
            print_error(f"Failed to delete droplet: {result.get('error')}")
            return False

    async def resize_droplet(self, droplet_id: int, size: str) -> bool:
        """Resize a droplet to a new size."""
        print_info(f"Resizing droplet {droplet_id} to {size}...")
        data = {"size": size, "disk": True}
        result = await self._api("POST", f"droplets/{droplet_id}/actions", data)
        
        if "error" not in result:
            action_id = result.get("action", {}).get("id")
            print_success(f"Resize initiated (action ID: {action_id})")
            # Wait for resize to complete
            await self._wait_for_action(droplet_id, action_id)
            return True
        else:
            print_error(f"Failed to resize droplet: {result.get('error')}")
            return False

    async def _wait_for_action(self, droplet_id: int, action_id: int, timeout: int = 300) -> bool:
        """Wait for a droplet action to complete."""
        print_info(f"Waiting for action {action_id} to complete...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            result = await self._api("GET", f"droplets/{droplet_id}/actions/{action_id}")
            action = result.get("action", {})
            status = action.get("status", "unknown")
            
            if status == "completed":
                print_success("Action completed successfully")
                return True
            elif status == "errored":
                print_error(f"Action failed: {action.get('message', 'Unknown error')}")
                return False
            
            print_info(f"  Action status: {status}, waiting 5s...")
            await asyncio.sleep(5)
        
        print_error(f"Timeout waiting for action after {timeout}s")
        return False

    async def create_snapshot(self, droplet_id: int, name: str) -> dict:
        """Create a snapshot of a droplet."""
        print_info(f"Creating snapshot '{name}' for droplet {droplet_id}...")
        data = {"type": "snapshot", "name": name}
        result = await self._api("POST", f"droplets/{droplet_id}/actions", data)
        
        if "error" not in result:
            action_id = result.get("action", {}).get("id")
            print_success(f"Snapshot creation initiated (action ID: {action_id})")
            # Wait for snapshot to complete
            await self._wait_for_action(droplet_id, action_id, timeout=600)
            # Get the snapshot ID from the droplet
            droplet = await self.get_droplet(droplet_id)
            snapshots = droplet.get("snapshot_ids", [])
            if snapshots:
                print_success(f"Snapshot created with ID: {snapshots[0]}")
                return {"snapshot_id": snapshots[0], "name": name}
            return {"snapshot_id": None, "name": name, "warning": "Snapshot may still be creating"}
        else:
            print_error(f"Failed to create snapshot: {result.get('error')}")
            return {"error": result.get('error')}

    async def list_snapshots(self, droplet_id: int = None) -> list[dict]:
        """List snapshots, optionally filtered by droplet."""
        if droplet_id:
            result = await self._api("GET", f"droplets/{droplet_id}/snapshots")
        else:
            result = await self._api("GET", "snapshots?resource_type=droplet")
        return result.get("snapshots", [])

    async def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        print_warning(f"Deleting snapshot {snapshot_id}...")
        result = await self._api("DELETE", f"snapshots/{snapshot_id}")
        if "error" not in result:
            print_success("Snapshot deleted successfully")
            return True
        else:
            print_error(f"Failed to delete snapshot: {result.get('error')}")
            return False

    async def create_droplet_from_snapshot(
        self,
        name: str,
        region: str,
        size: str,
        snapshot_id: str,
        ssh_key_ids: list[int] = None,
        tags: list[str] = None
    ) -> dict:
        """Create a new droplet from a snapshot."""
        data = {
            "name": name,
            "region": region,
            "size": size,
            "image": snapshot_id,
            "tags": tags or ["devplane", "production"],
            "monitoring": True,
            "backups": False,
        }
        if ssh_key_ids:
            data["ssh_keys"] = ssh_key_ids

        print_info(f"Creating droplet '{name}' from snapshot in {region}...")
        result = await self._api("POST", "droplets", data)

        if "droplet" in result:
            droplet = result["droplet"]
            print_success(f"Created droplet from snapshot: {droplet['name']} (ID: {droplet['id']})")
            return droplet
        else:
            print_error(f"Failed to create droplet from snapshot: {result.get('error', 'Unknown error')}")
            return result

    async def wait_for_droplet(
        self,
        droplet_id: int,
        timeout: int = 300,
        poll_interval: int = 10
    ) -> dict:
        """Wait for droplet to become active and return its details."""
        print_info(f"Waiting for droplet {droplet_id} to become active...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            droplet = await self.get_droplet(droplet_id)
            status = droplet.get("status")

            if status == "active":
                # Get IP address
                networks = droplet.get("networks", {})
                v4_networks = networks.get("v4", [])
                ip_address = None

                for network in v4_networks:
                    if network.get("type") == "public":
                        ip_address = network.get("ip_address")
                        break

                if ip_address:
                    print_success(f"Droplet is active! IP: {ip_address}")
                    droplet["ip_address"] = ip_address
                    return droplet

            print_info(f"  Status: {status}, waiting {poll_interval}s...")
            await asyncio.sleep(poll_interval)

        print_error(f"Timeout waiting for droplet after {timeout}s")
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# SSH Client
# ═══════════════════════════════════════════════════════════════════════════════

class SSHClient:
    """SSH client for remote server management."""

    def __init__(self, hostname: str, username: str = "root", key_path: str = None):
        self.hostname = hostname
        self.username = username
        self.key_path = key_path or os.path.expanduser("~/.ssh/id_rsa")
        self.client: Optional[paramiko.SSHClient] = None

    def connect(self, retries: int = 10, delay: int = 10) -> bool:
        """Connect to the server with retry logic."""
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        for attempt in range(retries):
            try:
                print_info(f"Connecting to {self.hostname} (attempt {attempt + 1}/{retries})...")
                self.client.connect(
                    hostname=self.hostname,
                    username=self.username,
                    key_filename=self.key_path,
                    timeout=30,
                    banner_timeout=30,
                    auth_timeout=30
                )
                print_success(f"Connected to {self.hostname}")
                return True
            except Exception as e:
                print_warning(f"Connection failed: {e}")
                if attempt < retries - 1:
                    print_info(f"Waiting {delay}s before retry...")
                    time.sleep(delay)

        print_error(f"Failed to connect after {retries} attempts")
        return False

    def disconnect(self):
        """Disconnect from the server."""
        if self.client:
            self.client.close()
            self.client = None

    def exec_command(self, command: str, timeout: int = 300) -> tuple[int, str, str]:
        """Execute a command on the remote server."""
        if not self.client:
            print_error("Not connected to server")
            return 1, "", "Not connected"

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            stdout_data = stdout.read().decode('utf-8', errors='replace')
            stderr_data = stderr.read().decode('utf-8', errors='replace')
            return exit_code, stdout_data, stderr_data
        except Exception as e:
            print_error(f"Command execution failed: {e}")
            return 1, "", str(e)

    def exec_command_sudo(self, command: str, timeout: int = 300) -> tuple[int, str, str]:
        """Execute a command with sudo on the remote server."""
        return self.exec_command(f"sudo {command}", timeout)

    def upload_file(self, local_path: str, remote_path: str):
        """Upload a file to the remote server."""
        if not self.client:
            print_error("Not connected to server")
            return False

        try:
            sftp = self.client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            print_success(f"Uploaded {local_path} to {remote_path}")
            return True
        except Exception as e:
            print_error(f"Failed to upload file: {e}")
            return False

    def upload_string(self, content: str, remote_path: str):
        """Upload string content to a file on the remote server."""
        if not self.client:
            print_error("Not connected to server")
            return False

        try:
            sftp = self.client.open_sftp()

            # Ensure directory exists
            remote_dir = os.path.dirname(remote_path)
            try:
                sftp.stat(remote_dir)
            except FileNotFoundError:
                self.exec_command(f"mkdir -p {remote_dir}")

            with sftp.file(remote_path, 'w') as f:
                f.write(content)
            sftp.close()
            return True
        except Exception as e:
            print_error(f"Failed to upload string: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str):
        """Download a file from the remote server."""
        if not self.client:
            print_error("Not connected to server")
            return False

        try:
            sftp = self.client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            print_success(f"Downloaded {remote_path} to {local_path}")
            return True
        except Exception as e:
            print_error(f"Failed to download file: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# Server Setup Functions
# ═══════════════════════════════════════════════════════════════════════════════

def setup_server(ssh: SSHClient) -> bool:
    """Set up the server with required dependencies."""
    print_section("Setting up Server")

    # Wait for any existing apt processes to finish
    print_info("Waiting for system to settle...")
    ssh.exec_command("while fuser /var/lib/dpkg/lock >/dev/null 2>&1; do sleep 5; done", timeout=120)
    ssh.exec_command("while fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do sleep 5; done", timeout=120)
    ssh.exec_command("while fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do sleep 5; done", timeout=120)

    # Update system packages (with retry)
    print_info("Updating system packages...")
    for attempt in range(3):
        exit_code, stdout, stderr = ssh.exec_command("apt-get update && apt-get upgrade -y", timeout=300)
        if exit_code == 0:
            break
        print_warning(f"Update attempt {attempt+1} failed, retrying...")
        ssh.exec_command("sleep 10")
    if exit_code != 0:
        print_warning(f"System update had issues: {stderr[:200]}")
    else:
        print_success("System packages updated")

    # Install required packages (using correct package names)
    print_info("Installing required packages...")
    # Use python3-full instead of python3-pip and python3-venv (Debian 12 changed these)
    packages = "curl wget git nano htop ufw fail2ban python3 python3-venv pip"
    exit_code, _, stderr = ssh.exec_command(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages}", timeout=180)
    if exit_code != 0:
        print_warning(f"Package installation had issues: {stderr[:200]}")
    else:
        print_success("Required packages installed")

    # Install Docker (using official install script)
    print_info("Installing Docker...")
    docker_install_script = """
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
usermod -aG docker root
systemctl enable docker
systemctl start docker
"""
    exit_code, _, stderr = ssh.exec_command(docker_install_script.strip(), timeout=300)
    if exit_code != 0:
        print_error(f"Docker installation failed: {stderr[:200]}")
        return False
    print_success("Docker installed")

    # Install Docker Compose
    print_info("Installing Docker Compose...")
    compose_install = """
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose
"""
    exit_code, _, stderr = ssh.exec_command(compose_install.strip(), timeout=120)
    if exit_code != 0:
        print_warning(f"Docker Compose installation had issues: {stderr}")
    else:
        print_success("Docker Compose installed")

    # Install cloudflared
    print_info("Installing cloudflared...")
    cloudflared_install = """
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared-linux-amd64.deb
rm cloudflared-linux-amd64.deb
"""
    exit_code, _, stderr = ssh.exec_command(cloudflared_install.strip(), timeout=120)
    if exit_code != 0:
        print_warning(f"cloudflared installation had issues: {stderr}")
    else:
        print_success("cloudflared installed")

    # Create directory structure
    print_info("Creating directory structure...")
    dirs = f"""
mkdir -p {DEPLOY_DIR}
mkdir -p {DEPLOY_DIR}/data
mkdir -p {DEPLOY_DIR}/data/qdrant
mkdir -p {DEPLOY_DIR}/data/prometheus
mkdir -p {DEPLOY_DIR}/data/grafana
mkdir -p {DEPLOY_DIR}/devplane
mkdir -p {DEPLOY_DIR}/static
mkdir -p {DEPLOY_DIR}/monitoring
"""
    exit_code, _, stderr = ssh.exec_command(dirs.strip(), timeout=30)
    if exit_code != 0:
        print_error(f"Directory creation failed: {stderr}")
        return False
    print_success("Directory structure created")

    # Configure firewall
    print_info("Configuring firewall...")
    firewall_setup = """
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
"""
    exit_code, _, stderr = ssh.exec_command(firewall_setup.strip(), timeout=60)
    if exit_code != 0:
        print_warning(f"Firewall configuration had issues: {stderr}")
    else:
        print_success("Firewall configured")

    return True


def copy_project_files(ssh: SSHClient, local_dir: str) -> bool:
    """Copy project files to the server."""
    print_section("Copying Project Files")

    local_path = Path(local_dir)

    # Files to copy
    files_to_copy = [
        "main.py",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
        ".env",
        "deploy.py",
    ]

    # Directories to copy
    dirs_to_copy = [
        "devplane",
        "static",
        "monitoring",
    ]

    # Copy individual files
    for file in files_to_copy:
        local_file = local_path / file
        if local_file.exists():
            remote_file = f"{DEPLOY_DIR}/{file}"
            if not ssh.upload_file(str(local_file), remote_file):
                print_warning(f"Failed to upload {file}")
        else:
            print_warning(f"Local file not found: {file}")

    # Copy directories recursively
    for dir_name in dirs_to_copy:
        local_dir_path = local_path / dir_name
        if local_dir_path.exists():
            print_info(f"Copying directory: {dir_name}")

            # Create tar archive locally
            with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # Create tar archive
                import tarfile
                with tarfile.open(tmp_path, "w:gz") as tar:
                    tar.add(local_dir_path, arcname=dir_name)

                # Upload archive
                remote_archive = f"/tmp/{dir_name}.tar.gz"
                if ssh.upload_file(tmp_path, remote_archive):
                    # Extract on server
                    exit_code, _, stderr = ssh.exec_command(
                        f"cd {DEPLOY_DIR} && tar -xzf {remote_archive} && rm {remote_archive}",
                        timeout=60
                    )
                    if exit_code == 0:
                        print_success(f"Copied directory: {dir_name}")
                    else:
                        print_error(f"Failed to extract {dir_name}: {stderr}")

                os.unlink(tmp_path)
            except Exception as e:
                print_error(f"Failed to copy directory {dir_name}: {e}")
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        else:
            print_warning(f"Local directory not found: {dir_name}")

    # Set permissions
    ssh.exec_command(f"chmod -R 755 {DEPLOY_DIR}")

    print_success("Project files copied")
    return True


def run_remote_deployment(ssh: SSHClient, tunnel_token: str) -> bool:
    """Run deployment commands on the remote server."""
    print_section("Running Remote Deployment")

    # Update .env with tunnel token on server
    print_info("Configuring environment...")
    ssh.exec_command(f"sed -i 's|^TUNNEL_TOKEN=.*|TUNNEL_TOKEN={tunnel_token}|' {DEPLOY_DIR}/.env")
    ssh.exec_command(f"sed -i 's|^ENV=.*|ENV=production|' {DEPLOY_DIR}/.env")
    ssh.exec_command(f"sed -i 's|^HOST=.*|HOST=0.0.0.0|' {DEPLOY_DIR}/.env")
    print_success("Environment configured")

    # Generate production compose file on server
    print_info("Generating production compose file...")
    compose_content = f'''# ═══════════════════════════════════════════════════════════════════════════════
# DevPlane Production Docker Compose Configuration
# Auto-generated on server at {datetime.now().isoformat()}
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
      - "127.0.0.1:9090:9090"
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
      - "127.0.0.1:3000:3000"
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

    ssh.upload_string(compose_content, f"{DEPLOY_DIR}/docker-compose.prod.yml")
    print_success("Production compose file created")

    # Deploy with Docker Compose
    print_info("Starting Docker Compose deployment...")
    deploy_cmd = f"""
cd {DEPLOY_DIR}
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d --remove-orphans
"""
    exit_code, stdout, stderr = ssh.exec_command(deploy_cmd.strip(), timeout=300)

    if exit_code != 0:
        print_error(f"Deployment failed: {stderr}")
        print_info(f"Stdout: {stdout}")
        return False

    print_success("Docker Compose deployment completed")
    return True


def verify_deployment(ssh: SSHClient) -> dict:
    """Verify that the deployment is working."""
    print_section("Verifying Deployment")

    results = {
        "docker_running": False,
        "containers": [],
        "api_healthy": False,
        "tunnel_running": False,
    }

    # Check Docker is running
    exit_code, stdout, _ = ssh.exec_command("docker ps --format '{{.Names}}'")
    if exit_code == 0:
        results["docker_running"] = True
        results["containers"] = [c.strip() for c in stdout.strip().split('\n') if c.strip()]
        print_success(f"Docker is running with {len(results['containers'])} containers")
        for container in results["containers"]:
            print_info(f"  - {container}")
    else:
        print_error("Docker is not running properly")

    # Check API health
    print_info("Checking API health...")
    exit_code, stdout, _ = ssh.exec_command("curl -sf http://localhost:8000/api/health")
    if exit_code == 0:
        try:
            health_data = json.loads(stdout)
            results["api_healthy"] = True
            print_success(f"API is healthy: {health_data}")
        except json.JSONDecodeError:
            print_warning("API responded but with invalid JSON")
    else:
        print_error("API health check failed")

    # Check tunnel
    print_info("Checking Cloudflare tunnel...")
    exit_code, stdout, _ = ssh.exec_command("docker ps | grep cloudflared")
    if exit_code == 0:
        results["tunnel_running"] = True
        print_success("Cloudflare tunnel container is running")
    else:
        print_warning("Cloudflare tunnel container not found")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Main Provisioning Workflow
# ═══════════════════════════════════════════════════════════════════════════════

async def provision_and_deploy(args):
    """Main provisioning and deployment workflow."""
    print_section("DevPlane VPS Provisioning & Deployment")

    # Check environment variables
    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found in environment")
        print_info("Please add it to your .env file")
        return False

    cf_required = ["CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL", "CLOUDFLARE_ZONE_ID", "CLOUDFLARE_ACCOUNT_ID"]
    cf_missing = [v for v in cf_required if not os.environ.get(v)]
    if cf_missing:
        print_error(f"Missing Cloudflare environment variables: {', '.join(cf_missing)}")
        return False

    # Check SSH key
    ssh_key_path = args.ssh_key_path or os.path.expanduser("~/.ssh/id_rsa")
    if not os.path.exists(ssh_key_path):
        print_error(f"SSH key not found: {ssh_key_path}")
        print_info("Generate one with: ssh-keygen -t rsa -b 4096 -C 'your-email@example.com'")
        return False

    print_success(f"Using SSH key: {ssh_key_path}")

    # Initialize clients
    do = DigitalOceanClient(do_token)
    cf = CloudflareManager()

    droplet = None
    ssh = None

    try:
        # Step 1: Create or get SSH key on DigitalOcean
        print_section("SSH Key Setup")
        ssh_keys = await do.list_ssh_keys()

        ssh_key_id = None
        with open(f"{ssh_key_path}.pub", 'r') as f:
            local_pubkey = f.read().strip()

        for key in ssh_keys:
            if key.get("public_key") == local_pubkey:
                ssh_key_id = key.get("id")
                print_success(f"Found existing SSH key: {key.get('name')} (ID: {ssh_key_id})")
                break

        if not ssh_key_id:
            print_info("Uploading SSH key to DigitalOcean...")
            key_name = f"devplane-key-{datetime.now().strftime('%Y%m%d')}"
            result = await do._api("POST", "account/keys", {
                "name": key_name,
                "public_key": local_pubkey
            })
            if "ssh_key" in result:
                ssh_key_id = result["ssh_key"]["id"]
                print_success(f"Uploaded SSH key (ID: {ssh_key_id})")
            else:
                print_warning("Could not upload SSH key, proceeding without it")

        # Step 2: Create Cloudflare tunnel
        print_section("Cloudflare Tunnel Setup")

        print_info("Creating Cloudflare tunnel...")
        tunnel = await get_or_create_tunnel(cf)
        if not tunnel:
            print_error("Failed to create tunnel")
            return False

        tunnel_id = tunnel.get("id")
        tunnel_token = await get_tunnel_token(cf, tunnel_id)
        if not tunnel_token:
            print_error("Failed to get tunnel token")
            return False

        print_success(f"Tunnel ready: {tunnel['name']}")

        # Step 3: Create DNS records
        print_section("DNS Configuration")
        await create_dns_records(cf, tunnel_id)

        # Step 4: Create droplet
        print_section("DigitalOcean Droplet Creation")

        region = args.region or DROPLET_REGION
        
        # Use cost-optimized sizes
        setup_size = args.setup_size or SETUP_SIZE
        runtime_size = args.runtime_size or RUNTIME_SIZE
        
        # Show cost estimate
        show_cost_estimate(setup_size, runtime_size, keep_snapshot=not args.no_snapshot)
        
        # Determine initial size
        size = setup_size
        
        # Check for existing droplet
        existing = await do.list_droplets(tag="devplane")
        existing_droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)

        if existing_droplet and not args.recreate:
            print_info(f"Found existing droplet: {existing_droplet['name']}")
            if args.destroy:
                await do.delete_droplet(existing_droplet['id'])
                print_info("Droplet destroyed. Exiting.")
                return True

            droplet = existing_droplet
            # Get IP address
            networks = droplet.get("networks", {})
            v4_networks = networks.get("v4", [])
            for network in v4_networks:
                if network.get("type") == "public":
                    droplet["ip_address"] = network.get("ip_address")
                    break
        else:
            if existing_droplet and args.recreate:
                print_warning("Recreating existing droplet...")
                await do.delete_droplet(existing_droplet['id'])
                await asyncio.sleep(10)  # Wait for deletion to start

            # Create new droplet
            droplet = await do.create_droplet(
                name=DROPLET_NAME,
                region=region,
                size=size,
                image=DROPLET_IMAGE,
                ssh_key_ids=[ssh_key_id] if ssh_key_id else [],
                tags=["devplane", "production"]
            )

            if "id" not in droplet:
                print_error("Failed to create droplet")
                return False

            # Wait for droplet to be ready
            droplet = await do.wait_for_droplet(droplet["id"], timeout=300)
            if not droplet.get("ip_address"):
                print_error("Droplet did not become ready")
                return False

        droplet_ip = droplet.get("ip_address")
        print_success(f"Droplet ready: {droplet_ip}")

        # Step 5: SSH into server and set up
        print_section("Server Setup")
        ssh = SSHClient(droplet_ip, SSH_USER, ssh_key_path)

        if not ssh.connect(retries=15, delay=10):
            print_error("Failed to connect to server")
            return False

        # Run server setup
        setup_success = False
        try:
            if not setup_server(ssh):
                print_error("Server setup failed")
            else:
                setup_success = True
        except Exception as e:
            print_error(f"Server setup error: {e}")

        if setup_success:
            # Copy project files
            if not copy_project_files(ssh, args.project_dir or "."):
                print_warning("Some project files may not have copied correctly")

            # Run deployment
            if not run_remote_deployment(ssh, tunnel_token):
                print_error("Remote deployment failed")
            else:
                # Wait for services to start
                print_info("Waiting for services to start...")
                time.sleep(30)

                # Verify deployment
                results = verify_deployment(ssh)

                # Cost optimization: Resize to runtime size after setup
                if setup_size != runtime_size and not args.no_resize:
                    print_section("Cost Optimization: Resizing Droplet")
                    print_info(f"Resizing from {setup_size} to {runtime_size} for cost savings...")
                    
                    # Stop Docker services before resize
                    print_info("Stopping services before resize...")
                    ssh.exec_command(f"cd {DEPLOY_DIR} && docker-compose -f docker-compose.prod.yml down", timeout=60)
                    
                    # Resize the droplet
                    if await do.resize_droplet(droplet["id"], runtime_size):
                        print_success(f"Resized to {runtime_size}")
                        # Wait for droplet to come back online
                        print_info("Waiting for droplet to come back online...")
                        await asyncio.sleep(30)
                        droplet = await do.wait_for_droplet(droplet["id"], timeout=300)
                        if droplet.get("ip_address"):
                            droplet_ip = droplet["ip_address"]
                            # Reconnect SSH
                            ssh.disconnect()
                            ssh = SSHClient(droplet_ip, SSH_USER, ssh_key_path)
                            if not ssh.connect(retries=15, delay=10):
                                print_warning("Failed to reconnect after resize")
                            else:
                                # Restart services
                                print_info("Restarting services...")
                                ssh.exec_command(f"cd {DEPLOY_DIR} && docker-compose -f docker-compose.prod.yml up -d", timeout=120)
                                time.sleep(20)
                    else:
                        print_warning("Resize failed, keeping original size")

                # Create snapshot for fast recovery (if not disabled)
                if not args.no_snapshot and setup_size != runtime_size:
                    print_section("Creating Snapshot for Fast Recovery")
                    snapshot_name = f"devplane-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    snapshot_result = await do.create_snapshot(droplet["id"], snapshot_name)
                    if "snapshot_id" in snapshot_result and snapshot_result["snapshot_id"]:
                        print_success(f"Snapshot created: {snapshot_name} (ID: {snapshot_result['snapshot_id']})")
                        print_info("Use --restore to quickly spin up from this snapshot")
                    else:
                        print_warning("Snapshot creation may still be in progress")

                # Show final status
                print_section("Deployment Complete")
                print_success("DevPlane has been deployed!")
                print()
                print_colored("Access Information:", "bold")
                print(f"  🌐 Website:      https://{DOMAIN}")
                print(f"  📊 Grafana:      http://{droplet_ip}:3000")
                print(f"  📈 Prometheus:   http://{droplet_ip}:9090")
                print(f"  🔧 API:          http://{droplet_ip}:8000")
                print(f"  🖥️  SSH:          ssh root@{droplet_ip}")
                print()
                print_colored("Droplet Information:", "bold")
                print(f"  Name:     {droplet.get('name')}")
                print(f"  IP:       {droplet_ip}")
                print(f"  Region:   {droplet.get('region', {}).get('name', region)}")
                print(f"  Size:     {droplet.get('size', {}).get('slug', size)}")
                print()
                print_colored("Useful Commands:", "bold")
                print(f"  ssh root@{droplet_ip}")
                print(f"  cd {DEPLOY_DIR} && docker-compose -f docker-compose.prod.yml logs -f")
                print()

                ssh.disconnect()
                return True

        ssh.disconnect()

    except KeyboardInterrupt:
        print("\nCancelled by user.")
        return False
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await do.close()
        await cf.close()


async def destroy_droplet():
    """Destroy the DevPlane droplet."""
    print_section("Destroying DevPlane Droplet")

    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found")
        return False

    do = DigitalOceanClient(do_token)

    try:
        existing = await do.list_droplets(tag="devplane")
        droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)

        if not droplet:
            print_warning("No DevPlane droplet found to destroy")
            return True

        print_warning(f"This will permanently delete droplet: {droplet['name']} (ID: {droplet['id']})")
        confirm = input("Type 'destroy' to confirm: ")

        if confirm.lower() == "destroy":
            await do.delete_droplet(droplet['id'])
            print_success("Droplet destroyed")
            return True
        else:
            print_info("Cancelled")
            return False

    finally:
        await do.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Cloudflare Helper Functions (from deploy.py)
# ═══════════════════════════════════════════════════════════════════════════════

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
    print_info("Creating DNS records...")

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

        print_info(f"  Creating: {name} → {target}")

        result = await cf.create_dns_record(name, target, record_type="CNAME", proxied=True)

        if "error" in result:
            # Check if it's a duplicate record error
            if "already exists" in str(result.get("error", "")).lower():
                print_warning(f"    DNS record already exists: {name}")
            else:
                print_error(f"    Failed to create DNS record {name}: {result['error']}")
                success = False
        else:
            print_success(f"    Created: {name}")

    return success


# ═══════════════════════════════════════════════════════════════════════════════
# Additional Commands: Resize, Snapshot, Restore
# ═══════════════════════════════════════════════════════════════════════════════

async def resize_droplet_command(args):
    """Resize the existing droplet to a new size."""
    print_section("Resize Droplet")
    
    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found")
        return False
    
    do = DigitalOceanClient(do_token)
    
    try:
        # Find existing droplet
        existing = await do.list_droplets(tag="devplane")
        droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)
        
        if not droplet:
            print_error(f"No droplet found with name: {DROPLET_NAME}")
            return False
        
        current_size = droplet.get("size", {}).get("slug", "unknown")
        new_size = args.size
        
        print_info(f"Current size: {current_size}")
        print_info(f"New size: {new_size}")
        
        # Show cost difference
        current_cost = DROPLET_SIZES.get(current_size, {}).get("cost_monthly", 0)
        new_cost = DROPLET_SIZES.get(new_size, {}).get("cost_monthly", 0)
        
        print_colored("Cost Impact:", "bold")
        print(f"  Current: ${current_cost}/mo")
        print(f"  New:     ${new_cost}/mo")
        print(f"  Savings: ${current_cost - new_cost}/mo")
        print()
        
        # Confirm
        confirm = input(f"Resize from {current_size} to {new_size}? (yes/no): ")
        if confirm.lower() != "yes":
            print_info("Cancelled")
            return False
        
        # Get droplet IP for SSH
        networks = droplet.get("networks", {})
        v4_networks = networks.get("v4", [])
        droplet_ip = None
        for network in v4_networks:
            if network.get("type") == "public":
                droplet_ip = network.get("ip_address")
                break
        
        # Stop services if we have IP
        if droplet_ip:
            ssh_key_path = args.ssh_key_path or os.path.expanduser("~/.ssh/id_rsa")
            ssh = SSHClient(droplet_ip, SSH_USER, ssh_key_path)
            if ssh.connect(retries=5, delay=5):
                print_info("Stopping services before resize...")
                ssh.exec_command(f"cd {DEPLOY_DIR} && docker-compose -f docker-compose.prod.yml down", timeout=60)
                ssh.disconnect()
        
        # Resize
        success = await do.resize_droplet(droplet["id"], new_size)
        
        if success:
            print_success("Droplet resized successfully!")
            # Wait for it to come back
            print_info("Waiting for droplet to come back online...")
            await asyncio.sleep(30)
            droplet = await do.wait_for_droplet(droplet["id"], timeout=300)
            
            if droplet.get("ip_address"):
                new_ip = droplet["ip_address"]
                print_success(f"Droplet is back online at: {new_ip}")
                
                # Restart services
                ssh = SSHClient(new_ip, SSH_USER, ssh_key_path)
                if ssh.connect(retries=5, delay=5):
                    print_info("Restarting services...")
                    ssh.exec_command(f"cd {DEPLOY_DIR} && docker-compose -f docker-compose.prod.yml up -d", timeout=120)
                    ssh.disconnect()
        
        return success
        
    finally:
        await do.close()


async def snapshot_command(args):
    """Create a snapshot of the current droplet."""
    print_section("Create Snapshot")
    
    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found")
        return False
    
    do = DigitalOceanClient(do_token)
    
    try:
        # Find existing droplet
        existing = await do.list_droplets(tag="devplane")
        droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)
        
        if not droplet:
            print_error(f"No droplet found with name: {DROPLET_NAME}")
            return False
        
        snapshot_name = args.name or f"devplane-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        print_info(f"Creating snapshot '{snapshot_name}' from droplet {droplet['name']}...")
        
        result = await do.create_snapshot(droplet["id"], snapshot_name)
        
        if "snapshot_id" in result and result["snapshot_id"]:
            print_success(f"Snapshot created successfully!")
            print(f"  Snapshot ID: {result['snapshot_id']}")
            print(f"  Name: {result['name']}")
            print_info("Use --restore to create a new droplet from this snapshot")
            return True
        else:
            print_error("Failed to create snapshot")
            return False
            
    finally:
        await do.close()


async def list_snapshots_command(args):
    """List available snapshots."""
    print_section("List Snapshots")
    
    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found")
        return False
    
    do = DigitalOceanClient(do_token)
    
    try:
        # Find existing droplet
        existing = await do.list_droplets(tag="devplane")
        droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)
        
        if droplet:
            snapshots = await do.list_snapshots(droplet["id"])
        else:
            # List all snapshots
            snapshots = await do.list_snapshots()
        
        # Filter for devplane snapshots
        devplane_snapshots = [s for s in snapshots if "devplane" in s.get("name", "").lower()]
        
        if not devplane_snapshots:
            print_info("No DevPlane snapshots found")
            return True
        
        print_colored(f"Found {len(devplane_snapshots)} snapshot(s):", "bold")
        for snap in devplane_snapshots:
            size_gb = snap.get("size_gigabytes", 0)
            created = snap.get("created_at", "unknown")
            print(f"  - {snap['name']}")
            print(f"    ID: {snap['id']}")
            print(f"    Size: {size_gb}GB")
            print(f"    Created: {created}")
            print()
        
        return True
        
    finally:
        await do.close()


async def restore_command(args):
    """Restore droplet from a snapshot."""
    print_section("Restore from Snapshot")
    
    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found")
        return False
    
    do = DigitalOceanClient(do_token)
    
    try:
        # Get snapshot ID
        snapshot_id = args.snapshot_id
        
        if not snapshot_id:
            # List available snapshots
            existing = await do.list_droplets(tag="devplane")
            droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)
            
            if droplet:
                snapshots = await do.list_snapshots(droplet["id"])
            else:
                snapshots = await do.list_snapshots()
            
            devplane_snapshots = [s for s in snapshots if "devplane" in s.get("name", "").lower()]
            
            if not devplane_snapshots:
                print_error("No DevPlane snapshots found")
                return False
            
            print_colored("Available snapshots:", "bold")
            for i, snap in enumerate(devplane_snapshots):
                print(f"  {i+1}. {snap['name']} (ID: {snap['id']})")
            
            choice = input("\nEnter snapshot number to restore: ")
            try:
                idx = int(choice) - 1
                snapshot_id = devplane_snapshots[idx]["id"]
            except (ValueError, IndexError):
                print_error("Invalid selection")
                return False
        
        # Get size
        size = args.size or RUNTIME_SIZE
        
        # Show cost estimate
        size_info = DROPLET_SIZES.get(size, {})
        print_colored("Restore Details:", "bold")
        print(f"  Snapshot: {snapshot_id}")
        print(f"  Size: {size} ({size_info.get('vcpus')} vCPU, {size_info.get('memory')}GB)")
        print(f"  Cost: ${size_info.get('cost_monthly', 0)}/mo")
        print()
        
        # Confirm
        confirm = input("Create new droplet from snapshot? (yes/no): ")
        if confirm.lower() != "yes":
            print_info("Cancelled")
            return False
        
        # Get SSH key
        ssh_key_path = args.ssh_key_path or os.path.expanduser("~/.ssh/id_rsa")
        if not os.path.exists(ssh_key_path):
            print_error(f"SSH key not found: {ssh_key_path}")
            return False
        
        with open(f"{ssh_key_path}.pub", 'r') as f:
            local_pubkey = f.read().strip()
        
        ssh_keys = await do.list_ssh_keys()
        ssh_key_id = None
        for key in ssh_keys:
            if key.get("public_key") == local_pubkey:
                ssh_key_id = key.get("id")
                break
        
        if not ssh_key_id:
            print_info("Uploading SSH key to DigitalOcean...")
            key_name = f"devplane-key-{datetime.now().strftime('%Y%m%d')}"
            result = await do._api("POST", "account/keys", {
                "name": key_name,
                "public_key": local_pubkey
            })
            if "ssh_key" in result:
                ssh_key_id = result["ssh_key"]["id"]
        
        # Create droplet from snapshot
        region = args.region or DROPLET_REGION
        new_name = f"{DROPLET_NAME}-restored"
        
        droplet = await do.create_droplet_from_snapshot(
            name=new_name,
            region=region,
            size=size,
            snapshot_id=snapshot_id,
            ssh_key_ids=[ssh_key_id] if ssh_key_id else [],
            tags=["devplane", "restored"]
        )
        
        if "id" not in droplet:
            print_error("Failed to create droplet from snapshot")
            return False
        
        # Wait for droplet
        droplet = await do.wait_for_droplet(droplet["id"], timeout=300)
        droplet_ip = droplet.get("ip_address")
        
        if not droplet_ip:
            print_error("Droplet did not become ready")
            return False
        
        print_success(f"Droplet restored successfully!")
        print(f"  IP: {droplet_ip}")
        print(f"  SSH: ssh root@{droplet_ip}")
        
        return True
        
    finally:
        await do.close()


async def destroy_keep_snapshot_command(args):
    """Destroy droplet but keep the most recent snapshot."""
    print_section("Destroy Droplet (Keep Snapshot)")
    
    do_token = os.environ.get("DIGITALOCEAN_TOKEN")
    if not do_token:
        print_error("DIGITALOCEAN_TOKEN not found")
        return False
    
    do = DigitalOceanClient(do_token)
    
    try:
        # Find existing droplet
        existing = await do.list_droplets(tag="devplane")
        droplet = next((d for d in existing if d.get("name") == DROPLET_NAME), None)
        
        if not droplet:
            print_warning(f"No droplet found with name: {DROPLET_NAME}")
            return True
        
        print_warning(f"This will permanently delete droplet: {droplet['name']} (ID: {droplet['id']})")
        
        # Create snapshot first if requested
        if not args.no_snapshot:
            snapshot_name = f"devplane-final-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            print_info(f"Creating final snapshot '{snapshot_name}' before destroy...")
            result = await do.create_snapshot(droplet["id"], snapshot_name)
            if "snapshot_id" in result and result["snapshot_id"]:
                print_success(f"Final snapshot created: {result['snapshot_id']}")
            else:
                print_warning("Could not create final snapshot, proceeding with destroy anyway")
        
        confirm = input("Type 'destroy' to confirm: ")
        
        if confirm.lower() == "destroy":
            await do.delete_droplet(droplet['id'])
            print_success("Droplet destroyed")
            return True
        else:
            print_info("Cancelled")
            return False
            
    finally:
        await do.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="DevPlane VPS Provisioning and Deployment Script - Cost Optimized",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
    (default)          Deploy a new droplet with cost-optimized settings
    resize             Resize the existing droplet
    snapshot           Create a snapshot of the current droplet
    snapshots          List available snapshots
    restore            Restore droplet from a snapshot
    destroy            Destroy the droplet (with option to keep snapshot)

Examples:
    # Deploy with cost-optimized defaults (2CPU/4GB setup, then resize to 1CPU/1GB)
    python provision-and-deploy.py
    
    # Custom setup and runtime sizes
    python provision-and-deploy.py --setup-size s-2vcpu-4gb --runtime-size s-1vcpu-2gb
    
    # Create a snapshot
    python provision-and-deploy.py snapshot
    
    # List snapshots
    python provision-and-deploy.py snapshots
    
    # Restore from snapshot
    python provision-and-deploy.py restore --snapshot-id <id>
    
    # Resize to a different size
    python provision-and-deploy.py resize --size s-2vcpu-4gb
    
    # Destroy but keep snapshot
    python provision-and-deploy.py destroy

Available Sizes:
    s-1vcpu-1gb  - $6/month  (default runtime)
    s-1vcpu-2gb  - $12/month
    s-2vcpu-2gb  - $18/month
    s-2vcpu-4gb  - $24/month  (default setup)
        """
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Default deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy a new droplet")
    deploy_parser.add_argument("--region", default=DROPLET_REGION, help=f"DigitalOcean region")
    deploy_parser.add_argument("--setup-size", default=SETUP_SIZE, help=f"Size for initial setup (default: {SETUP_SIZE})")
    deploy_parser.add_argument("--runtime-size", default=RUNTIME_SIZE, help=f"Size for permanent running (default: {RUNTIME_SIZE})")
    deploy_parser.add_argument("--ssh-key-path", default=None, help="Path to SSH private key")
    deploy_parser.add_argument("--project-dir", default=".", help="Path to project directory")
    deploy_parser.add_argument("--recreate", action="store_true", help="Recreate droplet if exists")
    deploy_parser.add_argument("--no-snapshot", action="store_true", help="Don't create snapshot after deploy")
    deploy_parser.add_argument("--no-resize", action="store_true", help="Don't resize after setup")
    
    # Resize command
    resize_parser = subparsers.add_parser("resize", help="Resize the droplet")
    resize_parser.add_argument("--size", required=True, help="New droplet size (e.g., s-1vcpu-1gb)")
    resize_parser.add_argument("--ssh-key-path", default=None, help="Path to SSH private key")
    
    # Snapshot command
    snapshot_parser = subparsers.add_parser("snapshot", help="Create a snapshot")
    snapshot_parser.add_argument("--name", help="Snapshot name")
    
    # List snapshots command
    subparsers.add_parser("snapshots", help="List available snapshots")
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from snapshot")
    restore_parser.add_argument("--snapshot-id", help="Snapshot ID to restore from")
    restore_parser.add_argument("--size", default=RUNTIME_SIZE, help="Size for restored droplet")
    restore_parser.add_argument("--region", default=DROPLET_REGION, help="Region for restored droplet")
    restore_parser.add_argument("--ssh-key-path", default=None, help="Path to SSH private key")
    
    # Destroy command
    destroy_parser = subparsers.add_parser("destroy", help="Destroy droplet")
    destroy_parser.add_argument("--no-snapshot", action="store_true", help="Don't create final snapshot")
    
    # Backwards compatibility: also support positional args for common operations
    parser.add_argument("--region", default=DROPLET_REGION, help="DigitalOcean region")
    parser.add_argument("--setup-size", default=SETUP_SIZE, help=f"Size for initial setup (default: {SETUP_SIZE})")
    parser.add_argument("--runtime-size", default=RUNTIME_SIZE, help=f"Size for permanent running (default: {RUNTIME_SIZE})")
    parser.add_argument("--size", help="Droplet size (for backwards compatibility)")
    parser.add_argument("--ssh-key-path", default=None, help="Path to SSH private key")
    parser.add_argument("--project-dir", default=".", help="Path to project directory")
    parser.add_argument("--recreate", action="store_true", help="Recreate droplet if exists")
    parser.add_argument("--destroy", action="store_true", help="Destroy the droplet")
    parser.add_argument("--no-snapshot", action="store_true", help="Don't create snapshot")
    parser.add_argument("--no-resize", action="store_true", help="Don't resize after setup")
    parser.add_argument("--snapshot-id", help="Snapshot ID for restore")
    parser.add_argument("cmd", nargs="?", help="Command (resize/snapshot/snapshots/restore/destroy)")

    args = parser.parse_args()
    
    # Handle command
    command = args.command or args.cmd
    
    try:
        if command == "resize":
            success = asyncio.run(resize_droplet_command(args))
        elif command == "snapshot":
            success = asyncio.run(snapshot_command(args))
        elif command == "snapshots":
            success = asyncio.run(list_snapshots_command(args))
        elif command == "restore":
            success = asyncio.run(restore_command(args))
        elif command == "destroy":
            success = asyncio.run(destroy_keep_snapshot_command(args))
        elif args.destroy:
            # Backwards compatibility
            success = asyncio.run(destroy_droplet())
        else:
            # Default: deploy
            success = asyncio.run(provision_and_deploy(args))
        
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        print_error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
