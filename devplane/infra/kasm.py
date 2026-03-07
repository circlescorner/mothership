"""Kasm Workspace Manager — deploy cloud dev environments on demand.

Creates DigitalOcean droplets with Kasm Server pre-installed,
providing browser-accessible workspaces for Antigravity, Kilo Code, etc.
"""

import os
import json
import logging
import secrets
from datetime import datetime
from devplane.db import get_db
from devplane.infra.manager import get_infra_manager, WORKSPACE_TEMPLATES

logger = logging.getLogger("devplane.infra.kasm")


async def create_workspace(template: str = "dev-full",
                           user_email: str = "") -> dict:
    """Create a Kasm workspace from a template.
    
    Deploys a droplet with Kasm Server + the chosen workspace image.
    Returns the workspace record with connect URL.
    """
    mgr = get_infra_manager()
    if not mgr.configured:
        return {"error": "DigitalOcean not configured. Set DIGITALOCEAN_TOKEN."}

    tmpl = WORKSPACE_TEMPLATES.get(template)
    if not tmpl:
        return {"error": f"Unknown template: {template}. Available: {list(WORKSPACE_TEMPLATES.keys())}"}

    ws_id = f"ws-{secrets.token_hex(4)}"
    name = f"devplane-kasm-{ws_id}"
    size = tmpl.get("size", "s-2vcpu-4gb")
    kasm_image = tmpl.get("image", "kasmweb/ubuntu-jammy-desktop:1.15.0")

    # User data script installs Kasm and launches the workspace
    admin_pass = secrets.token_urlsafe(16)
    user_pass = secrets.token_urlsafe(12)

    user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker root
systemctl enable docker && systemctl start docker

# Install Kasm Workspaces
cd /tmp
curl -O https://kasm-static-content.s3.amazonaws.com/kasm_release_1.15.0.06fdc8.tar.gz
tar -xf kasm_release_1.15.0.06fdc8.tar.gz
bash kasm_release/install.sh -e -H -q <<EOF
{admin_pass}
{admin_pass}
{user_pass}
{user_pass}
EOF

# Pull the workspace image
docker pull {kasm_image}

# Create workspace marker
mkdir -p /etc/devplane
echo '{{"workspace_id": "{ws_id}", "template": "{template}", "admin_pass": "{admin_pass}", "user_pass": "{user_pass}"}}' > /etc/devplane/workspace.json
chmod 600 /etc/devplane/workspace.json

hostnamectl set-hostname {name}
echo "Kasm workspace {ws_id} ready"
"""

    result = await mgr.create_droplet(name, size, "ubuntu-22-04-x64", "kasm", 0, user_data)
    droplet = result.get("droplet", {})
    droplet_id = droplet.get("id")

    if not droplet_id:
        return {"error": "Failed to create droplet", "details": result}

    # Track workspace in DB
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO workspaces (workspace_id, template, name, droplet_id, status, user_email)
            VALUES (?, ?, ?, ?, 'creating', ?)
        """, (ws_id, template, name, droplet_id, user_email))
        await db.commit()
    finally:
        await db.close()

    logger.info(f"Creating Kasm workspace: {ws_id} ({template}) on droplet {droplet_id}")

    return {
        "workspace_id": ws_id,
        "template": template,
        "name": name,
        "droplet_id": droplet_id,
        "status": "creating",
        "admin_password": admin_pass,
        "user_password": user_pass,
        "note": "Workspace will be available at https://<droplet-ip>:443 in ~5 minutes",
    }


async def list_workspaces() -> list[dict]:
    """List all workspaces with current status."""
    db = await get_db()
    try:
        rows = await db.execute(
            "SELECT * FROM workspaces WHERE status != 'destroyed' ORDER BY created_at DESC"
        )
        workspaces = [dict(r) for r in await rows.fetchall()]

        # Try to update connect URLs if we have droplet IPs
        for ws in workspaces:
            if ws.get("droplet_id") and not ws.get("connect_url"):
                ip_row = await db.execute(
                    "SELECT public_ip FROM droplets WHERE droplet_id = ?",
                    (ws["droplet_id"],)
                )
                ip = await ip_row.fetchone()
                if ip and ip["public_ip"]:
                    ws["connect_url"] = f"https://{ip['public_ip']}"
                    ws["status"] = "running"
                    await db.execute(
                        "UPDATE workspaces SET connect_url = ?, status = 'running' WHERE workspace_id = ?",
                        (ws["connect_url"], ws["workspace_id"])
                    )
            await db.commit()

        return workspaces
    finally:
        await db.close()


async def destroy_workspace(workspace_id: str) -> dict:
    """Destroy a workspace and its underlying droplet."""
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT droplet_id FROM workspaces WHERE workspace_id = ?",
            (workspace_id,)
        )
        ws = await row.fetchone()
        if not ws:
            return {"error": "Workspace not found"}

        # Destroy the droplet
        mgr = get_infra_manager()
        if ws["droplet_id"]:
            await mgr.destroy_droplet(ws["droplet_id"])

        await db.execute(
            "UPDATE workspaces SET status = 'destroyed', destroyed_at = datetime('now') WHERE workspace_id = ?",
            (workspace_id,)
        )
        await db.commit()

        return {"status": "destroyed", "workspace_id": workspace_id}
    finally:
        await db.close()
