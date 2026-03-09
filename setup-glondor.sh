#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Cloudflare Setup Script
# Run this after DNS is pointed to your server
# ═══════════════════════════════════════════════════════════════════════════════

set -e

DOMAIN="${DEPLOYMENT_DOMAIN:-glondor.xyz}"

echo "☁️  Cloudflare Setup for $DOMAIN"
echo "================================"

# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    sudo dpkg -i cloudflared-linux-amd64.deb
    rm cloudflared-linux-amd64.deb
fi

# Login to Cloudflare
echo ""
echo "🔐 Please login to Cloudflare..."
cloudflared tunnel login

# Create tunnel
echo ""
echo "🚇 Creating tunnel..."
TUNNEL_NAME="devplane-$(date +%s)"
TUNNEL_OUTPUT=$(cloudflared tunnel create $TUNNEL_NAME)
TUNNEL_ID=$(echo "$TUNNEL_OUTPUT" | grep -oP 'id: \K[a-f0-9-]+' || echo "")

if [ -z "$TUNNEL_ID" ]; then
    echo "❌ Failed to create tunnel"
    exit 1
fi

echo "✅ Tunnel created: $TUNNEL_ID"

# Create DNS record
cloudflared tunnel route dns $TUNNEL_ID $DOMAIN
cloudflared tunnel route dns $TUNNEL_ID www.$DOMAIN

# Get tunnel token
TUNNEL_TOKEN=$(cloudflared tunnel token $TUNNEL_ID)

# Create config file
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: $TUNNEL_ID
credentials-file: ~/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    service: http://localhost:8000
  - hostname: www.$DOMAIN
    service: http://localhost:8000
  - service: http_status:404
EOF

echo ""
echo "✅ Cloudflare Tunnel configured!"
echo ""
echo "🔑 Tunnel Token (save this for .env):"
echo "$TUNNEL_TOKEN"
echo ""
echo "📋 Add this to your .env file:"
echo "TUNNEL_TOKEN=$TUNNEL_TOKEN"
echo ""
echo "🚀 To start the tunnel:"
echo "  cloudflared tunnel run $TUNNEL_ID"
echo ""
echo "⚙️  To install as a service:"
echo "  sudo cloudflared service install $TUNNEL_TOKEN"
echo "  sudo systemctl enable cloudflared"
echo "  sudo systemctl start cloudflared"
