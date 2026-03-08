import asyncio
import os
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Mock Semantic Kernel for now to avoid heavy dependencies if not installed
class MockSemanticKernel:
    def __init__(self):
        self.plugins = {}

    def import_plugin(self, name: str, functions: List[str]):
        self.plugins[name] = functions
        return f"Plugin '{name}' imported with functions: {', '.join(functions)}."

    def invoke_function(self, plugin_name: str, function_name: str, arguments: Dict[str, Any]) -> str:
        if plugin_name not in self.plugins:
            return f"Error: Plugin '{plugin_name}' not found."
            
        if function_name not in self.plugins[plugin_name]:
            return f"Error: Function '{function_name}' not found in plugin '{plugin_name}'."
            
        return f"Semantic Kernel invoked {plugin_name}.{function_name} with arguments {arguments}. Result: Success."

kernel = MockSemanticKernel()

app = Server("semantickernel-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="import_plugin",
            description="Import a new Semantic Kernel plugin.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the plugin."
                    },
                    "functions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of function names in the plugin."
                    }
                },
                "required": ["name", "functions"]
            }
        ),
        Tool(
            name="invoke_function",
            description="Invoke a Semantic Kernel function.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plugin_name": {
                        "type": "string",
                        "description": "The name of the plugin."
                    },
                    "function_name": {
                        "type": "string",
                        "description": "The name of the function to invoke."
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for the function."
                    }
                },
                "required": ["plugin_name", "function_name"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "import_plugin":
        plugin_name = arguments.get("name")
        functions = arguments.get("functions", [])
        
        if not plugin_name:
            return [TextContent(type="text", text="Error: name is required.")]
            
        result = kernel.import_plugin(plugin_name, functions)
        return [TextContent(type="text", text=result)]
        
    elif name == "invoke_function":
        plugin_name = arguments.get("plugin_name")
        function_name = arguments.get("function_name")
        func_args = arguments.get("arguments", {})
        
        if not plugin_name or not function_name:
            return [TextContent(type="text", text="Error: plugin_name and function_name are required.")]
            
        result = kernel.invoke_function(plugin_name, function_name, func_args)
        return [TextContent(type="text", text=result)]
        
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
