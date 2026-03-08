"""Setup Extensions — Auto-configure Kilo Code, OpenCoder & Antigravity Fallback.

Run this script to automatically wire up all AI coding extensions using
the API keys from your .env file. This is also called by the Lockhost
wizard's "Setup Extensions" button.

Usage:
    python setup_extensions.py
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ────────────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).parent
HOME_DIR = Path.home()
VSCODE_DIR = PROJECT_DIR / ".vscode"
GEMINI_DIR = HOME_DIR / ".gemini"
ANTIGRAVITY_DIR = GEMINI_DIR / "antigravity"

# ─── API Keys ─────────────────────────────────────────────────────────────────

KEYS = {
    "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
    "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
    "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
    "TOGETHERAI_API_KEY": os.getenv("TOGETHERAI_API_KEY", ""),
    "FIREWORKS_AI_API_KEY": os.getenv("FIREWORKS_AI_API_KEY", ""),
    "CEREBRAS_API_KEY": os.getenv("CEREBRAS_API_KEY", ""),
}


def log(msg: str):
    print(f"  ✦ {msg}")


def print_security_warning():
    """Print security warning about API keys being written to disk."""
    print("\n" + "="*70)
    print("  🔒 SECURITY WARNING")
    print("="*70)
    print("  This script writes API keys to the following locations:")
    print("    - .vscode/settings.json (for Kilo Code configuration)")
    print("    - ~/.gemini/antigravity/ (for Antigravity configuration)")
    print("")
    print("  These files contain UNENCRYPTED API keys.")
    print("  To protect your keys:")
    print("    1. Ensure .vscode/settings.json is in .gitignore")
    print("    2. Restrict file permissions: chmod 600 .vscode/settings.json")
    print("    3. Never commit these files to version control")
    print("="*70 + "\n")


def setup_kilo_code():
    """Configure Kilo Code extension with OpenRouter multi-model access."""
    log("Configuring Kilo Code in .vscode/settings.json...")

    VSCODE_DIR.mkdir(exist_ok=True)

    # Read existing settings if present
    settings_path = VSCODE_DIR / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            # Strip comments for JSON parsing
            raw = settings_path.read_text(encoding="utf-8")
            lines = [l for l in raw.splitlines() if not l.strip().startswith("//")]
            settings = json.loads("\n".join(lines))
        except (json.JSONDecodeError, Exception):
            settings = {}

    # Kilo Code config
    settings.update({
        "kilocode.apiProvider": "openrouter",
        "kilocode.openRouterApiKey": KEYS["OPENROUTER_API_KEY"],
        "kilocode.openRouterModelId": "anthropic/claude-sonnet-4",
        "kilocode.modeApiConfigs": {
            "code": {
                "apiProvider": "openrouter",
                "openRouterModelId": "anthropic/claude-sonnet-4"
            },
            "architect": {
                "apiProvider": "openrouter",
                "openRouterModelId": "anthropic/claude-sonnet-4"
            },
            "ask": {
                "apiProvider": "openrouter",
                "openRouterModelId": "deepseek/deepseek-chat"
            },
            "debug": {
                "apiProvider": "openrouter",
                "openRouterModelId": "qwen/qwen3-coder-next"
            },
            "review": {
                "apiProvider": "openrouter",
                "openRouterModelId": "google/gemini-2.0-flash-001"
            }
        },
        "kilocode.enablePromptCompression": True,
        "kilocode.autoApproveReadonly": True,
    })

    settings_path.write_text(json.dumps(settings, indent=4), encoding="utf-8")
    log(f"  → Kilo Code configured with OpenRouter")


def setup_continue_dev():
    """Configure Continue.dev with OpenCoder + 5 provider models."""
    log("Configuring Continue.dev with OpenCoder-8B...")

    config = {
        "models": [
            {
                "title": "OpenCoder-8B (OpenRouter)",
                "provider": "openrouter",
                "model": "opencoder/opencoder-8b",
                "apiKey": KEYS["OPENROUTER_API_KEY"],
                "contextLength": 8192
            },
            {
                "title": "Qwen 2.5 Coder 32B (TogetherAI)",
                "provider": "together",
                "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
                "apiKey": KEYS["TOGETHERAI_API_KEY"],
                "contextLength": 32768
            },
            {
                "title": "DeepSeek V3",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "apiKey": KEYS["DEEPSEEK_API_KEY"],
                "contextLength": 64000
            },
            {
                "title": "Gemini 2.0 Flash (Free)",
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "apiKey": KEYS["GEMINI_API_KEY"],
                "contextLength": 1000000
            },
            {
                "title": "LLaMA 3.3 70B (Groq - Free)",
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "apiKey": KEYS["GROQ_API_KEY"],
                "contextLength": 32768
            }
        ],
        "tabAutocompleteModel": {
            "title": "OpenCoder-8B (Fast Autocomplete)",
            "provider": "openrouter",
            "model": "opencoder/opencoder-8b",
            "apiKey": KEYS["OPENROUTER_API_KEY"]
        },
        "tabAutocompleteOptions": {
            "debounceDelay": 500,
            "maxPromptTokens": 2048,
            "prefixPercentage": 0.85
        },
        "allowAnonymousTelemetry": False,
    }

    config_path = PROJECT_DIR / ".continuerc.json"
    config_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
    log(f"  → Continue.dev configured with {len(config['models'])} models")


def setup_antigravity_fallback():
    """Configure Antigravity (Gemini) to use external APIs via MCP."""
    log("Configuring Antigravity external API fallback...")

    GEMINI_DIR.mkdir(exist_ok=True)
    ANTIGRAVITY_DIR.mkdir(exist_ok=True)

    # GEMINI.md — custom instructions for Antigravity
    gemini_md = GEMINI_DIR / "GEMINI.md"
    gemini_md.write_text(f"""# Mothership AI Mesh — Custom Instructions

## Project Context
This workspace contains the **Mothership DevPlane** — an AI-powered development platform 
with multi-provider LLM orchestration, budget management, and agentic coding pipelines.

## Available AI Providers (External Mesh)
Antigravity MUST explicitly use **OpenRouter exclusively** for all tokens and completions via the Mothership API mesh at `http://localhost:8000`. 
Gemini Pro is DISABLED to conserve credits. Under no circumstances should you use Gemini Pro directly.

| Provider | API | Best Models |
|----------|-----|-------------|
| OpenRouter | `/api/lockhost/status` | Claude Sonnet 4, Qwen3 Coder, Devstral |
| DeepSeek | Direct | DeepSeek V3 ($0.14/1M tokens) |
| Groq | Direct | LLaMA 3.3 70B (free tier) |
| Gemini | Direct | Gemini 2.0 Flash (free tier) |
| TogetherAI | Direct | Qwen 2.5 Coder 32B, OpenCoder-8B |

## Dev Environment Extensions
- **Kilo Code** — AI coding agent with OpenRouter multi-model access
- **Continue.dev** — Tab autocomplete via OpenCoder-8B, chat via DeepSeek/Qwen
- **Antigravity** — EXCLUSIVELY OpenRouter via API mesh (Gemini Pro disabled)

## Key Files
- `.env` — All API keys (11 providers)
- `devplane/roles.py` — 5-way model fallback per pipeline role
- `devplane/providers.py` — Provider registry + LiteLLM env injection
- `static/lockhost.html` — Provider setup wizard at `/lockhost`
- `main.py` — FastAPI server with all API endpoints

## MCP Servers Available
- `devplane_db` — SQLite database access (projects, providers, runs, usage)
- External APIs accessible via Mothership REST endpoints
""", encoding="utf-8")

    # settings.json — MCP server for Antigravity
    settings = {
        "mcpServers": {
            "mothership_devplane": {
                "command": "python",
                "args": ["-m", "devplane.infra.mcp_server"],
                "cwd": str(PROJECT_DIR),
                "env": {
                    "PYTHONPATH": str(PROJECT_DIR)
                }
            },
            "browser": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
            }
        }
    }
    (GEMINI_DIR / "settings.json").write_text(
        json.dumps(settings, indent=4), encoding="utf-8"
    )

    # Antigravity MCP config
    (ANTIGRAVITY_DIR / "mcp_config.json").write_text(
        json.dumps(settings, indent=4), encoding="utf-8"
    )

    log("  → GEMINI.md written with fallback instructions")
    log("  → MCP config pointing to Mothership DevPlane")


def setup_extensions_json():
    """Write VS Code extension recommendations."""
    VSCODE_DIR.mkdir(exist_ok=True)
    ext_path = VSCODE_DIR / "extensions.json"
    ext_config = {
        "recommendations": [
            "kilocode.kilo-code",
            "continue.continue",
            "github.copilot"
        ]
    }
    ext_path.write_text(json.dumps(ext_config, indent=4), encoding="utf-8")
    log("  → Extension recommendations written")


def install_extensions():
    """Install VS Code extensions if `code` CLI is available."""
    log("Checking for VS Code CLI...")

    code_cmd = shutil.which("code")
    if not code_cmd:
        log("  [WARN] VS Code CLI not found. Install extensions manually:")
        log("    code --install-extension kilocode.kilo-code")
        log("    code --install-extension continue.continue")
        return

    extensions = [
        "kilocode.kilo-code",
        "continue.continue",
    ]

    for ext in extensions:
        log(f"  Installing {ext}...")
        try:
            subprocess.run(
                [code_cmd, "--install-extension", ext, "--force"],
                capture_output=True, text=True, timeout=60
            )
        except Exception as e:
            log(f"  [WARN] Failed to install {ext}: {e}")

    log("  → Extensions installed")


def print_summary():
    """Print setup summary."""
    print("\n" + "=" * 60)
    print("  🔒 Lockhost Extension Setup Complete")
    print("=" * 60)

    providers = []
    for name, key in KEYS.items():
        status = f"✅ {key[:8]}..." if key else "❌ Not set"
        providers.append(f"    {name:<25} {status}")

    print("\n  API Keys loaded:")
    print("\n".join(providers))

    print(f"\n  Configs written:")
    print(f"    .vscode/settings.json    — Kilo Code (5 modes)")
    print(f"    .continuerc.json         — Continue.dev (5 models + OpenCoder)")
    print(f"    ~/.gemini/GEMINI.md      — Antigravity fallback instructions")
    print(f"    ~/.gemini/settings.json  — Antigravity MCP config")

    print(f"\n  Extensions:")
    print(f"    Kilo Code                — OpenRouter multi-model agent")
    print(f"    Continue.dev             — OpenCoder-8B tab autocomplete")

    print(f"\n  How to verify:")
    print(f"    1. Restart VS Code")
    print(f"    2. Open Kilo Code panel → verify OpenRouter provider")
    print(f"    3. Start Mothership: python main.py")
    print(f"    4. Open http://localhost:8000/lockhost")
    print("=" * 60 + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_setup():
    """Run the full extension setup."""
    print("\n🔒 Lockhost Extension Setup")
    print("  Configuring Kilo Code + OpenCoder + Antigravity Fallback\n")
    
    # Print security warning about API keys
    print_security_warning()

    setup_kilo_code()
    setup_continue_dev()
    setup_antigravity_fallback()
    setup_extensions_json()
    install_extensions()
    print_summary()

    return {
        "status": "success",
        "kilo_code": True,
        "continue_dev": True,
        "antigravity_fallback": True,
        "providers_configured": sum(1 for v in KEYS.values() if v),
    }


if __name__ == "__main__":
    result = run_setup()
    sys.exit(0 if result["status"] == "success" else 1)
