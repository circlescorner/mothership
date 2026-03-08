import asyncio
import os
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Mock LlamaIndex for now to avoid heavy dependencies if not installed
class MockLlamaIndex:
    def __init__(self):
        self.documents = []

    def add_document(self, text: str):
        self.documents.append(text)

    def query(self, query_str: str) -> str:
        if not self.documents:
            return "No documents indexed."
        # Simple mock search
        results = [doc for doc in self.documents if any(word in doc.lower() for word in query_str.lower().split())]
        if results:
            return f"Found {len(results)} matching documents. Top result: {results[0][:100]}..."
        return "No matching documents found."

index = MockLlamaIndex()

app = Server("llamaindex-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_index",
            description="Query the LlamaIndex vector store for information.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query."
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="add_document",
            description="Add a document to the LlamaIndex vector store.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text content of the document."
                    }
                },
                "required": ["text"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_index":
        query = arguments.get("query")
        if not query:
            return [TextContent(type="text", text="Error: query is required.")]
        
        result = index.query(query)
        return [TextContent(type="text", text=result)]
        
    elif name == "add_document":
        text = arguments.get("text")
        if not text:
            return [TextContent(type="text", text="Error: text is required.")]
            
        index.add_document(text)
        return [TextContent(type="text", text="Document added successfully.")]
        
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
