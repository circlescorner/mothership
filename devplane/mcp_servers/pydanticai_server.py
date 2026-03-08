import asyncio
import json
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Mock PydanticAI for now to avoid heavy dependencies if not installed
class MockPydanticAIValidator:
    def __init__(self):
        self.schemas = {}

    def register_schema(self, name: str, schema: Dict[str, Any]):
        self.schemas[name] = schema
        return f"Schema '{name}' registered successfully."

    def validate_data(self, schema_name: str, data: Dict[str, Any]) -> str:
        if schema_name not in self.schemas:
            return f"Error: Schema '{schema_name}' not found."
        
        # Simple mock validation
        schema = self.schemas[schema_name]
        required_fields = schema.get("required", [])
        
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return f"Validation failed. Missing required fields: {', '.join(missing_fields)}"
            
        return f"Validation successful for data against schema '{schema_name}'."

validator = MockPydanticAIValidator()

app = Server("pydanticai-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="register_schema",
            description="Register a new Pydantic schema for validation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the schema."
                    },
                    "schema": {
                        "type": "object",
                        "description": "The JSON schema definition."
                    }
                },
                "required": ["name", "schema"]
            }
        ),
        Tool(
            name="validate_data",
            description="Validate data against a registered Pydantic schema.",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema_name": {
                        "type": "string",
                        "description": "The name of the registered schema."
                    },
                    "data": {
                        "type": "object",
                        "description": "The data to validate."
                    }
                },
                "required": ["schema_name", "data"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "register_schema":
        schema_name = arguments.get("name")
        schema = arguments.get("schema", {})
        
        if not schema_name:
            return [TextContent(type="text", text="Error: name is required.")]
            
        result = validator.register_schema(schema_name, schema)
        return [TextContent(type="text", text=result)]
        
    elif name == "validate_data":
        schema_name = arguments.get("schema_name")
        data = arguments.get("data", {})
        
        if not schema_name:
            return [TextContent(type="text", text="Error: schema_name is required.")]
            
        result = validator.validate_data(schema_name, data)
        return [TextContent(type="text", text=result)]
        
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
