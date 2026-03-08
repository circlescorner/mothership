# DevPlane Setup Guide for glondor.xyz

Complete setup instructions for deploying DevPlane to glondor.xyz

## Prerequisites

- A server (VPS) with Ubuntu 22.04+ (DigitalOcean, AWS, etc.)
- Domain `glondor.xyz` pointed to your server's IP (A record)
- Cloudflare account with glondor.xyz added as a zone

## Quick Start

```bash
# 1. SSH into your server
ssh root@your-server-ip

# 2. Clone the repository
git clone <repo-url> /opt/devplane
cd /opt/devplane

# 3. Create .env file
cp .env.example .env
nano .env  # Edit with your API keys

# 4. Run full installation
sudo ./deploy-glondor.sh install
```

## Detailed Setup Steps

### 1. Server Preparation

On a fresh Ubuntu 22.04 server:

```bash
# Update system
apt update && apt upgrade -y

# Set hostname
hostnamectl set-hostname devplane

# Create swap (if < 2GB RAM)
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 2. DNS Configuration

In your domain registrar/DNS provider:

```
Type: A
Name: @
Value: YOUR_SERVER_IP
TTL: Auto

Type: A
Name: www
Value: YOUR_SERVER_IP
TTL: Auto
```

### 3. Cloudflare Configuration

1. Add `glondor.xyz` to Cloudflare
2. Change nameservers at your registrar to Cloudflare's
3. Wait for DNS propagation (can take up to 24 hours)

Run the Cloudflare setup script:

```bash
./setup-glondor.sh
```

This will:
- Authenticate with Cloudflare
- Create a tunnel
- Generate a TUNNEL_TOKEN
- Output the token for your .env file

### 4. Environment Configuration

Create the `.env` file:

```bash
cp .env.example .env
nano .env
```

Minimum required configuration:

```env
# Server
ENV=production
CORS_ORIGINS=https://glondor.xyz,https://www.glondor.xyz

# Cloudflare (from setup-glondor.sh output)
TUNNEL_TOKEN=your-tunnel-token-here
CLOUDFLARE_API_KEY=your-cloudflare-global-api-key
CLOUDFLARE_EMAIL=your-email@example.com
CLOUDFLARE_ZONE_ID=your-zone-id
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_DOMAIN=glondor.xyz

# AI Providers (configure at least 2-3)
DEEPSEEK_API_KEY=sk-...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=sk-or-v1-...

# Infrastructure
DIGITALOCEAN_TOKEN=dop_v1_...
DIGITALOCEAN_REGION=nyc1

# Vector DB (optional)
QDRANT_URL=https://your-cluster.qdrant.tech
QDRANT_KEY=your-key

# Security
SECRET_KEY=$(openssl rand -hex 32)
```

### 5. Deploy Application

```bash
# Full installation
sudo ./deploy-glondor.sh install

# Check status
./deploy-glondor.sh status
```

### 6. Verify Deployment

Visit these URLs:
- https://glondor.xyz - Main dashboard
- https://glondor.xyz/api/health - Health check
- https://glondor.xyz/api/status - System status

### 7. Configure Providers

1. Visit https://glondor.xyz
2. Go to Settings → Providers
3. Add your API keys for each AI provider
4. Test connections

## Maintenance

### Update Application

```bash
cd /opt/devplane
git pull origin main
sudo ./deploy-glondor.sh deploy
```

### View Logs

```bash
./deploy-glondor.sh logs
```

### Renew SSL Certificate

```bash
sudo ./deploy-glondor.sh ssl
```

### Backup Database

```bash
# Create backup
cp /opt/devplane/devplane.db /opt/devplane/backups/devplane-$(date +%Y%m%d).db

# Or automated daily backup
crontab -e
# Add: 0 2 * * * cp /opt/devplane/devplane.db /opt/devplane/backups/devplane-$(date +\%Y\%m\%d).db
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
journalctl -u devplane -n 100

# Check environment
systemctl show devplane --property=Environment

# Manual test
su - devplane -s /bin/bash
cd /opt/devplane
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### Cloudflare Tunnel Issues

```bash
# Check tunnel status
cloudflared tunnel list

# Check tunnel logs
journalctl -u cloudflared -n 100

# Restart tunnel
sudo systemctl restart cloudflared
```

### SSL Certificate Issues

```bash
# Test certificate
openssl s_client -connect glondor.xyz:443 -servername glondor.xyz

# Renew manually
sudo certbot renew --force-renewal
```

## Security Checklist

- [ ] All API keys configured
- [ ] Cloudflare Tunnel active
- [ ] SSL certificate valid
- [ ] Firewall enabled (ufw)
- [ ] Automatic security updates enabled
- [ ] Backups configured
- [ ] Monitoring enabled

## Support

For issues or questions:
1. Check logs: `./deploy-glondor.sh logs`
2. Check status: `./deploy-glondor.sh status`
3. Review health endpoint: https://glondor.xyz/api/health/detailed
