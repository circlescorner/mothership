import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from devplane.infra.manager import InfraManager

load_dotenv()

async def main():
    mgr = InfraManager()
    
    # Read the generated game
    with open('/tmp/glondor_game/index.html', 'r', encoding='utf-8') as f:
        game_html = f.read()

    # Escape HTML for bash injection
    # We will use base64 to avoid quotes/formatting issues
    import base64
    b64_html = base64.b64encode(game_html.encode('utf-8')).decode('utf-8')

    user_data = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y

# Install nginx and cloudflared
apt-get install -y nginx
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared.deb

# Write game file
echo "{b64_html}" | base64 -d > /var/www/html/index.html
systemctl restart nginx

echo "Game deployed and Nginx running. Ready for Cloudflare Tunnel."
"""
    
    print("Spinning up game droplet...")
    result = await mgr.create_droplet("glondor-game-node", size="s-1vcpu-1gb", user_data=user_data)
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
