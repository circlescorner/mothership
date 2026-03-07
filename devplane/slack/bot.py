"""Slack bot integration — uses the chain engine instead of hardcoded stacks."""

import re
import logging
import os
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from devplane.chain.engine import run_tournament
from devplane.db import get_default_project_id

logger = logging.getLogger("devplane.slack")

slack_app = None
slack_handler = None


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

        if not query:
            await say(text="Send me a prompt and I'll run it through the AI chain! 🛰️", thread_ts=thread_ts)
            return

        await say(text="🚀 *DevPlane Engines Engaged.* Running AI Chain Tournament...", thread_ts=thread_ts)

        try:
            project_id = await get_default_project_id()
            result = await run_tournament(query, project_id)

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

    logger.info("Slack bot initialized")
