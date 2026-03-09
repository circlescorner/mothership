import urllib.request
import urllib.error
import json
import sys
import time

def test_endpoint(path):
    url = f"http://localhost:8000{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            print(f"GET {path} -> {response.status}")
            data = response.read()
            print(f"  Response: {data[:200]}")
    except urllib.error.HTTPError as e:
        print(f"GET {path} -> {e.code} {e.reason}")
        if e.code == 401:
            print("  (Authentication required, expected)")
        else:
            print(f"  Body: {e.read().decode()[:200]}")
    except urllib.error.URLError as e:
        print(f"GET {path} -> Connection error: {e.reason}")
        return False
    return True

if __name__ == "__main__":
    # Wait a bit for server to start
    time.sleep(2)
    endpoints = [
        "/api/config/roles",
        "/api/config/memory",
        "/api/config/optimizer",
        "/api/config/tools",
        "/api/config/mcp_servers",
    ]
    for ep in endpoints:
        test_endpoint(ep)
        time.sleep(0.5)