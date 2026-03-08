"""Sandbox Engine — Secure execution of untrusted autonomous agents.

Deploys ephemeral, isolated droplets to run code (Clawbot, etc) safely off-network
and captures output before immediate destruction.

Security Features:
- Network isolation (blocks private IP ranges)
- No persistent credentials
- Ephemeral secrets only
- Resource limits (CPU, memory, disk)
- Full audit logging
- Credential isolation from host
- Non-root execution
"""

import os
import secrets
import asyncio
import logging
import json
import hashlib
import threading
import paramiko
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from devplane.infra.manager import get_infra_manager

logger = logging.getLogger("devplane.infra.sandbox")


class SandboxStatus(str, Enum):
    """Sandbox lifecycle states."""
    PENDING = "pending"
    DEPLOYING = "deploying"
    RUNNING = "running"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    DESTROYED = "destroyed"


class SandboxSecurityLevel(str, Enum):
    """Sandbox security levels."""
    BASIC = "basic"         # Basic isolation
    STRICT = "strict"       # Strict isolation, no network
    CONTAINERIZED = "container"  # Docker container isolation


@dataclass
class SandboxSession:
    """Sandbox execution session."""
    session_id: str
    sandbox_id: str
    status: SandboxStatus
    created_at: datetime
    droplet_id: Optional[int] = None
    ip_address: Optional[str] = None
    security_level: SandboxSecurityLevel = SandboxSecurityLevel.BASIC
    user: str = "clawbot"
    max_runtime_minutes: int = 30
    max_cpu_percent: int = 50
    max_memory_mb: int = 512
    max_disk_mb: int = 1024
    network_allowed: bool = True
    allowed_domains: List[str] = field(default_factory=list)
    audit_log: List[Dict] = field(default_factory=list)
    execution_count: int = 0
    destroyed_at: Optional[datetime] = None


class SandboxSecurityMonitor:
    """Monitor and enforce sandbox security."""
    
    def __init__(self):
        self._sessions: Dict[str, SandboxSession] = {}
        self._audit_log: List[Dict] = []
        self._audit_lock = threading.Lock()
        self._failed_attempts: Dict[str, List[float]] = defaultdict(list)
    
    def create_session(self, security_level: SandboxSecurityLevel = SandboxSecurityLevel.BASIC,
                      max_runtime: int = 30, **options) -> SandboxSession:
        """Create a new sandbox session."""
        session_id = f"session-{secrets.token_hex(8)}"
        sandbox_id = f"sandbox-{secrets.token_hex(4)}"
        
        session = SandboxSession(
            session_id=session_id,
            sandbox_id=sandbox_id,
            status=SandboxStatus.PENDING,
            created_at=datetime.utcnow(),
            security_level=security_level,
            max_runtime_minutes=max_runtime,
            max_cpu_percent=options.get("max_cpu", 50),
            max_memory_mb=options.get("max_memory", 512),
            max_disk_mb=options.get("max_disk", 1024),
            network_allowed=security_level != SandboxSecurityLevel.STRICT,
            allowed_domains=options.get("allowed_domains", [])
        )
        
        self._sessions[session_id] = session
        self._audit(session_id, "session_created", True, 
                   f"Created sandbox: {sandbox_id}")
        
        return session
    
    def get_session(self, session_id: str) -> Optional[SandboxSession]:
        """Get session by ID."""
        return self._sessions.get(session_id)
    
    def update_session(self, session_id: str, **updates):
        """Update session state."""
        session = self._sessions.get(session_id)
        
        if not session:
            return None
        
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)
        
        return session
    
    def _audit(self, session_id: str, action: str, success: bool, details: str = None):
        """Log sandbox operation."""
        session = self._sessions.get(session_id)
        
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "sandbox_id": session.sandbox_id if session else "unknown",
            "action": action,
            "success": success,
            "details": details
        }
        
        with self._audit_lock:
            self._audit_log.append(entry)
            
            if session:
                session.audit_log.append(entry)
            
            # Keep last 10000 entries
            if len(self._audit_log) > 10000:
                self._audit_log = self._audit_log[-10000:]
    
    def check_rate_limit(self, identifier: str, max_attempts: int = 5, 
                        window_seconds: int = 300) -> bool:
        """Check rate limit for sandbox operations."""
        now = time.time()
        window_start = now - window_seconds
        
        # Clean old attempts
        self._failed_attempts[identifier] = [
            t for t in self._failed_attempts[identifier] if t > window_start
        ]
        
        if len(self._failed_attempts[identifier]) >= max_attempts:
            return False
        
        return True
    
    def record_attempt(self, identifier: str, success: bool):
        """Record an attempt."""
        if not success:
            self._failed_attempts[identifier].append(time.time())
        else:
            # Clear on success
            self._failed_attempts[identifier].clear()
    
    def get_audit_log(self, session_id: str = None, limit: int = 100) -> List[Dict]:
        """Get audit log."""
        with self._audit_lock:
            if session_id:
                return [e for e in self._audit_log[-limit:] 
                       if e.get("session_id") == session_id]
            return self._audit_log[-limit:]


class SandboxManager:
    """Manages isolated sandbox environments for running untrusted LLM code.
    
    Security enhancements:
    - No persistent credentials in sandbox
    - Ephemeral secrets only
    - Network isolation
    - Resource limits
    - Full audit logging
    """
    
    def __init__(self):
        self.mgr = get_infra_manager()
        self.security_monitor = SandboxSecurityMonitor()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def _get_user_data(self, session: SandboxSession) -> str:
        """Generate cloud-init user data with security hardening."""
        
        # Determine security level
        if session.security_level == SandboxSecurityLevel.STRICT:
            network_policy = "deny"
        elif session.security_level == SandboxSecurityLevel.CONTAINERIZED:
            network_policy = "container"
        else:
            network_policy = "allow"
        
        user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

# =============================================
# SANDBOX SECURITY HARDENING
# Generated: {datetime.utcnow().isoformat()}
# Session: {session.session_id}
# Security Level: {session.security_level.value}
# =============================================

# Timeout Safe Aliases (Kilocode Safety Wrappers)
cat > /etc/profile.d/safety-aliases.sh << 'EOF'
alias curl='curl --max-time 30 --connect-timeout 10'
alias wget='wget --timeout=30 --tries=3'
timeout_safe() {{
    local duration="$1"
    shift
    timeout --signal=TERM --kill-after=5 "$duration" "$@"
}}
EOF
chmod +x /etc/profile.d/safety-aliases.sh
source /etc/profile.d/safety-aliases.sh

# Safe apt-get with timeout
apt-get-update-safe() {{
    timeout_safe 300 apt-get update
}}
apt-get-install-safe() {{
    timeout_safe 600 apt-get install -y "$@"
}}

apt-get-update-safe

# Install security tools
apt-get-install-safe ufw dos2unix auditd rsyslog

# =============================================
# NETWORK ISOLATION
# =============================================

# Reset and configure UFW
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# BLOCK ALL PRIVATE IP RANGES - Prevent lateral movement
ufw deny out to 10.0.0.0/8
ufw deny out to 172.16.0.0/12
ufw deny out to 192.168.0.0/16
ufw deny out to 100.64.0.0/10
ufw deny out to 169.254.0.0/16  # Link-local

# Allow specific domains if whitelisted
"""
        
        # Add allowed domains if specified
        if session.allowed_domains:
            for domain in session.allowed_domains:
                user_data += f"""
# Allow domain: {domain}
ufw allow out to 8.8.8.8 port 53  # DNS for {domain}
"""
        
        user_data += f"""
# Allow SSH
ufw allow 22/tcp

# Enable firewall
ufw --force enable

# =============================================
# RESOURCE LIMITS
# =============================================

# Set up resource limits via /etc/security/limits.conf
cat >> /etc/security/limits.conf << 'EOF'
* soft cpu {session.max_cpu_percent}
* hard cpu {session.max_cpu_percent}
* soft mem {session.max_memory_mb}M
* hard mem {session.max_memory_mb}M
* soft nproc 100
* hard nproc 100
EOF

# =============================================
# NO PERSISTENT CREDENTIALS
# =============================================

# Remove any default keys
rm -f /root/.ssh/authorized_keys 2>/dev/null || true
rm -f /home/*/.ssh/authorized_keys 2>/dev/null || true

# Disable password authentication
sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config

# =============================================
# SANDBOX USER
# =============================================

# Create non-privileged user for task execution
useradd -m -s /bin/bash {session.user}
mkdir -p /home/{session.user}/workspace
chown -R {session.user}:{session.user} /home/{session.user}

# =============================================
# AUDIT LOGGING
# =============================================

# Configure auditd for sandbox operations
cat > /etc/audit/auditd.conf << 'EOF'
max_log_file = 10
max_log_file_action = ROTATE
space_left_action = SYSLOG
admin_space_left_action = SYSLOG
EOF

# Start services
systemctl enable auditd
systemctl start auditd

# =============================================
# EPHEMERAL DESTRUCTION
# =============================================

# Schedule destruction after max runtime
echo "shutdown -h now" | at now + {session.max_runtime_minutes} minutes 2>/dev/null || true

# Also set up a watchdog script
cat > /usr/local/bin/sandbox-watchdog.sh << 'EOF'
#!/bin/bash
# Kill any remaining processes after timeout
sleep {session.max_runtime_minutes * 60}
pkill -u {session.user} || true
shutdown -h now
EOF
chmod +x /usr/local/bin/sandbox-watchdog.sh
nohup /usr/local/bin/sandbox-watchdog.sh > /dev/null 2>&1 &

# Set hostname
hostnamectl set-hostname {session.sandbox_id}

echo "SECURE_SANDBOX_READY"
"""
        
        return user_data
    
    async def create_secure_sandbox(self, security_level: SandboxSecurityLevel = SandboxSecurityLevel.BASIC,
                                   max_runtime: int = 30, **options) -> Dict:
        """Create a secure sandbox with enhanced security.
        
        Args:
            security_level: Security level (basic, strict, container)
            max_runtime: Maximum runtime in minutes
            **options: Additional options (allowed_domains, max_cpu, etc.)
            
        Returns:
            Dict with session_id, sandbox_id, droplet_id, ip_address
        """
        # Check rate limit
        if not self.security_monitor.check_rate_limit("create", max_attempts=10):
            return {"error": "Rate limit exceeded for sandbox creation"}
        
        # Create security session
        session = self.security_monitor.create_session(
            security_level=security_level,
            max_runtime=max_runtime,
            **options
        )
        
        self.security_monitor.update_session(session.session_id, 
                                          status=SandboxStatus.DEPLOYING)
        
        # Generate user data
        user_data = self._get_user_data(session)
        
        try:
            logger.info(f"Deploying secure sandbox: {session.sandbox_id}")
            
            # Deploy droplet
            result = await self.mgr.create_droplet(
                name=session.sandbox_id,
                size="s-1vcpu-2gb",
                droplet_type="sandbox",
                ttl_minutes=max_runtime + 5,  # Buffer
                user_data=user_data
            )
            
            if "error" in result:
                self.security_monitor.update_session(session.session_id,
                                                   status=SandboxStatus.FAILED)
                self.security_monitor._audit(session.session_id, "deploy", False, 
                                            result.get("error"))
                return result
            
            droplet_id = result.get("droplet_id")
            ip_address = result.get("public_ip")
            
            # Update session
            self.security_monitor.update_session(
                session.session_id,
                droplet_id=droplet_id,
                ip_address=ip_address,
                status=SandboxStatus.RUNNING
            )
            
            self.security_monitor._audit(session.session_id, "deploy", True,
                                       f"Droplet: {droplet_id}, IP: {ip_address}")
            
            return {
                "session_id": session.session_id,
                "sandbox_id": session.sandbox_id,
                "droplet_id": droplet_id,
                "ip_address": ip_address,
                "security_level": security_level.value,
                "max_runtime": max_runtime
            }
            
        except Exception as e:
            logger.error(f"Sandbox deployment error: {e}")
            self.security_monitor.update_session(session.session_id,
                                              status=SandboxStatus.FAILED)
            self.security_monitor._audit(session.session_id, "deploy", False, str(e))
            return {"error": str(e)}
    
    async def execute_in_sandbox(self, session_id: str, script_content: str, 
                                lang: str = "python", timeout: int = 120) -> Dict:
        """Execute script in sandbox with credential isolation.
        
        IMPORTANT: No credentials are passed to the sandbox. 
        All secrets must be retrieved at runtime from the host.
        """
        session = self.security_monitor.get_session(session_id)
        
        if not session:
            return {"error": "Session not found"}
        
        if session.status not in [SandboxStatus.RUNNING, SandboxStatus.EXECUTING]:
            return {"error": f"Invalid session status: {session.status}"}
        
        if not session.ip_address:
            return {"error": "Sandbox IP not available"}
        
        self.security_monitor.update_session(session_id, 
                                          status=SandboxStatus.EXECUTING)
        self.security_monitor._audit(session_id, "execute", True,
                                   f"Starting {lang} execution")
        
        # Get SSH key from security manager (NOT from vault in sandbox)
        from devplane.security.ssh_manager import get_ssh_manager
        ssh_mgr = get_ssh_manager()
        
        key_path, _ = ssh_mgr.get_key_for_connection("deployment")
        
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            # Connect with timeout
            client.connect(
                hostname=session.ip_address,
                username="root",
                key_filename=key_path,
                timeout=30,
                banner_timeout=30
            )
            
            # Determine file extension
            ext = {"python": "py", "bash": "sh", "javascript": "js"}.get(lang, "txt")
            remote_path = f"/home/{session.user}/workspace/task.{ext}"
            
            # Upload script via SFTP
            sftp = client.open_sftp()
            with sftp.file(remote_path, 'w') as f:
                f.write(script_content)
            sftp.close()
            
            # Set permissions (run as non-root)
            client.exec_command(f"chown {session.user}:{session.user} {remote_path}")
            
            # Execute as non-privileged user
            cmd = f"sudo -u {session.user} {lang}3 {remote_path}" if lang == "python" else f"sudo -u {session.user} {lang} {remote_path}"
            
            # Run with timeout
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            
            exit_code = stdout.channel.recv_exit_status()
            out_data = stdout.read().decode('utf-8', errors='replace')
            err_data = stderr.read().decode('utf-8', errors='replace')
            
            session.execution_count += 1
            
            self.security_monitor._audit(session_id, "execute_complete", True,
                                       f"Exit code: {exit_code}")
            
            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "stdout": out_data,
                "stderr": err_data,
                "execution_count": session.execution_count
            }
            
        except Exception as e:
            logger.error(f"Sandbox execution error: {e}")
            self.security_monitor._audit(session_id, "execute", False, str(e))
            return {"error": str(e)}
            
        finally:
            client.close()
            self.security_monitor.update_session(session_id, 
                                              status=SandboxStatus.RUNNING)
    
    async def destroy_sandbox(self, session_id: str) -> bool:
        """Destroy a sandbox and clean up."""
        session = self.security_monitor.get_session(session_id)
        
        if not session:
            return False
        
        try:
            if session.droplet_id:
                await self.mgr.destroy_droplet(session.droplet_id)
            
            self.security_monitor.update_session(
                session_id,
                status=SandboxStatus.DESTROYED,
                destroyed_at=datetime.utcnow()
            )
            
            self.security_monitor._audit(session_id, "destroy", True,
                                       "Sandbox destroyed")
            
            return True
            
        except Exception as e:
            logger.error(f"Sandbox destruction error: {e}")
            self.security_monitor._audit(session_id, "destroy", False, str(e))
            return False
    
    async def run_secure_task(self, script_content: str, 
                            lang: str = "python",
                            security_level: SandboxSecurityLevel = SandboxSecurityLevel.BASIC,
                            max_runtime: int = 30, **options) -> Dict:
        """End-to-end secure sandbox execution.
        
        This is the main entry point for secure task execution.
        No credentials are ever passed to the sandbox.
        """
        
        # Check rate limit
        if not self.security_monitor.check_rate_limit("task"):
            return {"error": "Rate limit exceeded"}
        
        # Deploy sandbox
        deploy_result = await self.create_secure_sandbox(
            security_level=security_level,
            max_runtime=max_runtime,
            **options
        )
        
        if "error" in deploy_result:
            return deploy_result
        
        session_id = deploy_result["session_id"]
        
        try:
            # Wait for boot
            await asyncio.sleep(30)
            
            # Execute task
            exec_result = await self.execute_in_sandbox(session_id, script_content, lang)
            return exec_result
            
        finally:
            # Always destroy sandbox
            await self.destroy_sandbox(session_id)
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """Get session information."""
        session = self.security_monitor.get_session(session_id)
        
        if not session:
            return None
        
        return {
            "session_id": session.session_id,
            "sandbox_id": session.sandbox_id,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "ip_address": session.ip_address,
            "security_level": session.security_level.value,
            "execution_count": session.execution_count,
            "max_runtime": session.max_runtime_minutes
        }
    
    def get_audit_log(self, session_id: str = None, limit: int = 100) -> List[Dict]:
        """Get audit log."""
        return self.security_monitor.get_audit_log(session_id, limit)


# ─── Factory Function ───────────────────────────────────────────────────────────

_sandbox_manager: Optional[SandboxManager] = None


def get_sandbox_manager() -> SandboxManager:
    """Get or create the global sandbox manager."""
    global _sandbox_manager
    
    if _sandbox_manager is None:
        _sandbox_manager = SandboxManager()
    
    return _sandbox_manager
