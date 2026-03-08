"""Cloudflare DNS & Tunnel Manager — automated domain management for DevPlane.

Supports both Cloudflare API Token (preferred) and Global API Key authentication
to manage DNS records and tunnels for the glondor.xyz domain.
Auto-exposes new droplets and Kasm workspaces.
"""

import os
import json
import logging
from typing import Optional
import httpx

logger = logging.getLogger("devplane.infra.cloudflare")


class CloudflareManager:
    """Manages Cloudflare DNS records and tunnels for glondor.xyz."""

    def __init__(self):
        # Support both API Token (preferred) and Global API Key (legacy)
        self.api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        self.api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
        self.email = os.environ.get("CLOUDFLARE_EMAIL", "")
        self.zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
        self.account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        self.domain = os.environ.get("CLOUDFLARE_DOMAIN", "glondor.xyz")
        # Reuse client for connection pooling
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def configured(self) -> bool:
        # Check for API Token (preferred) or Global API Key (legacy)
        token_configured = bool(self.api_token and self.zone_id)
        legacy_configured = bool(self.api_key and self.email and self.zone_id)
        return token_configured or legacy_configured

    def _headers(self) -> dict:
        # Prefer API Token authentication (new method)
        if self.api_token:
            return {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
        # Fall back to Global API Key authentication (legacy method)
        return {
            "X-Auth-Email": self.email,
            "X-Auth-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx client for connection pooling."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self):
        """Close the httpx client. Call this on shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _api(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make a Cloudflare API request using shared client."""
        url = f"https://api.cloudflare.com/client/v4/{endpoint}"
        client = self._get_client()
        try:
            resp = await client.request(method, url, headers=self._headers(), json=data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Cloudflare API error: {e.response.status_code} - {e.response.text}")
            return {"success": False, "errors": [f"HTTP {e.response.status_code}"]}
        except httpx.RequestError as e:
            logger.error(f"Cloudflare API request failed: {e}")
            return {"success": False, "errors": [str(e)]}
        except Exception as e:
            logger.error(f"Cloudflare API unexpected error: {e}")
            return {"success": False, "errors": [str(e)]}

    # ─── DNS Records ─────────────────────────────────────────────────────

    async def list_dns_records(self, record_type: str = None) -> list[dict]:
        """List all DNS records for the zone."""
        if not self.configured:
            return [{"error": "Cloudflare not configured"}]

        endpoint = f"zones/{self.zone_id}/dns_records"
        if record_type:
            endpoint += f"?type={record_type}"

        result = await self._api("GET", endpoint)
        records = result.get("result", [])

        return [
            {
                "id": r["id"],
                "type": r["type"],
                "name": r["name"],
                "content": r["content"],
                "proxied": r.get("proxied", False),
                "ttl": r.get("ttl", 1),
            }
            for r in records
        ]

    async def create_dns_record(
        self, name: str, content: str, record_type: str = "A", proxied: bool = True
    ) -> dict:
        """Create a DNS record."""
        if not self.configured:
            return {"error": "Cloudflare not configured"}

        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
            "ttl": 1,  # Auto
        }
        result = await self._api("POST", f"zones/{self.zone_id}/dns_records", data)
        if result.get("success"):
            logger.info(f"Created DNS record: {name} → {content}")
            return result.get("result", {})
        else:
            errors = result.get("errors", [])
            logger.error(f"DNS creation failed: {errors}")
            return {"error": str(errors)}

    async def update_dns_record(self, record_id: str, name: str, content: str,
                                 record_type: str = "A", proxied: bool = True) -> dict:
        """Update an existing DNS record."""
        if not self.configured:
            return {"error": "Cloudflare not configured"}

        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
            "ttl": 1,
        }
        return await self._api("PUT", f"zones/{self.zone_id}/dns_records/{record_id}", data)

    async def delete_dns_record(self, record_id: str) -> dict:
        """Delete a DNS record."""
        if not self.configured:
            return {"error": "Cloudflare not configured"}
        return await self._api("DELETE", f"zones/{self.zone_id}/dns_records/{record_id}")

    # ─── Tunnels ─────────────────────────────────────────────────────────

    async def list_tunnels(self) -> list[dict]:
        """List all Cloudflare Tunnels."""
        if not self.configured or not self.account_id:
            return [{"error": "Cloudflare account not configured"}]

        result = await self._api("GET", f"accounts/{self.account_id}/cfd_tunnel")
        tunnels = result.get("result", [])
        return [
            {
                "id": t["id"],
                "name": t["name"],
                "status": t.get("status", "unknown"),
                "created_at": t.get("created_at", ""),
            }
            for t in tunnels
        ]

    async def create_tunnel(self, name: str) -> dict:
        """Create a new Cloudflare Tunnel."""
        if not self.configured or not self.account_id:
            return {"error": "Cloudflare account not configured"}

        import secrets
        import base64
        
        # Generate random bytes and encode as base64 (Cloudflare API requirement)
        tunnel_secret_bytes = secrets.token_bytes(32)
        tunnel_secret = base64.b64encode(tunnel_secret_bytes).decode('utf-8')

        data = {"name": name, "tunnel_secret": tunnel_secret}
        result = await self._api("POST", f"accounts/{self.account_id}/cfd_tunnel", data)

        if result.get("success"):
            tunnel = result.get("result", {})
            logger.info(f"Created tunnel: {name} (id={tunnel.get('id')})")
            return {
                "id": tunnel.get("id"),
                "name": tunnel.get("name"),
                # SECURITY: tunnel_secret is sensitive - only returned during creation
                # Store this securely and never log it in plaintext
                "tunnel_secret": tunnel_secret,
                "token": tunnel.get("token", ""),
                "status": "created",
            }
        else:
            return {"error": str(result.get("errors", [])), "status": "error"}

    async def delete_tunnel(self, tunnel_id: str) -> dict:
        """Delete a Cloudflare Tunnel."""
        if not self.configured or not self.account_id:
            return {"error": "Cloudflare account not configured"}

        result = await self._api("DELETE", f"accounts/{self.account_id}/cfd_tunnel/{tunnel_id}")
        if result.get("success"):
            logger.info(f"Deleted tunnel: {tunnel_id}")
            return {"status": "deleted", "id": tunnel_id}
        else:
            return {"error": str(result.get("errors", [])), "status": "error"}

    async def get_tunnel_token(self, tunnel_id: str) -> dict:
        """Get the token for a tunnel (needed for cloudflared)."""
        if not self.configured or not self.account_id:
            return {"error": "Cloudflare account not configured"}

        result = await self._api("GET", f"accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/token")
        if result.get("success"):
            return {
                "token": result.get("result", ""),
                "tunnel_id": tunnel_id,
            }
        else:
            return {"error": str(result.get("errors", []))}

    async def get_tunnel_config(self, tunnel_id: str) -> dict:
        """Get the configuration for a tunnel."""
        if not self.configured or not self.account_id:
            return {"error": "Cloudflare account not configured"}

        result = await self._api("GET", f"accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations")
        if result.get("success"):
            return result.get("result", {})
        else:
            return {"error": str(result.get("errors", []))}

    # ─── Auto-Expose Helper ──────────────────────────────────────────────

    async def auto_expose(self, ip: str, subdomain: str) -> dict:
        """One-call to create/update a DNS record pointing a subdomain to an IP.

        Example: auto_expose("164.92.100.50", "ws-abc123")
        → Creates ws-abc123.glondor.xyz → 164.92.100.50
        """
        if not self.configured:
            return {"error": "Cloudflare not configured"}

        full_name = f"{subdomain}.{self.domain}" if subdomain != "@" else self.domain

        # Check if record already exists
        records = await self.list_dns_records("A")
        existing = next((r for r in records if r.get("name") == full_name), None)

        if existing:
            result = await self.update_dns_record(
                existing["id"], full_name, ip, proxied=True
            )
            return {"action": "updated", "name": full_name, "ip": ip, "result": result}
        else:
            result = await self.create_dns_record(full_name, ip, proxied=True)
            return {"action": "created", "name": full_name, "ip": ip, "result": result}

    async def get_zone_info(self) -> dict:
        """Get information about the configured zone."""
        if not self.configured:
            return {"error": "Cloudflare not configured"}

        result = await self._api("GET", f"zones/{self.zone_id}")
        if result.get("success"):
            zone = result.get("result", {})
            return {
                "id": zone.get("id"),
                "name": zone.get("name"),
                "status": zone.get("status"),
                "plan": zone.get("plan", {}).get("name"),
                "name_servers": zone.get("name_servers", []),
            }
        else:
            return {"error": str(result.get("errors", []))}


# Singleton
_cf_manager: Optional[CloudflareManager] = None


def get_cloudflare_manager() -> CloudflareManager:
    global _cf_manager
    if _cf_manager is None:
        _cf_manager = CloudflareManager()
    return _cf_manager
