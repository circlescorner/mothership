import os
import paramiko

# Read local token
try:
    with open('.env', 'r', encoding='utf-8') as f:
        token = [line.split('=', 1)[1].strip() for line in f if 'TUNNEL_TOKEN' in line and 'ey' in line][0]
    print(f"Found token: {token[:10]}...")
except Exception as e:
    print(f"Failed to find token locally: {e}")
    token = ""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("167.99.229.228", username="root", key_filename=os.path.expanduser("~/.ssh/id_rsa"))

# 1. Update docker-compose.prod.yml
sed_cmd1 = "sed -i '/- \\.\\/devplane\\.db:\\/app\\/devplane\\.db/d' /opt/devplane/docker-compose.prod.yml"
sed_cmd2 = "sed -i 's/DEVPLANE_DB_PATH=\\/app\\/devplane\\.db/DEVPLANE_DB_PATH=\\/app\\/data\\/devplane\\.db/' /opt/devplane/docker-compose.prod.yml"

# 2. Fix .env TUNNEL_TOKEN appending safely
env_fix = f"grep -q 'TUNNEL_TOKEN' /opt/devplane/.env && sed -i 's|^.*TUNNEL_TOKEN.*|TUNNEL_TOKEN={token}|' /opt/devplane/.env || echo 'TUNNEL_TOKEN={token}' >> /opt/devplane/.env"

# 3. Apply changes and restart
cmds = [
    sed_cmd1,
    sed_cmd2,
    env_fix,
    "cd /opt/devplane && docker-compose -f docker-compose.prod.yml down",
    "cd /opt/devplane && docker-compose -f docker-compose.prod.yml up -d"
]

for cmd in cmds:
    print(f"Running: {cmd[:60]}")
    stdin, stdout, stderr = client.exec_command(cmd)
    stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    if err:
        print("Error:", err)

client.close()
print("Done")
