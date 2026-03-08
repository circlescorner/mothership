# The Agentic Mesh Architecture

DevPlane implements a unified "Agentic Mesh" architecture that leverages the Model Context Protocol (MCP) as a universal communication backbone to integrate the top five open-source LLM tools.

## Core Components

The system treats each framework as a specialized MCP Server that exposes its unique strengths as standardized tools to a central MCP Host (the Slack Bot).

1. **LlamaIndex (The Librarian)**: Operates as an MCP Server providing data retrieval tools. It indexes private documentation and provides high-accuracy context to the rest of the mesh.
2. **Haystack (The Search Specialist)**: Acts as an MCP Server for enterprise search. It manages complex NLP pipelines and connects to production-grade document stores.
3. **CrewAI (The Manager)**: Functions as the multi-agent orchestrator. It provides task execution tools where specialized agents collaborate to solve multi-step problems.
4. **PydanticAI (The Validator)**: Serves as the "Safe Gateway." Every piece of data entering or leaving the mesh is validated against strict schemas to ensure production-grade reliability.
5. **Semantic Kernel (The Enterprise Bridge)**: Connects the mesh to existing business logic, exposing legacy enterprise functions as MCP-compatible tools.

## Visualizing the Mesh

DevPlane integrates **Langflow** and **Flowise AI** to provide a "single pane of glass" for visualizing and configuring chains and networking.

- **Langflow**: Available at `http://localhost:7860`
- **Flowise**: Available at `http://localhost:3001`

These low-code platforms allow you to drag and drop components from all frameworks onto a single canvas, visually mapping how a query flows through the system.

## Real-time Observability

**Langfuse** is integrated into the mesh to provide real-time observability. It displays live trace graphs of every "node" in the mesh, allowing for deep-dive debugging of the execution chain.

- **Langfuse**: Available at `http://localhost:3002`

## The Central Hub: Slack Integration

Slack acts as the primary user interface (the MCP Client) for the Agentic Mesh.

- **Command**: `!mesh_route <task>`
- **Workflow**:
  1. A user sends a message in Slack using the `!mesh_route` command.
  2. The Slack App (the Host) broadcasts the intent to the MCP Mesh.
  3. The mesh intelligently routes the task to the appropriate MCP servers (e.g., Haystack for search, LlamaIndex for retrieval, CrewAI for orchestration).
  4. The unified response is posted back to the Slack thread, along with links to Langfuse and Langflow for debugging and configuration.

## Persistent Agents

DevPlane includes two persistent agents that run continuously in the background:

1. **Infra Manager**: Dedicated to managing infrastructure, maintaining documented status, and handling aggressive scale-to-zero operations based on budget limits.
2. **Builder**: Dedicated to building and implementing improvements on DevPlane itself.

## Budgeting and Scale-to-Zero

The Infra Manager agent continuously monitors the daily budget. If spending approaches the limit (90%), it enables an aggressive scale-to-zero mode, automatically snapshotting and destroying all non-essential droplets to prevent budget overruns.
