#!/usr/bin/env python3
"""
Cloudflare Configuration Script
Updates DNS records and configures SSL for DevPlane
Uses Cloudflare Origin CA certificates (not Let's Encrypt)
Adapted for Mothership
"""

import os
import sys
import json
import subprocess
import argparse
from typing import Dict, List, Optional

def load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        print(f"[ERROR] {env_path} not found")
        sys.exit(1)
    
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

class CloudflareConfigurator:
    def __init__(self):
        self.token = os.getenv('CLOUDFLARE_API_TOKEN')
        self.zone_id = os.getenv('CLOUDFLARE_ZONE_ID')
        self.domain = os.getenv('DOMAIN_NAME', 'glondor.xyz')
        # We target the existing Gate Droplet IP
        self.gate_ip = os.getenv('GATE_RESERVED_IP', '24.144.64.217')
        
        if not self.token:
            raise ValueError("CLOUDFLARE_API_TOKEN not set")
        if not self.zone_id:
            raise ValueError("CLOUDFLARE_ZONE_ID not set")
    
    def _cf_api(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Dict:
        url = f"https://api.cloudflare.com/client/v4/{endpoint}"
        cmd = [
            "curl", "-s", "-X", method,
            "-H", f"Authorization: Bearer {self.token}",
            "-H", "Content-Type: application/json"
        ]
        if data:
            cmd.extend(["-d", json.dumps(data)])
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"API call failed: {result.stderr}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw": result.stdout}
    
    def get_dns_records(self) -> List[Dict]:
        result = self._cf_api(f"zones/{self.zone_id}/dns_records")
        if not result.get('success'):
            print(f"[ERROR] API failed: {result}")
        return result.get('result') or []
    
    def update_dns_record(self, record_id: str, record_type: str, name: str, content: str, proxied: bool = True) -> Dict:
        data = {"type": record_type, "name": name, "content": content, "proxied": proxied, "ttl": 1}
        return self._cf_api(f"zones/{self.zone_id}/dns_records/{record_id}", "PUT", data)
    
    def create_dns_record(self, record_type: str, name: str, content: str, proxied: bool = True) -> Dict:
        data = {"type": record_type, "name": name, "content": content, "proxied": proxied, "ttl": 1}
        return self._cf_api(f"zones/{self.zone_id}/dns_records", "POST", data)
    
    def update_all_dns_to_gate(self) -> None:
        print(f"[INFO] Updating DNS records to point to {self.gate_ip}...")
        records = self.get_dns_records()
        
        gate_records = ['@', 'cp', 'admin', 'www', 'dev']
        updated = 0
        created = 0
        
        for record in records:
            if record.get('type') == 'A':
                name = record.get('name', '').replace(f".{self.domain}", "").replace(self.domain, "@")
                record_id = record.get('id')
                current_ip = record.get('content')
                
                if name in gate_records and current_ip != self.gate_ip:
                    print(f"  Updating {name}.{self.domain}: {current_ip} -> {self.gate_ip}")
                    self.update_dns_record(record_id, 'A', name if name != '@' else self.domain, self.gate_ip)
                    updated += 1
        
        existing_names = {r.get('name', '').replace(f".{self.domain}", "").replace(self.domain, "@") 
                         for r in records if r.get('type') == 'A'}
        
        for name in gate_records:
            if name not in existing_names:
                print(f"  Creating {name}.{self.domain} -> {self.gate_ip}")
                self.create_dns_record('A', name if name != '@' else self.domain, self.gate_ip)
                created += 1
        
        print(f"[OK] Updated {updated} records, created {created} records")
    
    def enable_full_ssl(self) -> None:
        print("[INFO] Enabling Full SSL mode...")
        data = {"value": "full"}
        result = self._cf_api(f"zones/{self.zone_id}/settings/ssl", "PATCH", data)
        if result.get('success'):
            print("[OK] Full SSL enabled")
        else:
            print(f"[WARN] SSL configuration result: {result}")

def main():
    parser = argparse.ArgumentParser(description='Configure Cloudflare for DevPlane Mothership')
    parser.add_argument('--env', default='.env', help='Path to .env file')
    parser.add_argument('--update-dns', action='store_true', help='Update DNS records')
    parser.add_argument('--enable-ssl', action='store_true', help='Enable Full SSL')
    parser.add_argument('--all', action='store_true', help='Run all configuration steps')
    args = parser.parse_args()
    
    load_env_file(args.env)
    
    try:
        cf = CloudflareConfigurator()
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    
    if args.update_dns or args.all:
        cf.update_all_dns_to_gate()
    if args.enable_ssl or args.all:
        cf.enable_full_ssl()
    if not any([args.update_dns, args.enable_ssl, args.all]):
        parser.print_help()

if __name__ == "__main__":
    main()
