"""Model Context Protocol (MCP) Manager.

Dynamically loads and manages connected MCP tools for the LangGraph agent.
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger("devplane.infra.mcp")

class MCPManager:
    """Manages connections to trusted self-hosted MCP servers."""
    
    def __init__(self):
        # Dictionary of active MCP client sessions
        self.clients = {}
        # Stores fetched tool schemas
        self.available_tools: List[Dict[str, Any]] = []
        
    async def connect_local_server(self, name: str, command: str, args: List[str]):
        """Connects to a local MCP server via stdio."""
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp.client.session import ClientSession
        
        try:
            params = StdioServerParameters(command=command, args=args)
            client_ctx = stdio_client(params)
            
            try:
                # Enter the context to get transport
                read_stream, write_stream = await client_ctx.__aenter__()
            except Exception as inner_e:
                logger.error(f"Failed to start MCP Server process {name}: {inner_e}")
                return False
                
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            await session.initialize()
            
            self.clients[name] = {
                "session": session,
                "context": client_ctx,
                "command": command
            }
            
            # Fetch available tools
            tools_response = await session.list_tools()
            for tool in tools_response.tools:
                # Store tool info along with the server name that provides it
                self.available_tools.append({
                    "server": name,
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                })
                
            logger.info(f"Connected to MCP Server: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP Server {name}: {e}")
            return False

    def get_agent_tools(self) -> List:
        """Translates connected MCP tools into LangChain @tool objects."""
        from langchain_core.tools import StructuredTool
        import json
        
        langchain_tools = []
        
        for tool_info in self.available_tools:
            # We must bind the session in the closure carefully
            server_name = tool_info["server"]
            tool_name = tool_info["name"]
            
            # Create a dynamic function that calls the MCP session
            async def _mcp_tool_func(*args, **kwargs) -> str:
                # Find active session
                client_info = self.clients.get(server_name)
                if not client_info:
                    return f"Error: MCP Server {server_name} is no longer connected."
                
                try:
                    result = await client_info["session"].call_tool(tool_name, arguments=kwargs)
                    return json.dumps([c.model_dump() for c in result.content])
                except Exception as e:
                    return f"MCP Tool execution error: {str(e)}"
            
            # Create a structured tool for LangChain
            lc_tool = StructuredTool.from_function(
                coroutine=_mcp_tool_func,
                name=f"{server_name}_{tool_name}",
                description=tool_info["description"] or f"Executes {tool_name} on {server_name}",
                # Input schema mapping could be tricky depending on the MCP schema, 
                # but LangChain can usually infer from standard JSON Schema kwargs if we build a pydantic model.
                # For simplicity in this demo, we'll let Langchain try to infer or we can wrap it.
            )
            langchain_tools.append(lc_tool)
            
        return langchain_tools
        
    async def cleanup(self):
        """Close all MCP sessions."""
        for name, client_info in self.clients.items():
            try:
                await client_info["session"].__aexit__(None, None, None)
                await client_info["context"].__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error cleaning up MCP {name}: {e}")
        self.clients.clear()
        self.available_tools.clear()

# Global Singleton
_mcp_manager = MCPManager()

def get_mcp_manager() -> MCPManager:
    return _mcp_manager
