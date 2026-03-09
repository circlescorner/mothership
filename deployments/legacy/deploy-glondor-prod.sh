#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# DevPlane Production Deployment Script
# ═══════════════════════════════════════════════════════════════════════════════
# 
# This script automates the complete production deployment including:
# - Cloudflare Tunnel creation via API
# - DNS record configuration
# - Docker Compose production setup
# - Health checks and monitoring
# - SSL/TLS via Cloudflare (no firewall ports needed)
#
# Usage: ./deploy-glondor-prod.sh [command]
# Commands: deploy, tunnel-only, status, logs, destroy
#
# Prerequisites:
# - Docker and Docker Compose installed
# - .env file with CLOUDFLARE_API_KEY, CLOUDFLARE_EMAIL, 
#   CLOUDFLARE_ZONE_ID, CLOUDFLARE_ACCOUNT_ID
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════
DOMAIN="${DEPLOYMENT_DOMAIN:-glondor.xyz}"
TUNNEL_NAME="devplane-prod"
DEPLOY_DIR="/opt/devplane"
COMPOSE_PROJECT="devplane"

# ═══════════════════════════════════════════════════════════════════════════════
# Colors for output
# ═══════════════════════════════════════════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ═══════════════════════════════════════════════════════════════════════════════
# Logging functions
# ═══════════════════════════════════════════════════════════════════════════════
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${CYAN}[STEP]${NC} $1"; }

# ═══════════════════════════════════════════════════════════════════════════════
# Load environment variables
# ═══════════════════════════════════════════════════════════════════════════════
load_env() {
    if [[ -f .env ]]; then
        set -a
        source .env
        set +a
        log_info "Loaded environment from .env"
    else
        log_error ".env file not found! Please create one from .env.example"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Check prerequisites
# ═══════════════════════════════════════════════════════════════════════════════
check_prerequisites() {
    log_step "Checking prerequisites..."
    
    local missing_deps=()
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        missing_deps+=("docker")
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        missing_deps+=("docker-compose")
    fi
    
    # Check curl
    if ! command -v curl &> /dev/null; then
        missing_deps+=("curl")
    fi
    
    # Check jq
    if ! command -v jq &> /dev/null; then
        missing_deps+=("jq")
    fi
    
    # Check Python for Cloudflare API helper
    if ! command -v python3 &> /dev/null; then
        missing_deps+=("python3")
    fi
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing dependencies: ${missing_deps[*]}"
        log_info "Please install missing dependencies:"
        log_info "  Ubuntu/Debian: sudo apt-get install -y docker.io docker-compose curl jq python3 python3-pip"
        log_info "  macOS: brew install docker docker-compose curl jq python3"
        exit 1
    fi
    
    # Check Cloudflare credentials
    local required_vars=("CLOUDFLARE_API_KEY" "CLOUDFLARE_EMAIL" "CLOUDFLARE_ZONE_ID" "CLOUDFLARE_ACCOUNT_ID")
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        log_error "Missing required environment variables: ${missing_vars[*]}"
        log_info "Please add them to your .env file"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Create Cloudflare Tunnel helper script
# ═══════════════════════════════════════════════════════════════════════════════
ensure_tunnel_helper() {
    local helper_script="$SCRIPT_DIR/.tunnel-helper.py"
    
    if [[ -f "$helper_script" ]]; then
        return 0
    fi
    
    log_step "Creating Cloudflare Tunnel helper script..."
    
    cat > "$helper_script" << 'PYTHON_EOF'
#!/usr/bin/env python3
"""Cloudflare Tunnel API Helper - Creates tunnels and configures DNS."""

import os
import sys
import json
import secrets
import argparse
import asyncio
from typing import Optional

# Try to import httpx, fallback to urllib
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import urllib.request
    import urllib.error
    import ssl


class CloudflareTunnelAPI:
    """Handles Cloudflare Tunnel creation and DNS management."""
    
    def __init__(self):
        self.api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
        self.email = os.environ.get("CLOUDFLARE_EMAIL", "")
        self.zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
        self.account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        self.domain = os.environ.get("CLOUDFLARE_DOMAIN", "glondor.xyz")
    
    @property
    def headers(self) -> dict:
        return {
            "X-Auth-Email": self.email,
            "X-Auth-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    def _api_sync(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make synchronous API request."""
        url = f"https://api.cloudflare.com/client/v4/{endpoint}"
        
        if HAS_HTTPX:
            import httpx
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.request(method, url, headers=self.headers, json=data)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:
                return {"success": False, "errors": [str(e)]}
        else:
            # Fallback to urllib
            try:
                req = urllib.request.Request(
                    url,
                    method=method,
                    headers=self.headers,
                    data=json.dumps(data).encode() if data else None
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                return {"success": False, "errors": [f"HTTP {e.code}: {e.read().decode()}"]}
            except Exception as e:
                return {"success": False, "errors": [str(e)]}
    
    def list_tunnels(self) -> list:
        """List all tunnels."""
        result = self._api_sync("GET", f"accounts/{self.account_id}/cfd_tunnel")
        if result.get("success"):
            return [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "status": t.get("status", "unknown"),
                }
                for t in result.get("result", [])
            ]
        return []
    
    def get_tunnel_by_name(self, name: str) -> Optional[dict]:
        """Find tunnel by name."""
        tunnels = self.list_tunnels()
        for tunnel in tunnels:
            if tunnel["name"] == name:
                return tunnel
        return None
    
    def create_tunnel(self, name: str) -> dict:
        """Create a new tunnel and return credentials."""
        tunnel_secret = secrets.token_hex(32)
        
        data = {
            "name": name,
            "tunnel_secret": tunnel_secret
        }
        
        result = self._api_sync("POST", f"accounts/{self.account_id}/cfd_tunnel", data)
        
        if result.get("success"):
            tunnel = result.get("result", {})
            # Get the token for cloudflared
            token_result = self._api_sync(
                "GET", 
                f"accounts/{self.account_id}/cfd_tunnel/{tunnel['id']}/token"
            )
            
            return {
                "success": True,
                "id": tunnel.get("id"),
                "name": tunnel.get("name"),
                "token": token_result.get("result", ""),
                "tunnel_secret": tunnel_secret,
            }
        else:
            return {
                "success": False,
                "errors": result.get("errors", ["Unknown error"])
            }
    
    def delete_tunnel(self, tunnel_id: str) -> bool:
        """Delete a tunnel."""
        result = self._api_sync("DELETE", f"accounts/{self.account_id}/cfd_tunnel/{tunnel_id}")
        return result.get("success", False)
    
    def create_dns_record(self, name: str, record_type: str, content: str, proxied: bool = True) -> dict:
        """Create a DNS record."""
        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
            "ttl": 1,  # Auto
        }
        
        result = self._api_sync("POST", f"zones/{self.zone_id}/dns_records", data)
        
        if result.get("success"):
            record = result.get("result", {})
            return {
                "success": True,
                "id": record.get("id"),
                "name": record.get("name"),
                "type": record.get("type"),
                "content": record.get("content"),
            }
        else:
            return {
                "success": False,
                "errors": result.get("errors", ["Unknown error"])
            }
    
    def list_dns_records(self, record_type: str = None) -> list:
        """List DNS records."""
        endpoint = f"zones/{self.zone_id}/dns_records"
        if record_type:
            endpoint += f"?type={record_type}"
        
        result = self._api_sync("GET", endpoint)
        if result.get("success"):
            return result.get("result", [])
        return []
    
    def delete_dns_record(self, record_id: str) -> bool:
        """Delete a DNS record."""
        result = self._api_sync("DELETE", f"zones/{self.zone_id}/dns_records/{record_id}")
        return result.get("success", False)
    
    def setup_tunnel_dns(self, tunnel_id: str, subdomain: str = "@") -> dict:
        """Create CNAME record pointing to tunnel."""
        # For tunnels, we create a CNAME to <tunnel-id>.cfargotunnel.com
        tunnel_domain = f"{tunnel_id}.cfargotunnel.com"
        
        full_name = f"{subdomain}.{self.domain}" if subdomain != "@" else self.domain
        
        # Check if record exists
        existing = None
        for record in self.list_dns_records("CNAME"):
            if record.get("name") == full_name:
                existing = record
                break
        
        if existing:
            # Update existing
            self.delete_dns_record(existing["id"])
        
        # Create new CNAME
        return self.create_dns_record(full_name, "CNAME", tunnel_domain, proxied=True)


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Tunnel Helper")
    parser.add_argument("command", choices=["create", "delete", "list", "setup-dns"])
    parser.add_argument("--name", default="devplane-prod", help="Tunnel name")
    parser.add_argument("--tunnel-id", help="Tunnel ID for deletion")
    parser.add_argument("--subdomain", default="@", help="Subdomain for DNS")
    parser.add_argument("--output", help="Output file for credentials")
    
    args = parser.parse_args()
    
    api = CloudflareTunnelAPI()
    
    if args.command == "list":
        tunnels = api.list_tunnels()
        print(json.dumps(tunnels, indent=2))
    
    elif args.command == "create":
        # Check if tunnel exists
        existing = api.get_tunnel_by_name(args.name)
        if existing:
            print(json.dumps({
                "success": False,
                "error": f"Tunnel '{args.name}' already exists",
                "existing_id": existing["id"]
            }))
            sys.exit(1)
        
        result = api.create_tunnel(args.name)
        print(json.dumps(result, indent=2))
    
    elif args.command == "delete":
        if not args.tunnel_id:
            # Try to find by name
            existing = api.get_tunnel_by_name(args.name)
            if existing:
                args.tunnel_id = existing["id"]
            else:
                print(json.dumps({"success": False, "error": "Tunnel not found"}))
                sys.exit(1)
        
        success = api.delete_tunnel(args.tunnel_id)
        print(json.dumps({"success": success, "id": args.tunnel_id}))
    
    elif args.command == "setup-dns":
        if not args.tunnel_id:
            print(json.dumps({"success": False, "error": "--tunnel-id required"}))
            sys.exit(1)
        
        result = api.setup_tunnel_dns(args.tunnel_id, args.subdomain)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
PYTHON_EOF

    chmod +x "$helper_script"
    log_success "Tunnel helper script created"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Create or get existing tunnel
# ═══════════════════════════════════════════════════════════════════════════════
manage_tunnel() {
    log_step "Managing Cloudflare Tunnel..."
    
    ensure_tunnel_helper
    
    # Check for existing tunnel
    log_info "Checking for existing tunnel '$TUNNEL_NAME'..."
    
    local existing_tunnel
    existing_tunnel=$(python3 "$SCRIPT_DIR/.tunnel-helper.py" list | jq -r ".[] | select(.name == \"$TUNNEL_NAME\") | .id")
    
    if [[ -n "$existing_tunnel" ]]; then
        log_warn "Tunnel '$TUNNEL_NAME' already exists (ID: $existing_tunnel)"
        log_info "Using existing tunnel..."
        TUNNEL_ID="$existing_tunnel"
        
        # Get token for existing tunnel
        log_info "Retrieving tunnel token..."
        local token_result
        token_result=$(curl -s -X GET \
            "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/token" \
            -H "X-Auth-Email: $CLOUDFLARE_EMAIL" \
            -H "X-Auth-Key: $CLOUDFLARE_API_KEY" \
            -H "Content-Type: application/json")
        
        TUNNEL_TOKEN=$(echo "$token_result" | jq -r '.result')
    else
        log_info "Creating new Cloudflare Tunnel..."
        
        local create_result
        create_result=$(python3 "$SCRIPT_DIR/.tunnel-helper.py" create --name "$TUNNEL_NAME")
        
        if [[ $(echo "$create_result" | jq -r '.success') != "true" ]]; then
            log_error "Failed to create tunnel: $(echo "$create_result" | jq -r '.errors | join(", ")')"
            exit 1
        fi
        
        TUNNEL_ID=$(echo "$create_result" | jq -r '.id')
        TUNNEL_TOKEN=$(echo "$create_result" | jq -r '.token')
        
        log_success "Created tunnel: $TUNNEL_ID"
    fi
    
    # Update .env file with TUNNEL_TOKEN
    update_env_var "TUNNEL_TOKEN" "$TUNNEL_TOKEN"
    
    # Export for current session
    export TUNNEL_TOKEN
    
    log_success "Tunnel configured (ID: $TUNNEL_ID)"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Update environment variable in .env file
# ═══════════════════════════════════════════════════════════════════════════════
update_env_var() {
    local var_name="$1"
    local var_value="$2"
    local env_file="$SCRIPT_DIR/.env"
    
    if [[ -f "$env_file" ]]; then
        # Remove existing line if present
        grep -v "^${var_name}=" "$env_file" > "$env_file.tmp" || true
        
        # Add new value
        echo "${var_name}='${var_value}'" >> "$env_file.tmp"
        
        mv "$env_file.tmp" "$env_file"
        log_info "Updated $var_name in .env"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Setup DNS records for tunnel
# ═══════════════════════════════════════════════════════════════════════════════
setup_dns() {
    log_step "Setting up DNS records..."
    
    if [[ -z "${TUNNEL_ID:-}" ]]; then
        log_error "TUNNEL_ID not set. Run tunnel creation first."
        exit 1
    fi
    
    # Setup main domain
    log_info "Creating DNS record for $DOMAIN → tunnel..."
    
    local dns_result
    dns_result=$(python3 "$SCRIPT_DIR/.tunnel-helper.py" setup-dns \
        --tunnel-id "$TUNNEL_ID" \
        --subdomain "@")
    
    if [[ $(echo "$dns_result" | jq -r '.success') == "true" ]]; then
        log_success "DNS configured: $DOMAIN → $TUNNEL_ID.cfargotunnel.com"
    else
        log_warn "DNS setup returned: $(echo "$dns_result" | jq -r '.errors | join(", ") // "unknown error"')"
    fi
    
    # Setup www subdomain
    log_info "Creating DNS record for www.$DOMAIN → tunnel..."
    
    local www_dns_result
    www_dns_result=$(python3 "$SCRIPT_DIR/.tunnel-helper.py" setup-dns \
        --tunnel-id "$TUNNEL_ID" \
        --subdomain "www")
    
    if [[ $(echo "$www_dns_result" | jq -r '.success') == "true" ]]; then
        log_success "DNS configured: www.$DOMAIN → $TUNNEL_ID.cfargotunnel.com"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Create production docker-compose.yml
# ═══════════════════════════════════════════════════════════════════════════════
create_docker_compose() {
    log_step "Creating production Docker Compose configuration..."
    
    local compose_file="$SCRIPT_DIR/docker-compose.prod.yml"
    
    cat > "$compose_file" << COMPOSE_EOF
# ═══════════════════════════════════════════════════════════════════════════════
# DevPlane Production Docker Compose Configuration
# ═══════════════════════════════════════════════════════════════════════════════
# 
# Optimized for production deployment with:
# - Cloudflare Tunnel for secure ingress (no firewall ports needed)
# - Role-based model registry with 5-way fallback
# - AI mesh, workflow orchestration, infrastructure management
# - Health checks and monitoring
# - Auto-restart policies
#
# Usage: docker-compose -f docker-compose.prod.yml up -d
#
# ═══════════════════════════════════════════════════════════════════════════════

version: "3.8"

services:
  # ═════════════════════════════════════════════════════════════════════════════
  # Main DevPlane Application
  # ═════════════════════════════════════════════════════════════════════════════
  devplane:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: devplane-app
    restart: unless-stopped
    
    environment:
      - ENV=production
      - HOST=0.0.0.0
      - PORT=8000
      - DEVPLANE_DB_PATH=/app/data/devplane.db
      - CORS_ORIGINS=https://${DOMAIN},https://www.${DOMAIN}
      # AI Provider API Keys (from .env)
      - OPENROUTER_API_KEY=\${OPENROUTER_API_KEY:-}
      - DEEPSEEK_API_KEY=\${DEEPSEEK_API_KEY:-}
      - GROQ_API_KEY=\${GROQ_API_KEY:-}
      - GEMINI_API_KEY=\${GEMINI_API_KEY:-}
      - CEREBRAS_API_KEY=\${CEREBRAS_API_KEY:-}
      - TOGETHERAI_API_KEY=\${TOGETHERAI_API_KEY:-}
      - FIREWORKS_AI_API_KEY=\${FIREWORKS_AI_API_KEY:-}
      - OPENAI_API_KEY=\${OPENAI_API_KEY:-}
      # Infrastructure
      - DIGITALOCEAN_TOKEN=\${DIGITALOCEAN_TOKEN:-}
      - CLOUDFLARE_API_KEY=\${CLOUDFLARE_API_KEY:-}
      - CLOUDFLARE_EMAIL=\${CLOUDFLARE_EMAIL:-}
      - CLOUDFLARE_ZONE_ID=\${CLOUDFLARE_ZONE_ID:-}
      - CLOUDFLARE_ACCOUNT_ID=\${CLOUDFLARE_ACCOUNT_ID:-}
      - CLOUDFLARE_DOMAIN=\${CLOUDFLARE_DOMAIN:-${DOMAIN}}
      # Vector DB
      - QDRANT_URL=\${QDRANT_URL:-http://qdrant:6333}
      - QDRANT_KEY=\${QDRANT_KEY:-}
      # Slack
      - SLACK_BOT_TOKEN=\${SLACK_BOT_TOKEN:-}
      - SLACK_APP_TOKEN=\${SLACK_APP_TOKEN:-}
      - ENABLE_SLACK=\${ENABLE_SLACK:-false}
      # Security
      - SECRET_KEY=\${SECRET_KEY:-}
      - RATE_LIMIT_REQUESTS_PER_MINUTE=\${RATE_LIMIT_REQUESTS_PER_MINUTE:-60}
      - RATE_LIMIT_BURST_SIZE=\${RATE_LIMIT_BURST_SIZE:-10}
      # Monitoring
      - SENTRY_DSN=\${SENTRY_DSN:-}
      # Feature flags
      - ENABLE_GPU_PROVIDERS=\${ENABLE_GPU_PROVIDERS:-true}
      - ENABLE_CLOUDFLARE_TUNNEL=true
    
    volumes:
      - devplane-data:/app/data
      - ./static:/app/static:ro
    
    networks:
      - devplane-network
    
    # Production health check
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    
    # Resource limits for cost optimization
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
    
    depends_on:
      qdrant:
        condition: service_healthy

  # ═════════════════════════════════════════════════════════════════════════════
  # Qdrant Vector Database
  # ═════════════════════════════════════════════════════════════════════════════
  qdrant:
    image: qdrant/qdrant:latest
    container_name: devplane-qdrant
    restart: unless-stopped
    
    volumes:
      - qdrant-data:/qdrant/storage
    
    networks:
      - devplane-network
    
    environment:
      - QDRANT__SERVICE__API_KEY=\${QDRANT_KEY:-}
      - QDRANT__SERVICE__HTTP_PORT=6333
      - QDRANT__SERVICE__GRPC_PORT=6334
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 256M

  # ═════════════════════════════════════════════════════════════════════════════
  # Cloudflare Tunnel (Secure Public Access)
  # No firewall ports needed - outbound-only connection
  # ═════════════════════════════════════════════════════════════════════════════
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: devplane-tunnel
    restart: unless-stopped
    
    command: tunnel --no-autoupdate run --token \${TUNNEL_TOKEN}
    
    environment:
      - TUNNEL_TOKEN=\${TUNNEL_TOKEN}
    
    networks:
      - devplane-network
    
    # No ports exposed - tunnel connects outbound to Cloudflare
    # This provides secure HTTPS without opening firewall ports
    
    depends_on:
      devplane:
        condition: service_healthy
    
    deploy:
      resources:
        limits:
          cpus: '0.25'
          memory: 128M

  # ═════════════════════════════════════════════════════════════════════════════
  # Prometheus Metrics Collection
  # ═════════════════════════════════════════════════════════════════════════════
  prometheus:
    image: prom/prometheus:latest
    container_name: devplane-prometheus
    restart: unless-stopped
    
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=15d'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
      - '--web.enable-lifecycle'
    
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    
    networks:
      - devplane-network
    
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M

  # ═════════════════════════════════════════════════════════════════════════════
  # Grafana Visualization
  # ═════════════════════════════════════════════════════════════════════════════
  grafana:
    image: grafana/grafana:latest
    container_name: devplane-grafana
    restart: unless-stopped
    
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=\${GRAFANA_PASSWORD:-admin}
      - GF_SECURITY_ADMIN_USER=\${GRAFANA_USER:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_SERVER_ROOT_URL=https://grafana.${DOMAIN}
    
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    
    networks:
      - devplane-network
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

# ═══════════════════════════════════════════════════════════════════════════════
# Volumes
# ═══════════════════════════════════════════════════════════════════════════════
volumes:
  devplane-data:
    driver: local
  qdrant-data:
    driver: local
  prometheus-data:
    driver: local
  grafana-data:
    driver: local

# ═══════════════════════════════════════════════════════════════════════════════
# Networks
# ═══════════════════════════════════════════════════════════════════════════════
networks:
  devplane-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
COMPOSE_EOF

    log_success "Production Docker Compose file created: $compose_file"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Create monitoring configuration
# ═══════════════════════════════════════════════════════════════════════════════
setup_monitoring() {
    log_step "Setting up monitoring configuration..."
    
    # Create monitoring directories
    mkdir -p "$SCRIPT_DIR/monitoring/grafana/dashboards"
    mkdir -p "$SCRIPT_DIR/monitoring/grafana/datasources"
    
    # Create Prometheus config if not exists
    if [[ ! -f "$SCRIPT_DIR/monitoring/prometheus.yml" ]]; then
        cat > "$SCRIPT_DIR/monitoring/prometheus.yml" << 'PROMETHEUS_EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  # - "first_rules.yml"

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'devplane'
    static_configs:
      - targets: ['devplane:8000']
    metrics_path: '/api/metrics'
    scrape_interval: 30s
PROMETHEUS_EOF
        log_success "Prometheus configuration created"
    fi
    
    # Create Grafana datasource config
    cat > "$SCRIPT_DIR/monitoring/grafana/datasources/datasources.yml" << 'GRAFANA_DS_EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
GRAFANA_DS_EOF
    
    log_success "Monitoring configuration complete"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Deploy with Docker Compose
# ═══════════════════════════════════════════════════════════════════════════════
deploy_docker() {
    log_step "Deploying with Docker Compose..."
    
    # Ensure docker-compose.prod.yml exists
    if [[ ! -f "$SCRIPT_DIR/docker-compose.prod.yml" ]]; then
        create_docker_compose
    fi
    
    # Pull latest images
    log_info "Pulling latest images..."
    docker-compose -f "$SCRIPT_DIR/docker-compose.prod.yml" pull
    
    # Start services
    log_info "Starting services..."
    docker-compose -f "$SCRIPT_DIR/docker-compose.prod.yml" up -d --remove-orphans
    
    # Wait for services to be healthy
    log_info "Waiting for services to be healthy..."
    sleep 10
    
    local retries=0
    local max_retries=30
    
    while [[ $retries -lt $max_retries ]]; do
        if curl -sf "http://localhost:8000/api/health" > /dev/null 2>&1; then
            log_success "DevPlane is healthy!"
            break
        fi
        
        retries=$((retries + 1))
        log_info "Waiting for DevPlane to be ready... ($retries/$max_retries)"
        sleep 5
    done
    
    if [[ $retries -eq $max_retries ]]; then
        log_error "DevPlane failed to become healthy within timeout"
        show_logs
        exit 1
    fi
    
    log_success "Deployment complete!"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Show deployment status
# ═══════════════════════════════════════════════════════════════════════════════
show_status() {
    log_step "Deployment Status"
    echo "================================================"
    
    # Docker status
    if docker-compose -f "$SCRIPT_DIR/docker-compose.prod.yml" ps &> /dev/null; then
        log_info "Docker containers:"
        docker-compose -f "$SCRIPT_DIR/docker-compose.prod.yml" ps
    fi
    
    echo ""
    log_info "Health checks:"
    
    # Check DevPlane health
    if curl -sf "http://localhost:8000/api/health" > /dev/null 2>&1; then
        log_success "DevPlane API: Healthy"
        local health_json
        health_json=$(curl -s "http://localhost:8000/api/health")
        echo "  Status: $(echo "$health_json" | jq -r '.status // "unknown"')"
    else
        log_error "DevPlane API: Unhealthy"
    fi
    
    # Check tunnel status via Cloudflare API
    if [[ -n "${TUNNEL_ID:-}" ]]; then
        log_info "Cloudflare Tunnel:"
        echo "  Name: $TUNNEL_NAME"
        echo "  ID: $TUNNEL_ID"
        echo "  Domain: https://$DOMAIN"
    fi
    
    echo ""
    log_info "Access URLs:"
    echo "  🌐 Application: https://$DOMAIN"
    echo "  🌐 Application: https://www.$DOMAIN"
    echo "  📊 Health Check: http://localhost:8000/api/health"
    echo "  📈 Metrics: http://localhost:8000/api/metrics"
    
    if [[ -n "${TUNNEL_TOKEN:-}" ]]; then
        echo "  🔒 Public URL: https://$DOMAIN (via Cloudflare Tunnel)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Show logs
# ═══════════════════════════════════════════════════════════════════════════════
show_logs() {
    log_step "Showing logs..."
    docker-compose -f "$SCRIPT_DIR/docker-compose.prod.yml" logs -f --tail=100
}

# ═══════════════════════════════════════════════════════════════════════════════
# Destroy deployment
# ═══════════════════════════════════════════════════════════════════════════════
destroy_deployment() {
    log_warn "This will destroy the deployment and ALL DATA!"
    read -p "Are you sure? Type 'destroy' to confirm: " confirm
    
    if [[ "$confirm" != "destroy" ]]; then
        log_info "Destruction cancelled"
        return
    fi
    
    log_step "Destroying deployment..."
    
    # Stop and remove containers
    docker-compose -f "$SCRIPT_DIR/docker-compose.prod.yml" down -v
    
    # Optionally delete tunnel
    read -p "Delete Cloudflare Tunnel? (y/N): " delete_tunnel
    if [[ "$delete_tunnel" == "y" || "$delete_tunnel" == "Y" ]]; then
        ensure_tunnel_helper
        local existing_tunnel
        existing_tunnel=$(python3 "$SCRIPT_DIR/.tunnel-helper.py" list | jq -r ".[] | select(.name == \"$TUNNEL_NAME\") | .id")
        
        if [[ -n "$existing_tunnel" ]]; then
            log_info "Deleting tunnel $existing_tunnel..."
            python3 "$SCRIPT_DIR/.tunnel-helper.py" delete --tunnel-id "$existing_tunnel"
            log_success "Tunnel deleted"
        fi
    fi
    
    log_success "Deployment destroyed"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main deployment flow
# ═══════════════════════════════════════════════════════════════════════════════
main_deploy() {
    log_info "🚀 DevPlane Production Deployment for $DOMAIN"
    echo "================================================"
    
    load_env
    check_prerequisites
    manage_tunnel
    setup_dns
    setup_monitoring
    create_docker_compose
    deploy_docker
    show_status
    
    echo ""
    log_success "🎉 Deployment complete!"
    log_info "Your application is now available at: https://$DOMAIN"
    log_info "Tunnel provides secure HTTPS without opening firewall ports"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Command handler
# ═══════════════════════════════════════════════════════════════════════════════
case "${1:-deploy}" in
    deploy)
        main_deploy
        ;;
    tunnel-only)
        load_env
        check_prerequisites
        manage_tunnel
        setup_dns
        log_success "Tunnel setup complete!"
        log_info "Add TUNNEL_TOKEN to your .env and restart your services"
        ;;
    status)
        load_env
        show_status
        ;;
    logs)
        show_logs
        ;;
    destroy)
        destroy_deployment
        ;;
    update)
        load_env
        deploy_docker
        show_status
        ;;
    *)
        echo "DevPlane Production Deployment Script"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  deploy       - Full deployment (default)"
        echo "  tunnel-only  - Setup Cloudflare Tunnel only"
        echo "  status       - Show deployment status"
        echo "  logs         - View application logs"
        echo "  update       - Update/redeploy containers"
        echo "  destroy      - Destroy deployment and data"
        echo ""
        echo "Examples:"
        echo "  $0                    # Full deployment"
        echo "  $0 tunnel-only        # Setup tunnel only"
        echo "  $0 status             # Check status"
        ;;
esac
