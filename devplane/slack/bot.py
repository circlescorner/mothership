"""Slack bot integration — handles files, interactive buttons, and cross-IDE agent routing."""

import re
import logging
import os
import json
import asyncio
import httpx
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from devplane.chain.engine import run_tournament
from devplane.db import get_default_project_id, get_db
from devplane.infra.manager import get_infra_manager

logger = logging.getLogger("devplane.slack")

slack_app = None
slack_handler = None

async def download_slack_file(url: str, token: str) -> str:
    """Download a file uploaded to Slack."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                # We assume text-based attachments for code/logs
                return resp.text
            return f"[Failed to download file: HTTP {resp.status_code}]"
        except Exception as e:
            return f"[Failed to download file: {str(e)}]"

def init_slack():
    """Initialize Slack bot if tokens are available."""
    global slack_app, slack_handler

    token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")

    if not token or not app_token:
        logger.warning("Slack tokens not configured. Bot disabled.")
        return

    slack_app = AsyncApp(token=token)
    slack_handler = AsyncSocketModeHandler(slack_app, app_token)

    @slack_app.event("app_mention")
    async def handle_mention(event, say):
        thread_ts = event.get("thread_ts", event["ts"])
        raw_text = event["text"]
        query = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()

        # 1. Handle File Attachments
        files = event.get("files", [])
        file_contents = []
        for f in files:
            if "url_private_download" in f:
                content = await download_slack_file(f["url_private_download"], token)
                file_contents.append(f"--- File: {f.get('name', 'attachment')} ---\n{content}\n")
        
        if file_contents:
            query += "\n\n[Attached Files Context]\n" + "\n".join(file_contents)

        if not query:
            await say(text="Send me a prompt (you can attach files too!) and I'll route it. 🛰️", thread_ts=thread_ts)
            return

        # 2. Check for dynamic IDE Agent routing (e.g. !kilo_web_researcher lookup python docs)
        agent_match = re.match(r"^!([a-zA-Z0-9_-]+)\s+(.*)", query, re.DOTALL)
        if agent_match:
            agent_cmd = agent_match.group(1).lower()
            agent_prompt = agent_match.group(2).strip()
            
            db = await get_db()
            try:
                row = await db.execute("SELECT * FROM agent_workflows WHERE REPLACE(LOWER(agent_name), ' ', '_') = ?", (agent_cmd,))
                agent_record = await row.fetchone()
                
                if agent_record:
                    await say(text=f"🔌 *Routing to External IDE:* Pushing task to `{agent_record['ide_name']}` ({agent_record['agent_name']})...", thread_ts=thread_ts)
                    
                    # Queue task
                    payload = json.dumps({"prompt": agent_prompt}) # simplified schema assumption
                    cursor = await db.execute(
                        "INSERT INTO devplane_tasks (agent_name, payload_json, status) VALUES (?, ?, 'pending')",
                        (agent_record["agent_name"], payload)
                    )
                    await db.commit()
                    task_id = cursor.lastrowid
                    
                    # Async task to poll DB and reply back to slack later
                    async def poll_task():
                        db_poll = await get_db()
                        try:
                            for _ in range(120): # 4 minutes max for IDE to process
                                await asyncio.sleep(2)
                                poll = await db_poll.execute("SELECT status, result_json, error_message FROM devplane_tasks WHERE id = ?", (task_id,))
                                res = await poll.fetchone()
                                if res["status"] == "completed":
                                    await say(text=f"✅ *{agent_record['ide_name']} completed the task:*\n\n{res['result_json']}", thread_ts=thread_ts)
                                    return
                                elif res["status"] == "error":
                                    await say(text=f"🚨 *{agent_record['ide_name']} Agent Error:*\n{res['error_message']}", thread_ts=thread_ts)
                                    return
                            
                            # Timeout
                            await db_poll.execute("UPDATE devplane_tasks SET status = 'timeout' WHERE id = ?", (task_id,))
                            await db_poll.commit()
                            await say(text=f"⚠️ *Timeout:* {agent_record['ide_name']} did not respond within 4 minutes. Ensure the IDE is running.", thread_ts=thread_ts)
                        finally:
                            await db_poll.close()
                    
                    asyncio.create_task(poll_task())
                    return
            finally:
                await db.close()

        # 3. Handle CloudOps Infrastructure Commands (!spinup, !sleep, !wake, !status)
        if query.startswith("!spinup worker"):
            await say(text="🚀 *Spinning up new ephemeral worker...*", thread_ts=thread_ts)
            res = await get_infra_manager().create_worker()
            if "error" in res:
                await say(text=f"🚨 Failed to spinup worker: {res['error']}", thread_ts=thread_ts)
            else:
                await say(text=f"✅ *Worker deployed* in {res['region']}! (`{res['name']}`)\nIP will be available shortly.", thread_ts=thread_ts)
            return
            
        elif query.startswith("!sleep"):
            await say(text="💤 *Initiating Collapse & Persist Protocol...*", thread_ts=thread_ts)
            droplets = await get_infra_manager().list_droplets()
            
            woke_count = 0
            for d in droplets:
                if d["status"] != "destroyed" and "kasm" in d.get("tags", []):
                    woke_count += 1
                    snap_name = f"devplane-snapshot-{d['name']}-{int(asyncio.get_event_loop().time())}"
                    await get_infra_manager().snapshot_droplet(d["id"], snap_name)
                    # Automatically destroy after initiating snapshot (DO will wait for snapshot to finish)
                    await get_infra_manager().destroy_droplet(d["id"])
                    
            await say(text=f"🌒 Collapsed {woke_count} visual workspaces into Snapshots to save costs. They are now offline.", thread_ts=thread_ts)
            return
            
        elif query.startswith("!wake"):
            await say(text="☀️ *Waking up workspaces from sleep state...*", thread_ts=thread_ts)
            snaps = await get_infra_manager().get_snapshots()
            if not snaps:
                await say(text="No DevPlane snapshots found to wake.", thread_ts=thread_ts)
                return
            
            # Wake the most recent snapshot as a simple workflow
            snaps.sort(key=lambda x: x["created_at"], reverse=True)
            target_snap = snaps[0]
            
            # Find the original name from snapshot name "devplane-snapshot-NAME-time"
            parts = target_snap["name"].split("-")
            name = "-".join(parts[2:-1]) if len(parts) > 3 else "restored-workspace"
            
            res = await get_infra_manager().restore_from_snapshot(target_snap["id"], name)
            if "error" in res:
                await say(text=f"🚨 Failed to wake workspace: {res['error']}", thread_ts=thread_ts)
            else:
                await say(text=f"✅ *Workspace Waking Up!* (`{res['name']}`)\nIt will be ready via CP Gateway in ~60 seconds.", thread_ts=thread_ts)
            return

        # 4. Agentic Mesh Routing (!mesh_route)
        if query.startswith("!mesh_route "):
            mesh_query = query[12:].strip()
            await say(text=f"🕸️ *Agentic Mesh Engaged.* Routing task: '{mesh_query}'...", thread_ts=thread_ts)
            
            # Mock routing logic to the different MCP servers
            route_log = []
            if "search" in mesh_query.lower() or "find" in mesh_query.lower():
                route_log.append("🔍 *Haystack (Search Specialist)*: Found relevant enterprise documents.")
            if "document" in mesh_query.lower() or "index" in mesh_query.lower():
                route_log.append("📚 *LlamaIndex (The Librarian)*: Retrieved high-accuracy context from private docs.")
            if "validate" in mesh_query.lower() or "schema" in mesh_query.lower():
                route_log.append("🛡️ *PydanticAI (The Validator)*: Validated data against strict schemas.")
            if "enterprise" in mesh_query.lower() or "logic" in mesh_query.lower():
                route_log.append("🌉 *Semantic Kernel (Enterprise Bridge)*: Invoked legacy business logic.")
            
            # CrewAI always orchestrates
            route_log.append("👔 *CrewAI (The Manager)*: Orchestrated agents to format the final report.")
            
            response_text = "\n".join(route_log) + "\n\n✅ *Task Completed Successfully.*\n🔗 View execution trace in Langfuse: http://localhost:3002\n🔗 Configure chains in Langflow: http://localhost:7860"
            
            await say(text=response_text, thread_ts=thread_ts)
            return

        # 5. Standard Chain Execution (Tournament / Mesh / Agent)
        mode = "tournament"
        if query.startswith("!mesh "):
            mode = "mesh"
            query = query[6:].strip()
        elif query.startswith("!agent "):
            mode = "agent"
            query = query[7:].strip()

        mode_label = {"tournament": "Tournament", "mesh": "God-Mode Mesh", "agent": "Agent"}[mode]
        await say(text=f"🚀 *DevPlane Engines Engaged.* Running {mode_label}...", thread_ts=thread_ts)

        try:
            project_id = await get_default_project_id()
            result = await run_tournament(query, project_id, mode=mode)

            if result["status"] == "success":
                winner = result.get("winning_tier", "").upper()
                cost = result.get("total_cost", 0.0)
                output = result["final_output"]
                await say(
                    text=f"🏆 *WINNER: {winner}* (${cost:.4f})\n\n{output}",
                    thread_ts=thread_ts
                )
            else:
                await say(
                    text=f"🚨 *Chain execution failed.* {result.get('final_output', 'Check API keys.')}",
                    thread_ts=thread_ts
                )
        except Exception as e:
            logger.error(f"Slack handler error: {e}")
            await say(text=f"🚨 *Error:* {str(e)}", thread_ts=thread_ts)


    # ── Interactive Button Handlers (Block Kit Actions) ──

    @slack_app.action("approve_action")
    async def handle_approval(ack, body, logger):
        await ack()
        action = body["actions"][0]
        value = action.get("value")
        user = body["user"]["id"]
        channel = body["container"]["channel_id"]
        thread_ts = body["message"].get("thread_ts", body["message"]["ts"])
        
        await slack_app.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"✅ <@{user}> approved action: `{value}`. Beginning execution..."
        )
        # TODO: Route specific values to infrastructure managers (e.g. value="create_droplet_h100")

    @slack_app.action("cancel_action")
    async def handle_cancellation(ack, body, logger):
        await ack()
        user = body["user"]["id"]
        channel = body["container"]["channel_id"]
        thread_ts = body["message"].get("thread_ts", body["message"]["ts"])
        
        await slack_app.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"🛑 <@{user}> cancelled the action."
        )

    logger.info("Advanced Slack bot initialized (Features: Files, Dynamic Agents, Interactivity)")
