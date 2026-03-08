"""LangGraph Agent Framework — Persistent Multi-Agent State Machine.

Upgrades DevPlane from a simple loop sequence into a stateful,
persistent agent capable of tool use, reflection, and picking up
exactly where it left off across runs.
"""

import operator
from typing import Annotated, TypedDict, Sequence, Optional, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
import subprocess
import os
import logging
import json
import importlib
from devplane.infra.mcp import get_mcp_manager

# ─── State Schema ─────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """The persistent state of the DevPlane Agent."""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    project_id: int
    current_tier: str
    tools_called: int

# ─── Tools ────────────────────────────────────────────────────────────────────

@tool
def write_file(path: str, content: str) -> str:
    """Writes the given content to a file at the specified path."""
    try:
        # Create directories if needed
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

@tool
def read_file(path: str) -> str:
    """Reads the content of a file at the specified path."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@tool
def fetch_url(url: str) -> str:
    """Fetches the text content of a URL."""
    import httpx
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.text[:5000] # Return safe chunk
    except Exception as e:
        return f"Error fetching URL: {str(e)}"

@tool
def execute_python(code: str) -> str:
    """Executes python code locally string and returns the output stdout. Only use if absolutely necessary and safe."""
    import subprocess
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        temp_path = f.name
        
    try:
        # Run the safe temporary script
        result = subprocess.run(["python", temp_path], capture_output=True, text=True, timeout=10.0)
        os.remove(temp_path)
        
        output = result.stdout
        if result.stderr:
            output += f"\nERRORS:\n{result.stderr}"
        return output if output else "Executed successfully with no output."
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return f"Failed to execute code: {str(e)}"

async def get_enabled_core_tools():
    """Return list of enabled core tool functions based on tool_config table."""
    from devplane.db import get_db
    db = await get_db()
    try:
        rows = await db.execute("SELECT tool_name, enabled FROM tool_config WHERE enabled = 1")
        enabled_tools = [row["tool_name"] for row in await rows.fetchall()]
    except Exception as e:
        logger = logging.getLogger("devplane.chain.agent")
        logger.warning(f"Failed to fetch tool config: {e}")
        enabled_tools = ["write_file", "read_file", "fetch_url", "execute_python"]  # default all
    tool_map = {
        "write_file": write_file,
        "read_file": read_file,
        "fetch_url": fetch_url,
        "execute_python": execute_python,
        "search_web": None,  # placeholder, not implemented
        "list_files": None,
        "apply_diff": None,
        "delete_file": None,
        "codebase_search": None,
        "search_files": None,
    }
    # Filter out None (unimplemented) and disabled
    return [tool_map[name] for name in enabled_tools if name in tool_map and tool_map[name] is not None]


async def get_langchain_tools():
    """Return list of LangChain tools registered in langchain_tools table."""
    from devplane.db import get_db
    db = await get_db()
    try:
        rows = await db.execute("SELECT * FROM langchain_tools WHERE enabled = 1")
        tools = []
        for row in await rows.fetchall():
            tool = dict(row)
            # Parse JSON fields
            schema = json.loads(tool.get("schema_json") or "{}")
            handler_config = json.loads(tool.get("handler_config_json") or "{}")
            handler_type = tool.get("handler_type", "python_function")
            # Create tool based on handler_type
            if handler_type == "python_function":
                # Expect module and function in handler_config
                module_name = handler_config.get("module")
                func_name = handler_config.get("function")
                if not module_name or not func_name:
                    logger = logging.getLogger("devplane.chain.agent")
                    logger.warning(f"Missing module/function for tool {tool['name']}")
                    continue
                try:
                    module = importlib.import_module(module_name)
                    func = getattr(module, func_name)
                except (ImportError, AttributeError) as e:
                    logger.warning(f"Failed to import {module_name}.{func_name}: {e}")
                    continue
                # Create a LangChain tool from the function
                # Use the existing @tool decorator to wrap
                from langchain_core.tools import tool
                # Check if already a tool (has .args_schema etc.)
                if hasattr(func, "_tool_type"):
                    # Already a tool
                    tools.append(func)
                else:
                    # Wrap with description
                    wrapped = tool(func)
                    tools.append(wrapped)
            else:
                # Unsupported handler type, skip
                logger = logging.getLogger("devplane.chain.agent")
                logger.warning(f"Unsupported handler type {handler_type} for tool {tool['name']}")
        return tools
    except Exception as e:
        logger = logging.getLogger("devplane.chain.agent")
        logger.warning(f"Failed to fetch langchain tools: {e}")
        return []
# Register core tools (all defined tools, filtering happens in dynamic_tool_node)
agent_tools = [write_file, read_file, fetch_url, execute_python]

async def dynamic_tool_node(state: AgentState) -> dict:
    """Dynamically loads and executes tools including MCP capabilities."""
    from devplane.infra.mcp import get_mcp_manager
    mcp_manager = get_mcp_manager()
    enabled_core_tools = await get_enabled_core_tools()
    langchain_tools = await get_langchain_tools()
    all_tools = enabled_core_tools + mcp_manager.get_agent_tools() + langchain_tools
    
    # We create a temporary ToolNode mapped to the current combined tools
    node = ToolNode(all_tools)
    return await node.ainvoke(state)


# ─── Nodes ────────────────────────────────────────────────────────────────────

async def agent_node(state: AgentState) -> dict:
    """The core decision-making brain of the agent."""
    messages = state["messages"]
    tier_model = state.get("current_tier", "anthropic/claude-3-5-sonnet-20240620")
    
    # We use ChatLiteLLM which wraps litellm in the LangChain BaseChatModel interface
    # allowing native LangGraph tool passing and streaming
    llm = ChatLiteLLM(model=tier_model, temperature=0.7)
    
    # Bind our registered tools
    llm_with_tools = llm.bind_tools(agent_tools)
    
    # Ensure system prompt is first if not present
    if not any(isinstance(m, SystemMessage) for m in messages):
        sys_msg = SystemMessage(content="You are an elite DevPlane AI agent. "
            "You have tools to read and write files to the local disk. "
            "Think step-by-step and use your tools to complete complex tasks autonomously.")
        messages = [sys_msg] + list(messages)
    
    # Execute the LLM
    response = await llm_with_tools.ainvoke(messages)
    
    return {"messages": [response]}

# ─── Edges ────────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    """Determine if we are done or need to call tools."""
    last_msg = state["messages"][-1]
    
    # If there are tool calls, go to tools
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
        
    return "end"

# ─── Graph Construction ───────────────────────────────────────────────────────

def build_graph():
    """Constructs the LangGraph state machine."""
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", dynamic_tool_node)
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional edges from agent
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )
    
    # Tools always return to agent
    workflow.add_edge("tools", "agent")
    
    return workflow

# Singleton graph builder
def get_agent_graph(checkpointer=None):
    """Get the compiled graph, optionally with a checkpointer."""
    workflow = build_graph()
    if checkpointer:
        return workflow.compile(checkpointer=checkpointer)
    return workflow.compile()
