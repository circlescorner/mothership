#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# DevPlane Deployment Script for glondor.xyz
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 DevPlane Deployment Script for glondor.xyz${NC}"
echo "================================================"

# Configuration
DOMAIN="glondor.xyz"
DEPLOY_DIR="/opt/devplane"
SERVICE_NAME="devplane"

# Check if running as root for installation
if [ "$EUID" -ne 0 ] && [ "$1" == "install" ]; then 
    echo -e "${RED}Please run as root for installation: sudo ./deploy-glondor.sh install${NC}"
    exit 1
fi

# Function to install dependencies
install_deps() {
    echo -e "${YELLOW}📦 Installing dependencies...${NC}"
    apt-get update
    apt-get install -y \
        python3-pip \
        python3-venv \
        docker.io \
        docker-compose \
        nginx \
        certbot \
        python3-certbot-nginx \
        git \
        curl \
        sqlite3
    
    # Install cloudflared
    if ! command -v cloudflared &> /dev/null; then
        echo -e "${YELLOW}Installing cloudflared...${NC}"
        wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
        dpkg -i cloudflared-linux-amd64.deb
        rm cloudflared-linux-amd64.deb
    fi
    
    echo -e "${GREEN}✅ Dependencies installed${NC}"
}

# Function to setup directory structure
setup_directories() {
    echo -e "${YELLOW}📁 Setting up directory structure...${NC}"
    mkdir -p $DEPLOY_DIR
    mkdir -p $DEPLOY_DIR/data
    mkdir -p $DEPLOY_DIR/data/qdrant
    mkdir -p $DEPLOY_DIR/logs
    mkdir -p /var/log/devplane
    
    # Create user if doesn't exist
    if ! id "devplane" &>/dev/null; then
        useradd -r -s /bin/false devplane
    fi
    
    chown -R devplane:devplane $DEPLOY_DIR
    echo -e "${GREEN}✅ Directories created${NC}"
}

# Function to deploy application
deploy_app() {
    echo -e "${YELLOW}🚀 Deploying application...${NC}"
    
    # Copy application files
    cp -r devplane/ $DEPLOY_DIR/
    cp -r static/ $DEPLOY_DIR/
    cp main.py $DEPLOY_DIR/
    cp requirements.txt $DEPLOY_DIR/
    cp docker-compose.yml $DEPLOY_DIR/
    cp Dockerfile $DEPLOY_DIR/
    cp .env $DEPLOY_DIR/ 2>/dev/null || echo -e "${YELLOW}⚠️  No .env file found. Please create one.${NC}"
    
    chown -R devplane:devplane $DEPLOY_DIR
    echo -e "${GREEN}✅ Application deployed${NC}"
}

# Function to create systemd service
create_service() {
    echo -e "${YELLOW}⚙️  Creating systemd service...${NC}"
    
    cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=DevPlane AI Control Plane
After=network.target

[Service]
Type=simple
User=devplane
WorkingDirectory=$DEPLOY_DIR
Environment=PATH=/usr/local/bin:/usr/bin
Environment=DEVPLANE_DB_PATH=$DEPLOY_DIR/devplane.db
Environment=ENV=production
EnvironmentFile=$DEPLOY_DIR/.env
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    echo -e "${GREEN}✅ Service created${NC}"
}

# Function to setup nginx
setup_nginx() {
    echo -e "${YELLOW}🌐 Configuring Nginx...${NC}"
    
    cat > /etc/nginx/sites-available/devplane <<EOF
server {
    listen 80;
    server_name glondor.xyz www.glondor.xyz;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
        
        # SSE support
        proxy_buffering off;
        proxy_read_timeout 86400;
    }
    
    location /static {
        alias $DEPLOY_DIR/static;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

    ln -sf /etc/nginx/sites-available/devplane /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
    echo -e "${GREEN}✅ Nginx configured${NC}"
}

# Function to setup SSL
setup_ssl() {
    echo -e "${YELLOW}🔒 Setting up SSL with Let's Encrypt...${NC}"
    certbot --nginx -d glondor.xyz -d www.glondor.xyz --non-interactive --agree-tos --email admin@glondor.xyz || true
    echo -e "${GREEN}✅ SSL configured${NC}"
}

# Function to setup Cloudflare Tunnel
setup_cloudflare_tunnel() {
    echo -e "${YELLOW}☁️  Setting up Cloudflare Tunnel...${NC}"
    
    if [ -z "$TUNNEL_TOKEN" ]; then
        echo -e "${YELLOW}⚠️  TUNNEL_TOKEN not set. Skipping tunnel setup.${NC}"
        echo "To setup tunnel later, run:"
        echo "  export TUNNEL_TOKEN=your-token"
        echo "  cloudflared service install \$TUNNEL_TOKEN"
        return
    fi
    
    cloudflared service install $TUNNEL_TOKEN
    systemctl enable cloudflared
    systemctl start cloudflared
    echo -e "${GREEN}✅ Cloudflare Tunnel configured${NC}"
}

# Function to start services
start_services() {
    echo -e "${YELLOW}▶️  Starting services...${NC}"
    systemctl enable $SERVICE_NAME
    systemctl start $SERVICE_NAME
    echo -e "${GREEN}✅ Services started${NC}"
}

# Function to check status
check_status() {
    echo -e "${BLUE}📊 Checking deployment status...${NC}"
    echo "================================================"
    
    # Check service status
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo -e "${GREEN}✅ DevPlane service: Running${NC}"
    else
        echo -e "${RED}❌ DevPlane service: Not running${NC}"
        systemctl status $SERVICE_NAME --no-pager
    fi
    
    # Check nginx
    if systemctl is-active --quiet nginx; then
        echo -e "${GREEN}✅ Nginx: Running${NC}"
    else
        echo -e "${RED}❌ Nginx: Not running${NC}"
    fi
    
    # Check health endpoint
    if curl -sf http://localhost:8000/api/health > /dev/null; then
        echo -e "${GREEN}✅ Health check: Passing${NC}"
    else
        echo -e "${RED}❌ Health check: Failing${NC}"
    fi
    
    echo ""
    echo -e "${BLUE}🌐 Access URLs:${NC}"
    echo "  - Application: https://glondor.xyz"
    echo "  - Health: https://glondor.xyz/api/health"
    echo "  - Metrics: https://glondor.xyz/api/metrics"
}

# Function to view logs
view_logs() {
    journalctl -u $SERVICE_NAME -f
}

# Main command handler
case "${1:-}" in
    install)
        echo -e "${BLUE}🔧 Full installation...${NC}"
        install_deps
        setup_directories
        deploy_app
        create_service
        setup_nginx
        setup_ssl
        setup_cloudflare_tunnel
        start_services
        check_status
        echo ""
        echo -e "${GREEN}🎉 Installation complete!${NC}"
        ;;
    deploy)
        echo -e "${BLUE}🚀 Deploying application...${NC}"
        systemctl stop $SERVICE_NAME 2>/dev/null || true
        deploy_app
        systemctl start $SERVICE_NAME
        check_status
        echo -e "${GREEN}🎉 Deployment complete!${NC}"
        ;;
    status)
        check_status
        ;;
    logs)
        view_logs
        ;;
    ssl)
        setup_ssl
        ;;
    tunnel)
        setup_cloudflare_tunnel
        ;;
    *)
        echo "DevPlane Deployment Script for glondor.xyz"
        echo ""
        echo "Usage: sudo ./deploy-glondor.sh [command]"
        echo ""
        echo "Commands:"
        echo "  install   - Full installation (run once)"
        echo "  deploy    - Deploy/update application"
        echo "  status    - Check deployment status"
        echo "  logs      - View application logs"
        echo "  ssl       - Renew/setup SSL certificate"
        echo "  tunnel    - Setup Cloudflare tunnel"
        echo ""
        echo "Examples:"
        echo "  sudo ./deploy-glondor.sh install    # First time setup"
        echo "  ./deploy-glondor.sh deploy          # Update app"
        echo "  ./deploy-glondor.sh status          # Check status"
        ;;
esac
