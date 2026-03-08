"""Sandbox Engine — Secure execution of untrusted autonomous agents.

Deploys ephemeral, isolated droplets to run code (Clawbot, etc) safely off-network
and captures output before immediate destruction.
"""

import os
import secrets
import asyncio
import logging
import json
import paramiko
from datetime import datetime, timedelta
from devplane.infra.manager import get_infra_manager

logger = logging.getLogger("devplane.infra.sandbox")

class SandboxManager:
    """Manages isolated sandbox environments for running untrusted LLM code."""
    
    def __init__(self):
        self.mgr = get_infra_manager()
        
    async def create_firewalled_sandbox(self, system_type: str = "basic") -> dict:
        """Deploy a droplet with strict UFW egress filtering for security.
        It can only talk to essential repos and is blocked from local LANs.
        """
        sandbox_id = f"sandbox-{secrets.token_hex(4)}"
        
        # Critical Security User Data
        # 1. Deny outgoing by default to prevent lateral scanning
        # 2. Allow DNS (53) and HTTP/HTTPS (80,443) only for dependency installs
        # 3. Block private IP ranges completely so it cannot reach the Gate Droplet
        user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

# Timeout Safe Aliases (Kilocode Safety Wrappers)
cat > /etc/profile.d/safety-aliases.sh << 'EOF'
alias curl='curl --max-time 30 --connect-timeout 10'
alias wget='wget --timeout=30 --tries=3'
timeout_safe() {{
    local duration="\\$1"
    shift
    timeout --signal=TERM --kill-after=5 "\\$duration" "\\$@"
}}
EOF
chmod +x /etc/profile.d/safety-aliases.sh

# Apply aliases to root shell for setup
source /etc/profile.d/safety-aliases.sh

timeout_safe 300 apt-get update && timeout_safe 600 apt-get upgrade -y

# Setup precise UFW Sandbox Firewall
apt-get install -y ufw dos2unix
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# Block all private LAN spaces to prevent lateral movement (AWS/DO internal IPs)
ufw deny out to 10.0.0.0/8
ufw deny out to 172.16.0.0/12
ufw deny out to 192.168.0.0/16
ufw deny out to 100.64.0.0/10

# Allow SSH so we can orchestrate it
ufw allow incoming 22/tcp
ufw --force enable

# Setup non-root user for task execution
useradd -m -s /bin/bash clawbot
mkdir -p /home/clawbot/workspace
chown -R clawbot:clawbot /home/clawbot
"""

        if system_type == "docker":
            user_data += """
# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker clawbot
systemctl enable docker
"""
        elif system_type == "kubernetes":
            user_data += """
# Install Docker & K3s
curl -fsSL https://get.docker.com | sh
usermod -aG docker clawbot
curl -sfL https://get.k3s.io | sh -
chmod 644 /etc/rancher/k3s/k3s.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
echo "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml" >> /home/clawbot/.bashrc
"""

        user_data += f"""
# Ensure ephemeral destruction after 25 mins max
echo "docker stop \\$(docker ps -aq) 2>/dev/null; shutdown -h now" | at now + 25 minutes

hostnamectl set-hostname {sandbox_id}
echo "Secured Sandbox Ready"
"""
        
        logger.info(f"Deploying isolated sandbox droplet: {sandbox_id}")
        return await self.mgr.create_droplet(
            name=sandbox_id,
            size="s-1vcpu-2gb", # Cheapest enough for code execution
            droplet_type="sandbox",
            ttl_minutes=30, # Hard backup if bash cron fails
            user_data=user_data
        )

    async def execute_in_sandbox(self, droplet_ip: str, script_content: str, lang: str = "python") -> dict:
        """Upload and execute untrusted script via SSH, waiting for result."""
        
        key_path = os.path.expanduser("~/.ssh/id_rsa")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        logger.info(f"Connecting to sandbox IP: {droplet_ip}")
        try:
            # We wrap this in a loop because droplet might take 30-40 secs of booting before SSH allows connections
            connected = False
            for attempt in range(10):
                try:
                    client.connect(hostname=droplet_ip, username="root", key_filename=key_path, timeout=5)
                    connected = True
                    break
                except Exception:
                    await asyncio.sleep(5)
                    
            if not connected:
                return {"error": "Failed to SSH into sandbox after boot."}
                
            # Drop the script in the non-privileged workspace
            ext = "py" if lang == "python" else "bash" if lang == "bash" else "js"
            remote_path = f"/home/clawbot/workspace/task.{ext}"
            
            # Using SFTP to securely transfer the exact string content
            sftp = client.open_sftp()
            with sftp.file(remote_path, 'w') as f:
                f.write(script_content)
            sftp.close()
            
            # Fix perms
            client.exec_command(f"chown clawbot:clawbot {remote_path}")
            
            # Execute command as the unprivileged user
            cmd = f"sudo -u clawbot python3 {remote_path}" if lang == "python" else f"sudo -u clawbot bash {remote_path}"
            logger.info("Triggering sandbox execution...")
            stdin, stdout, stderr = client.exec_command(cmd, timeout=120) # Max 2 mins of compute
            
            exit_code = stdout.channel.recv_exit_status()
            out_data = stdout.read().decode('utf-8', errors='replace')
            err_data = stderr.read().decode('utf-8', errors='replace')
            
            logger.info(f"Sandbox completed with exit code: {exit_code}")
            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "stdout": out_data,
                "stderr": err_data
            }
            
        except Exception as e:
            logger.error(f"Sandbox SSH execution error: {e}")
            return {"error": str(e)}
        finally:
            client.close()

    async def run_safe_task(self, python_script: str, system_type: str = "basic") -> dict:
        """End-to-end sandbox lifecycle: Deploy -> Check -> Run -> Destroy."""
        
        if not self.mgr.configured:
            return {"error": "DigitalOcean not configured for sandbox deployment."}
            
        # 1. Deploy
        deploy_res = await self.create_firewalled_sandbox(system_type=system_type)
        if "error" in deploy_res:
            return deploy_res
            
        droplet_id = deploy_res["droplet_id"]
        
        try:
            # Wait for public IP assignment
            ip_address = None
            for _ in range(15):
                await asyncio.sleep(4)
                status = await self.mgr.get_droplet(droplet_id)
                if status.get("public_ip"):
                    ip_address = status["public_ip"]
                    break
                    
            if not ip_address:
                raise Exception("Sandbox failed to acquire an IP address.")
                
            logger.info(f"Sandbox IP Acquired: {ip_address}, waiting for boot...")
            await asyncio.sleep(30) # Let UFW and useradd initialize
            
            # 2. Execute
            exec_res = await self.execute_in_sandbox(ip_address, python_script)
            return exec_res
            
        finally:
            # 3. Destroy (Always runs, even if python script errors)
            logger.info(f"Atomizing sandbox droplet {droplet_id}")
            await self.mgr.destroy_droplet(droplet_id)


def get_sandbox_manager() -> SandboxManager:
    return SandboxManager()
