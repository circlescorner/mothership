import asyncio
import logging
from typing import Optional
from dotenv import load_dotenv

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

# Ensure environment variables are loaded from the start
load_dotenv()

# Set up logging for stdio MCP (use stderr so we don't pollute stdout which MCP uses for communication)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Default wraps sys.stderr
)
logger = logging.getLogger("mcp_server_devplane")

app = Server("devplane_mcp")

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """Expose DevPlane mesh roles and routing as MCP tools."""
    return [
        types.Tool(
            name="ask_kilo_code",
            description="Send a complex coding or heavy lifting task to the Mothership 'worker' role (typically powered by DeepSeek V3 or Qwen 2.5 Coder 32B)",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The coding task or question"},
                    "context": {"type": "string", "description": "Additional context or code snippets (optional)"}
                },
                "required": ["prompt"]
            }
        ),
        types.Tool(
            name="ask_continue_dev",
            description="Send a rapid autocomplete, refactor, or debugging question to the Mothership 'fast' role (typically powered by LLaMA 3.3 or Cerebras)",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The debugging issue or fast autocomplete prompt"},
                    "context": {"type": "string", "description": "Surrounding code or context (optional)"}
                },
                "required": ["prompt"]
            }
        ),
        types.Tool(
            name="ask_antigravity",
            description="Consult the Mothership 'architect' role (typically powered by Claude Sonnet 4 or DeepSeek V3) for architectural decisions, system design, or review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The architectural question or design request"},
                    "context": {"type": "string", "description": "Project context or existing architectural decisions (optional)"}
                },
                "required": ["prompt"]
            }
        ),
        types.Tool(
            name="ask_any_role",
            description="Dynamically consult any available DevPlane role. Roles include: planner, executor, reviewer, judge, personal, architect, worker, critic, fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "The specific DevPlane role (e.g., 'planner', 'critic', 'judge')"},
                    "prompt": {"type": "string", "description": "The task or question for the specified role"},
                    "context": {"type": "string", "description": "Context or existing information for the specified role (optional)"}
                },
                "required": ["role", "prompt"]
            }
        ),
        types.Tool(
            name="run_devplane_routing",
            description="Invoke the entire DevPlane routing system (Slackbot Tournament, God-Mode Mesh, or LangChain Agent). Use this to delegate complex generation or pipelines.",
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "description": "The DevPlane execution mode: 'tournament', 'mesh', or 'agent'."},
                    "prompt": {"type": "string", "description": "The full task prompt to send into the arena/mesh/agent"}
                },
                "required": ["mode", "prompt"]
            }
        )
    ]

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Handle invocations of the DevPlane MCP tools."""
    from devplane.roles import call_with_fallback
    from devplane.chain.engine import run_tournament
    from devplane.db import init_db, get_default_project_id
    from devplane.providers import load_all_keys_to_env
    from devplane.roles import load_from_db
    
    if arguments is None:
        raise ValueError("Missing arguments")
        
    prompt = arguments.get("prompt")
    context = arguments.get("context", "")
    
    try:
        # Initialize necessary Mothership systems
        logger.info(f"Initializing DevPlane context for tool: {name}")
        await load_all_keys_to_env()
        await init_db()
        await load_from_db()
        
        # Determine the project
        project_id = await get_default_project_id()

        if name == "run_devplane_routing":
            mode = arguments.get("mode", "tournament")
            logger.info(f"Invoking {mode} routing via DevPlane...")
            
            result = await run_tournament(prompt, project_id=project_id, mode=mode)
            
            status = result.get("status", "error")
            if status == "success":
                winner = result.get("winning_tier", "Unknown Tier")
                cost = result.get("total_cost", 0.0)
                final_output = result.get("final_output", "")
                
                final_response = (
                    f"🚀 [DevPlane Routing Proxy | Mode: {mode} | Winner: {winner} | Cost: ${cost:.5f}]\n\n"
                    f"{final_output}"
                )
                logger.info(f"Successfully returned routing response for {mode}.")
                return [types.TextContent(type="text", text=final_response)]
            else:
                error_output = result.get("final_output", "Unknown error in routing.")
                return [types.TextContent(type="text", text=f"DevPlane Routing Error: {error_output}")]

        else:
            # Map MCP tool to DevPlane role
            role_map = {
                "ask_kilo_code": "worker",
                "ask_continue_dev": "fast",
                "ask_antigravity": "architect"
            }
            
            if name == "ask_any_role":
                role = arguments.get("role", "worker").lower()
            else:
                if name not in role_map:
                    raise ValueError(f"Unknown tool: {name}")
                role = role_map[name]
                
            system_prompt = (
                f"You are the {role} AI agent within the Mothership DevPlane mesh. "
                "You are being invoked via the Model Context Protocol (MCP) by a peer AI extension "
                "(like Antigravity, Kilo Code, or Continue.dev). Help them accomplish their task by "
                "providing specialized expertise."
            )
            
            user_content = prompt
            if context:
                user_content = f"[Context]\n{context}\n\n[Task]\n{prompt}"
            
            logger.info(f"Invoking {role} role via DevPlane fallbacks...")
            result = await call_with_fallback(
                role=role,
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=0.2,
                project_id=project_id
            )
            
            response_text = result.get("content", f"Error: No content returned. Result: {result}")
            model_used = result.get("model", "unknown")
            cost = result.get("cost", 0.0)
            
            # Format response to highlight it came through DevPlane's proxy
            final_response = (
                f"🚀 [DevPlane Proxy via {model_used} | Role: {role} | Cost: ${cost:.5f}]\n\n"
                f"{response_text}"
            )
            
            logger.info(f"Successfully returned response from {model_used} for {role}.")
            return [types.TextContent(type="text", text=final_response)]
            
    except Exception as e:
        logger.error(f"Error calling {name}: {e}")
        return [types.TextContent(type="text", text=f"DevPlane MCP Error: {str(e)}")]

async def main():
    """Run the MCP server over stdio."""
    logger.info("Starting DevPlane MCP Server on stdio...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
