import os
import sys

# Read TUNNEL_TOKEN locally
token = None
try:
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            if 'TUNNEL_TOKEN' in line and 'ey' in line:
                token = line.split('=', 1)[1].strip()
                break
except Exception as e:
    print(f"Failed reading .env: {e}")

if not token:
    print("WARNING: Token not found locally")
else:
    print(f"Found token starting with {token[:10]}...")

import paramiko

print("Connecting to Droplet...")
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("167.99.229.228", username="root", key_filename=os.path.expanduser("~/.ssh/id_rsa"))

    # Fix db issue and token
    env_update_cmd = f"sed -i 's/^.*TUNNEL_TOKEN=.*/TUNNEL_TOKEN={token}/' /opt/devplane/.env" if token else "echo 'No token'"
    
    cmds = [
        "rm -rf /opt/devplane/devplane.db",
        "touch /opt/devplane/devplane.db",
        "chown 1000:1000 /opt/devplane/devplane.db",
        env_update_cmd,
        "cd /opt/devplane && docker-compose -f docker-compose.prod.yml restart"
    ]
    for cmd in cmds:
        print(f"Running: {cmd[:50]}...")
        stdin, stdout, stderr = client.exec_command(cmd)
        stdout.channel.recv_exit_status()
        err = stderr.read().decode('utf-8')
        if err:
            print(f"Error: {err}")
    client.close()
    print("Fix script completed successfully!")
except Exception as e:
    print(f"Connection/exec failed: {e}")
