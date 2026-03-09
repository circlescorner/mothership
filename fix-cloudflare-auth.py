#!/usr/bin/env python3
"""
Cloudflare Auth Diagnostic & Token Setup Script

This script:
1. Tests current Cloudflare credentials from .env
2. Identifies what permissions are missing
3. Provides step-by-step instructions for creating the correct API Token
4. Can optionally update the .env file with the new token

Usage:
    python fix-cloudflare-auth.py           # Test current credentials
    python fix-cloudflare-auth.py --update  # Update .env with new token
"""

import os
import sys
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)

# ===============================================================================
# CONFIGURATION
# ===============================================================================

ENV_FILE = Path(".env")
DOMAIN = os.environ.get("CLOUDFLARE_DOMAIN", "glondor.xyz")

REQUIRED_PERMISSIONS = {
    "zone": [
        ("Zone", "Read", "Required to read zone information and verify access"),
        ("Zone", "Edit", "Required to manage DNS records for the domain"),
    ],
    "dns": [
        ("DNS", "Read", "Required to read existing DNS records"),
        ("DNS", "Edit", "Required to create/update/delete DNS records"),
    ],
    "account": [
        ("Account", "Read", "Required to read account information"),
    ],
    "tunnel": [
        ("Cloudflare Tunnel", "Edit", "Required to create and manage Cloudflare Tunnels"),
        ("Cloudflare Tunnel", "Read", "Required to read tunnel information"),
    ],
}

# ===============================================================================
# DATA CLASSES
# ===============================================================================

@dataclass
class TestResult:
    name: str
    success: bool
    message: str
    details: dict = field(default_factory=dict)

@dataclass
class DiagnosticReport:
    credentials_loaded: bool
    api_key_present: bool
    api_token_present: bool
    email_present: bool
    zone_id_present: bool
    account_id_present: bool
    auth_method: str = "none"  # "token" or "api_key"
    tests: list[TestResult] = field(default_factory=list)
    missing_permissions: list[str] = field(default_factory=list)

# ===============================================================================
# COLOR OUTPUT (with Windows compatibility)
# ===============================================================================

class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"

def supports_color():
    """Check if the terminal supports color output."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def disable_colors():
    """Disable all color output."""
    Colors.HEADER = ""
    Colors.BLUE = ""
    Colors.CYAN = ""
    Colors.GREEN = ""
    Colors.YELLOW = ""
    Colors.RED = ""
    Colors.BOLD = ""
    Colors.UNDERLINE = ""
    Colors.END = ""

# Disable colors on Windows if not supported
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        disable_colors()

def print_header(text: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}  {text}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.END}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}[OK] {text}{Colors.END}")

def print_error(text: str):
    print(f"{Colors.RED}[FAIL] {text}{Colors.END}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.END}")

def print_info(text: str):
    print(f"{Colors.CYAN}[INFO] {text}{Colors.END}")

def print_bold(text: str):
    print(f"{Colors.BOLD}{text}{Colors.END}")

# ===============================================================================
# ENV FILE HANDLING
# ===============================================================================

def load_env_file(filepath: Path = ENV_FILE) -> dict:
    """Load environment variables from .env file."""
    env_vars = {}
    if not filepath.exists():
        return env_vars
    
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                # Remove quotes if present
                value = value.strip().strip("'\"")
                env_vars[key] = value
    return env_vars

def update_env_file(key: str, value: str, filepath: Path = ENV_FILE) -> bool:
    """Update or add a key in the .env file."""
    if not filepath.exists():
        print_error(f".env file not found at {filepath}")
        return False
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check if key already exists
    pattern = rf"^{re.escape(key)}\s*=.*$"
    new_line = f"{key}={value}"
    
    if re.search(pattern, content, re.MULTILINE):
        # Update existing key
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    else:
        # Add new key
        content += f"\n{new_line}\n"
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    return True

# ===============================================================================
# API TESTS
# ===============================================================================

class CloudflareTester:
    def __init__(self, api_key: str = None, email: str = None, zone_id: str = None, account_id: str = None, api_token: str = None):
        self.api_key = api_key
        self.email = email
        self.zone_id = zone_id
        self.account_id = account_id
        self.api_token = api_token
        self.base_url = "https://api.cloudflare.com/client/v4"
        
        # Determine authentication method
        if api_token:
            self.auth_method = "token"
        elif api_key and email:
            self.auth_method = "api_key"
        else:
            self.auth_method = "none"
    
    def _headers(self) -> dict:
        if self.auth_method == "token":
            # Bearer token authentication (new token-based auth)
            return {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
        else:
            # Legacy API key authentication
            return {
                "X-Auth-Email": self.email,
                "X-Auth-Key": self.api_key,
                "Content-Type": "application/json",
            }
    
    async def _make_request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make a request to the Cloudflare API."""
        url = f"{self.base_url}/{endpoint}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.request(method, url, headers=self._headers(), json=data)
                return {
                    "status_code": resp.status_code,
                    "json": resp.json() if resp.status_code != 204 else {},
                    "text": resp.text,
                }
            except httpx.HTTPStatusError as e:
                return {
                    "status_code": e.response.status_code,
                    "json": {},
                    "text": str(e),
                    "error": True,
                }
            except Exception as e:
                return {
                    "status_code": 0,
                    "json": {},
                    "text": str(e),
                    "error": True,
                }
    
    async def test_zone_read(self) -> TestResult:
        """Test Zone:Read permission."""
        result = await self._make_request("GET", f"zones/{self.zone_id}")
        
        if result.get("status_code") == 200:
            zone_data = result.get("json", {}).get("result", {})
            return TestResult(
                name="Zone:Read",
                success=True,
                message=f"Can read zone: {zone_data.get('name', 'Unknown')}",
                details={"zone": zone_data}
            )
        elif result.get("status_code") == 403:
            return TestResult(
                name="Zone:Read",
                success=False,
                message="Permission denied - Zone:Read access required",
                details={"code": result.get("status_code")}
            )
        else:
            return TestResult(
                name="Zone:Read",
                success=False,
                message=f"Failed with status {result.get('status_code')}: {result.get('text', '')[:100]}",
                details={"code": result.get("status_code")}
            )
    
    async def test_dns_list(self) -> TestResult:
        """Test DNS:Read permission."""
        result = await self._make_request("GET", f"zones/{self.zone_id}/dns_records?per_page=1")
        
        if result.get("status_code") == 200:
            records = result.get("json", {}).get("result", [])
            return TestResult(
                name="DNS:Read",
                success=True,
                message=f"Can list DNS records ({len(records)} sample record(s) retrieved)",
            )
        elif result.get("status_code") == 403:
            return TestResult(
                name="DNS:Read",
                success=False,
                message="Permission denied - DNS:Read access required",
            )
        else:
            return TestResult(
                name="DNS:Read",
                success=False,
                message=f"Failed with status {result.get('status_code')}",
            )
    
    async def test_dns_write(self) -> TestResult:
        """Test DNS:Edit permission by creating a test record."""
        # First try to create a test record
        test_record = {
            "type": "TXT",
            "name": f"_auth-test.{DOMAIN}",
            "content": f"auth-test-{os.urandom(4).hex()}",
            "ttl": 60,
        }
        
        result = await self._make_request(
            "POST", 
            f"zones/{self.zone_id}/dns_records", 
            test_record
        )
        
        if result.get("status_code") in [200, 201]:
            # Clean up the test record
            record_id = result.get("json", {}).get("result", {}).get("id")
            if record_id:
                await self._make_request("DELETE", f"zones/{self.zone_id}/dns_records/{record_id}")
            
            return TestResult(
                name="DNS:Edit",
                success=True,
                message="Can create and delete DNS records",
            )
        elif result.get("status_code") == 403:
            return TestResult(
                name="DNS:Edit",
                success=False,
                message="Permission denied - DNS:Edit access required",
            )
        else:
            return TestResult(
                name="DNS:Edit",
                success=False,
                message=f"Failed with status {result.get('status_code')}: {result.get('text', '')[:100]}",
            )
    
    async def test_account_read(self) -> TestResult:
        """Test Account:Read permission."""
        result = await self._make_request("GET", f"accounts/{self.account_id}")
        
        if result.get("status_code") == 200:
            account_data = result.get("json", {}).get("result", {})
            return TestResult(
                name="Account:Read",
                success=True,
                message=f"Can read account: {account_data.get('name', 'Unknown')}",
            )
        elif result.get("status_code") == 403:
            return TestResult(
                name="Account:Read",
                success=False,
                message="Permission denied - Account:Read access required",
            )
        else:
            return TestResult(
                name="Account:Read",
                success=False,
                message=f"Failed with status {result.get('status_code')}",
            )
    
    async def test_tunnel_read(self) -> TestResult:
        """Test Cloudflare Tunnel:Read permission."""
        result = await self._make_request(
            "GET", 
            f"accounts/{self.account_id}/tunnels?per_page=1"
        )
        
        if result.get("status_code") == 200:
            return TestResult(
                name="Cloudflare Tunnel:Read",
                success=True,
                message="Can list Cloudflare Tunnels",
            )
        elif result.get("status_code") == 403:
            return TestResult(
                name="Cloudflare Tunnel:Read",
                success=False,
                message="Permission denied - Cloudflare Tunnel:Read access required",
            )
        else:
            return TestResult(
                name="Cloudflare Tunnel:Read",
                success=False,
                message=f"Failed with status {result.get('status_code')}",
            )
    
    async def test_tunnel_write(self) -> TestResult:
        """Test Cloudflare Tunnel:Edit permission."""
        import secrets
        import base64
        
        # Generate tunnel secret as base64 (Cloudflare API requirement)
        tunnel_secret_bytes = secrets.token_bytes(32)
        tunnel_secret = base64.b64encode(tunnel_secret_bytes).decode('utf-8')
        
        # Use the correct API endpoint and data format
        test_tunnel = {
            "name": f"_auth-test-{os.urandom(4).hex()}",
            "tunnel_secret": tunnel_secret,
        }
        
        result = await self._make_request(
            "POST",
            f"accounts/{self.account_id}/cfd_tunnel",
            test_tunnel
        )
        
        # Clean up if created
        if result.get("status_code") in [200, 201]:
            tunnel_id = result.get("json", {}).get("result", {}).get("id")
            if tunnel_id:
                await self._make_request(
                    "DELETE",
                    f"accounts/{self.account_id}/cfd_tunnel/{tunnel_id}"
                )
            return TestResult(
                name="Cloudflare Tunnel:Edit",
                success=True,
                message="Can create and delete Cloudflare Tunnels",
            )
        
        # 400 might mean we have permission but tunnel name exists or other validation error
        # 403 means definitely no permission
        if result.get("status_code") == 403:
            return TestResult(
                name="Cloudflare Tunnel:Edit",
                success=False,
                message="Permission denied - Cloudflare Tunnel:Edit access required",
            )
        elif result.get("status_code") == 400:
            # Likely have permission but there was a validation error
            error_msg = result.get("json", {}).get("errors", [{}])[0].get("message", "")
            if "exists" in error_msg.lower() or "validation" in error_msg.lower():
                return TestResult(
                    name="Cloudflare Tunnel:Edit",
                    success=True,
                    message="Likely has permission (got validation error, not permission error)",
                )
            return TestResult(
                name="Cloudflare Tunnel:Edit",
                success=False,
                message=f"Request failed: {error_msg}",
            )
        else:
            return TestResult(
                name="Cloudflare Tunnel:Edit",
                success=False,
                message=f"Failed with status {result.get('status_code')}",
            )
    
    async def run_all_tests(self) -> list[TestResult]:
        """Run all diagnostic tests."""
        tests = [
            self.test_zone_read(),
            self.test_dns_list(),
            self.test_dns_write(),
            self.test_account_read(),
            self.test_tunnel_read(),
            self.test_tunnel_write(),
        ]
        return await asyncio.gather(*tests)

# ===============================================================================
# INSTRUCTIONS
# ===============================================================================

def print_token_creation_instructions():
    """Print step-by-step instructions for creating the API token."""
    print_header("EXACT PERMISSIONS TO CONFIGURE")
    
    print_bold("Go to: https://dash.cloudflare.com/profile/api-tokens")
    print()
    print_bold("Click: 'Create Token' -> 'Get started' (Custom token)")
    print()
    
    print(f"{Colors.BOLD}Token Name:{Colors.END} DevPlane Management")
    print()
    
    print(f"{Colors.BOLD}Configure these EXACT permissions:{Colors.END}\n")
    
    print(f"{Colors.YELLOW}1. Zone Permissions (for {DOMAIN}):{Colors.END}")
    print(f"   {Colors.GREEN}Zone - Read{Colors.END}  (Required to read zone info)")
    print(f"   {Colors.GREEN}Zone - Edit{Colors.END}  (Required for DNS management)")
    print()
    
    print(f"{Colors.YELLOW}2. DNS Permissions:{Colors.END}")
    print(f"   {Colors.GREEN}DNS - Read{Colors.END}  (Required to read DNS records)")
    print(f"   {Colors.GREEN}DNS - Edit{Colors.END}  (Required to modify DNS records)")
    print()
    
    print(f"{Colors.YELLOW}3. Account Permissions:{Colors.END}")
    print(f"   {Colors.GREEN}Account - Read{Colors.END}  (Required to read account info)")
    print()
    
    print(f"{Colors.YELLOW}4. Cloudflare Tunnel Permissions:{Colors.END}")
    print(f"   {Colors.GREEN}Cloudflare Tunnel - Read{Colors.END}  (Required to read tunnels)")
    print(f"   {Colors.GREEN}Cloudflare Tunnel - Edit{Colors.END}  (Required to manage tunnels)")
    print()
    
    print(f"{Colors.YELLOW}5. Zone Resources - Include:{Colors.END}")
    print(f"   {Colors.GREEN}Include - Specific zone - {DOMAIN}{Colors.END}")
    print()
    
    print(f"{Colors.YELLOW}6. Account Resources - Include:{Colors.END}")
    print(f"   {Colors.GREEN}Include - All accounts{Colors.END} (or select your specific account)")
    print()
    
    print(f"{Colors.BOLD}Click 'Continue to summary' -> 'Create Token'{Colors.END}")
    print()
    print_warning("IMPORTANT: Copy the token immediately - you won't see it again!")
    print()
    
    print_header("UPDATING YOUR .ENV FILE")
    print("After creating the token, run:")
    print()
    print(f"   {Colors.CYAN}python fix-cloudflare-auth.py --update{Colors.END}")
    print()
    print("Or manually edit .env and replace:")
    print(f"   {Colors.YELLOW}CLOUDFLARE_API_KEY=your-old-key{Colors.END}")
    print("With:")
    print(f"   {Colors.GREEN}CLOUDFLARE_API_TOKEN=your-new-token{Colors.END}")
    print()
    print_info("Note: The new token-based auth uses CLOUDFLARE_API_TOKEN instead of CLOUDFLARE_API_KEY")
    print()

def print_summary_report(report: DiagnosticReport):
    """Print a summary of the diagnostic report."""
    print_header("DIAGNOSTIC SUMMARY")
    
    # Credentials check
    print_bold("Credentials Status:")
    
    # Show authentication method
    if report.auth_method == "token":
        print_info("Using: CLOUDFLARE_API_TOKEN (Bearer Token Authentication)")
    elif report.auth_method == "api_key":
        print_info("Using: CLOUDFLARE_API_KEY (Legacy Global API Key)")
    else:
        print_warning("No valid authentication method configured")
    
    print()
    
    if report.api_token_present:
        print_success("CLOUDFLARE_API_TOKEN is set")
    else:
        print_warning("CLOUDFLARE_API_TOKEN is not set")
    
    if report.api_key_present:
        print_success("CLOUDFLARE_API_KEY is set")
    else:
        print_warning("CLOUDFLARE_API_KEY is not set")
    
    if report.email_present:
        print_success("CLOUDFLARE_EMAIL is set")
    else:
        print_warning("CLOUDFLARE_EMAIL is not set (not required for token auth)")
    
    if report.zone_id_present:
        print_success("CLOUDFLARE_ZONE_ID is set")
    else:
        print_error("CLOUDFLARE_ZONE_ID is missing")
    
    if report.account_id_present:
        print_success("CLOUDFLARE_ACCOUNT_ID is set")
    else:
        print_error("CLOUDFLARE_ACCOUNT_ID is missing")
    
    print()
    
    # Test results
    print_bold("Permission Tests:")
    passed = 0
    failed = 0
    
    for test in report.tests:
        if test.success:
            print_success(f"{test.name}: {test.message}")
            passed += 1
        else:
            print_error(f"{test.name}: {test.message}")
            failed += 1
    
    print()
    print_bold(f"Results: {passed} passed, {failed} failed")
    
    if failed > 0:
        print()
        if report.auth_method == "token":
            print_warning("Your API Token is missing required permissions!")
            print()
            print("Edit your API Token at: https://dash.cloudflare.com/profile/api-tokens")
            print("Make sure it has the exact permissions listed below.")
        else:
            print_warning("Your current API Key is missing required permissions!")
            print()
            print("The Global API Key often has limited permissions.")
            print("Create a dedicated API Token with the exact permissions listed above.")

# ===============================================================================
# MAIN
# ===============================================================================

import asyncio

def prompt_for_token() -> str:
    """Prompt the user for the new API token."""
    print_header("UPDATE .ENV WITH NEW TOKEN")
    print("Enter your new Cloudflare API Token (from https://dash.cloudflare.com/profile/api-tokens)")
    print()
    print_warning("Note: The token will be hidden as you type for security")
    print()
    
    try:
        import getpass
        token = getpass.getpass("API Token: ").strip()
        return token
    except:
        token = input("API Token (visible): ").strip()
        return token

def validate_token_format(token: str) -> bool:
    """Basic validation of the token format."""
    if not token:
        print_error("Token cannot be empty")
        return False
    
    # Cloudflare API tokens are typically long base64-like strings
    if len(token) < 20:
        print_warning("Token seems unusually short. Please verify it's the full token.")
        return False
    
    return True

async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Cloudflare Auth Diagnostic & Token Setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fix-cloudflare-auth.py           # Test current credentials
  python fix-cloudflare-auth.py --update  # Update .env with new token
        """
    )
    parser.add_argument(
        "--update", "-u",
        action="store_true",
        help="Update the .env file with a new API token"
    )
    parser.add_argument(
        "--test-token",
        metavar="TOKEN",
        help="Test a specific token before saving it"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output"
    )
    
    args = parser.parse_args()
    
    if args.no_color:
        disable_colors()
    
    # Load current environment
    env_vars = load_env_file()
    
    if args.update:
        # Update mode
        token = args.test_token or prompt_for_token()
        
        if not validate_token_format(token):
            sys.exit(1)
        
        print()
        print_info("Updating .env file...")
        
        # For token-based auth, we add CLOUDFLARE_API_TOKEN
        # The CloudflareManager will need to be updated to support token auth
        success = update_env_file("CLOUDFLARE_API_TOKEN", token)
        
        if success:
            print_success("Successfully added CLOUDFLARE_API_TOKEN to .env")
            print()
            print_info("Note: You may need to update devplane/infra/cloudflare.py")
            print("      to use token-based authentication (Authorization: Bearer header)")
            print()
            print("Current .env uses Global API Key auth (CLOUDFLARE_API_KEY)")
            print("New token is saved as CLOUDFLARE_API_TOKEN")
        else:
            print_error("Failed to update .env file")
            sys.exit(1)
        
        return
    
    # Diagnostic mode
    print_header("Cloudflare Auth Diagnostic Tool")
    
    # Check for API token first (new token-based auth)
    api_token = env_vars.get("CLOUDFLARE_API_TOKEN", "")
    api_key = env_vars.get("CLOUDFLARE_API_KEY", "")
    email = env_vars.get("CLOUDFLARE_EMAIL", "")
    zone_id = env_vars.get("CLOUDFLARE_ZONE_ID", "")
    account_id = env_vars.get("CLOUDFLARE_ACCOUNT_ID", "")
    
    # Determine which authentication method to use
    if api_token:
        auth_method = "token"
        print_info("Found CLOUDFLARE_API_TOKEN - using Bearer Token authentication")
    elif api_key and email:
        auth_method = "api_key"
        print_info("Found CLOUDFLARE_API_KEY - using Legacy API Key authentication")
    else:
        auth_method = "none"
    
    report = DiagnosticReport(
        credentials_loaded=bool(env_vars),
        api_key_present=bool(api_key),
        api_token_present=bool(api_token),
        email_present=bool(email),
        zone_id_present=bool(zone_id),
        account_id_present=bool(account_id),
        auth_method=auth_method,
    )
    
    # Validate required credentials based on auth method
    if auth_method == "token":
        # Token auth only needs zone_id and account_id
        if not all([zone_id, account_id]):
            print_error("Missing required credentials for token authentication")
            print()
            print("Required variables:")
            print("  - CLOUDFLARE_API_TOKEN")
            print("  - CLOUDFLARE_ZONE_ID")
            print("  - CLOUDFLARE_ACCOUNT_ID")
            print()
            print_info("Please check your .env file and ensure all values are set.")
            sys.exit(1)
    elif auth_method == "api_key":
        # API key auth needs all credentials
        if not all([api_key, email, zone_id, account_id]):
            print_error("Missing required credentials for API key authentication")
            print()
            print("Required variables:")
            print("  - CLOUDFLARE_API_KEY")
            print("  - CLOUDFLARE_EMAIL")
            print("  - CLOUDFLARE_ZONE_ID")
            print("  - CLOUDFLARE_ACCOUNT_ID")
            print()
            print_info("Please check your .env file and ensure all values are set.")
            sys.exit(1)
    else:
        print_error("No valid authentication method found")
        print()
        print("Please set either:")
        print("  - CLOUDFLARE_API_TOKEN (recommended - token-based auth)")
        print("  - CLOUDFLARE_API_KEY (legacy - Global API Key)")
        print()
        print_info("For token-based auth, you also need:")
        print("  - CLOUDFLARE_ZONE_ID")
        print("  - CLOUDFLARE_ACCOUNT_ID")
        sys.exit(1)
    
    print_info("Testing credentials...")
    print(f"   Zone ID: {zone_id[:8]}...{zone_id[-8:]}")
    print(f"   Account ID: {account_id[:8]}...{account_id[-8:]}")
    if auth_method == "api_key":
        print(f"   Email: {email}")
    print(f"   Auth Method: {auth_method}")
    print()
    
    # Create tester with appropriate credentials
    if auth_method == "token":
        tester = CloudflareTester(zone_id=zone_id, account_id=account_id, api_token=api_token)
    else:
        tester = CloudflareTester(api_key=api_key, email=email, zone_id=zone_id, account_id=account_id)
    
    report.tests = await tester.run_all_tests()
    
    print_summary_report(report)
    
    # Check if any tests failed
    if any(not t.success for t in report.tests):
        print()
        print_token_creation_instructions()
        sys.exit(1)
    else:
        print()
        print_success("All permission tests passed! Your credentials are working correctly.")
        print()

if __name__ == "__main__":
    asyncio.run(main())
