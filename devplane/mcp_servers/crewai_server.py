import asyncio
import os
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Mock CrewAI for now to avoid heavy dependencies if not installed
class MockCrewAI:
    def __init__(self):
        self.crews = {}

    def create_crew(self, name: str, agents: List[str], tasks: List[str]):
        self.crews[name] = {"agents": agents, "tasks": tasks}
        return f"Crew '{name}' created with {len(agents)} agents and {len(tasks)} tasks."

    def kickoff_crew(self, name: str, inputs: Dict[str, Any]) -> str:
        if name not in self.crews:
            return f"Error: Crew '{name}' not found."
        
        crew = self.crews[name]
        return f"Crew '{name}' kicked off successfully. Agents {crew['agents']} completed tasks {crew['tasks']} with inputs {inputs}."

crew_manager = MockCrewAI()

app = Server("crewai-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_crew",
            description="Create a new CrewAI crew with specified agents and tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the crew."
                    },
                    "agents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of agent roles."
                    },
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of task descriptions."
                    }
                },
                "required": ["name", "agents", "tasks"]
            }
        ),
        Tool(
            name="kickoff_crew",
            description="Kickoff an existing CrewAI crew.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the crew to kickoff."
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Inputs for the crew execution."
                    }
                },
                "required": ["name"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "create_crew":
        crew_name = arguments.get("name")
        agents = arguments.get("agents", [])
        tasks = arguments.get("tasks", [])
        
        if not crew_name:
            return [TextContent(type="text", text="Error: name is required.")]
            
        result = crew_manager.create_crew(crew_name, agents, tasks)
        return [TextContent(type="text", text=result)]
        
    elif name == "kickoff_crew":
        crew_name = arguments.get("name")
        inputs = arguments.get("inputs", {})
        
        if not crew_name:
            return [TextContent(type="text", text="Error: name is required.")]
            
        result = crew_manager.kickoff_crew(crew_name, inputs)
        return [TextContent(type="text", text=result)]
        
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
