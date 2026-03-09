# DevPlane Server Setup Guide

Complete setup instructions for deploying DevPlane on a server (VPS).

> **Note:** This guide uses `yourdomain.com` as a placeholder. Replace it with your actual domain name (e.g., `glondor.xyz`).

---

## Prerequisites

- A server (VPS) with Ubuntu 22.04+ (DigitalOcean, AWS, etc.)
- Domain name pointed to your server's IP (A record)
- Cloudflare account with your domain added as a zone

---

## Quick Start

```bash
# 1. SSH into your server
ssh root@your-server-ip

# 2. Clone the repository
git clone <repo-url> /opt/devplane
cd /opt/devplane

# 3. Create .env file
cp .env.example .env
nano .env  # Edit with your API keys and domain

# 4. Run full installation using the deployment orchestrator
python deployments/orchestrator.py --env production --phase all
```

---

## Detailed Setup Steps

### 1. Server Preparation

On a fresh Ubuntu 22.04 server:

```bash
# Update system
apt update && apt upgrade -y

# Set hostname (replace 'devplane' with your preferred hostname)
hostnamectl set-hostname devplane

# Create swap (if < 2GB RAM)
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Install Python and dependencies
apt install -y python3 python3-pip python3-venv git
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

Type: A
Name: cp
Value: YOUR_SERVER_IP
TTL: Auto
```

> **Note:** The `cp` subdomain is used for the control panel (e.g., `cp.yourdomain.com`).

### 3. Cloudflare Configuration

1. Add your domain to Cloudflare
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
DEPLOYMENT_DOMAIN=yourdomain.com
DEPLOYMENT_MODE=remote
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com,https://cp.yourdomain.com

# Cloudflare (from setup-glondor.sh output)
TUNNEL_TOKEN=your-tunnel-token-here
CLOUDFLARE_API_TOKEN=your-cloudflare-api-token-here
CLOUDFLARE_EMAIL=your-email@example.com
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_ZONE_ID=your-zone-id
CLOUDFLARE_DOMAIN=yourdomain.com

# AI Providers (configure at least 2-3)
DEEPSEEK_API_KEY=sk-...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=sk-or-v1-...

# Infrastructure
DIGITALOCEAN_TOKEN=dop_v1_...
DIGITALOCEAN_REGION=nyc1

# Database
DATABASE_URL=sqlite+aiosqlite:///./devplane.db

# Security
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)

# Vector DB (optional)
QDRANT_URL=https://your-cluster.qdrant.tech
QDRANT_KEY=your-key
```

### 5. Deploy Application

Using the new deployment orchestrator:

```bash
# Validate configuration first (dry-run)
python deployments/orchestrator.py --env production --phase discover --dry-run

# Provision infrastructure
python deployments/orchestrator.py --env production --phase provision

# Configure and deploy
python deployments/orchestrator.py --env production --phase configure
python deployments/orchestrator.py --env production --phase deploy

# Verify deployment
python deployments/orchestrator.py --env production --phase verify
```

Or run the full pipeline:

```bash
python deployments/orchestrator.py --env production --phase all
```

### 6. Verify Deployment

Visit these URLs:
- https://yourdomain.com - Main dashboard
- https://cp.yourdomain.com - Control panel
- https://yourdomain.com/api/health - Health check
- https://yourdomain.com/api/status - System status

### 7. Configure Providers

1. Visit https://cp.yourdomain.com or https://yourdomain.com
2. Go to Settings → Providers
3. Add your API keys for each AI provider
4. Test connections

---

## Maintenance

### Update Application

```bash
cd /opt/devplane
git pull origin main

# Re-deploy using orchestrator
python deployments/orchestrator.py --env production --phase deploy
```

### View Logs

```bash
# If using systemd service
journalctl -u devplane -n 100

# If using Docker
docker-compose logs -f devplane

# Application logs
tail -f /opt/devplane/logs/devplane.log
```

### Renew SSL Certificate

If using Let's Encrypt (without Cloudflare Tunnel):

```bash
sudo certbot renew --force-renewal
```

With Cloudflare Tunnel, SSL is handled automatically by Cloudflare.

### Backup Database

```bash
# Create backup directory
mkdir -p /opt/devplane/backups

# Create backup
cp /opt/devplane/devplane.db /opt/devplane/backups/devplane-$(date +%Y%m%d).db

# Or automated daily backup
crontab -e
# Add: 0 2 * * * cp /opt/devplane/devplane.db /opt/devplane/backups/devplane-$(date +\%Y\%m\%d).db
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs
journalctl -u devplane -n 100

# Check environment
systemctl show devplane --property=Environment

# Manual test
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
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com

# Renew manually (if not using Cloudflare Tunnel)
sudo certbot renew --force-renewal
```

### Configuration Validation

```bash
# Validate configuration
python deployments/orchestrator.py --env production --phase discover --dry-run
```

---

## Security Checklist

- [ ] All API keys configured
- [ ] Cloudflare Tunnel active
- [ ] SSL certificate valid (or Cloudflare Tunnel in use)
- [ ] Firewall enabled (ufw)
- [ ] Automatic security updates enabled
- [ ] Backups configured
- [ ] Monitoring enabled
- [ ] Strong SECRET_KEY and JWT_SECRET generated
- [ ] CORS_ORIGINS restricted to your domains only

---

## Support

For issues or questions:
1. Check logs: `journalctl -u devplane -n 100`
2. Check status: `python deployments/orchestrator.py --env production --phase discover --dry-run`
3. Review health endpoint: https://yourdomain.com/api/health/detailed
4. See [DEPLOYMENT.md](DEPLOYMENT.md) for deployment documentation
5. See [USER_GUIDE.md](USER_GUIDE.md) for usage instructions
