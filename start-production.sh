#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# DevPlane Production Startup Script
# ═══════════════════════════════════════════════════════════════════════════════

set -e

echo "🚀 Starting DevPlane Production Server"
echo "======================================"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please create one from .env.example:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

# Load environment
export $(grep -v '^#' .env | xargs)

# Check required environment variables
if [ -z "$SECRET_KEY" ]; then
    echo "⚠️  SECRET_KEY not set, generating one..."
    export SECRET_KEY=$(openssl rand -hex 32)
    echo "SECRET_KEY=$SECRET_KEY" >> .env
fi

# Create data directories
mkdir -p data
mkdir -p logs

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python version: $PYTHON_VERSION"

# Check if dependencies are installed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Run database migrations (if needed)
echo "🗄️  Checking database..."
python3 -c "
import asyncio
from devplane.db import init_db
asyncio.run(init_db())
"

# Load API keys into environment
echo "🔑 Loading provider keys..."
python3 -c "
import asyncio
from devplane.providers import load_all_keys_to_env
asyncio.run(load_all_keys_to_env())
"

# Start the server
echo ""
echo "🌐 Starting server on http://0.0.0.0:8000"
echo "======================================"
echo ""
echo "Access URLs:"
echo "  - Dashboard: http://localhost:8000"
echo "  - Health:    http://localhost:8000/api/health"
echo "  - Metrics:   http://localhost:8000/api/metrics"
echo ""
echo "Press Ctrl+C to stop"
echo ""

exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
