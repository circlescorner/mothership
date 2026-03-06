import asyncio
import os
import re
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import set_key, load_dotenv
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from litellm import acompletion

load_dotenv() # Load initial if present

# Configure logging for production observability
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mothership")

# Initialize Slack App Conditionally
slack_token = os.environ.get("SLACK_BOT_TOKEN")
slack_app_token = os.environ.get("SLACK_APP_TOKEN")

slack_app = AsyncApp(token=slack_token) if slack_token else None
slack_handler = AsyncSocketModeHandler(slack_app, slack_app_token) if slack_app and slack_app_token else None

# Manage FastAPI Lifespan to run Socket Mode concurrently with Web Server
@asynccontextmanager
async def lifespan(app: FastAPI):
    if slack_handler:
        logger.info("Starting Slack Socket Mode Handler...")
        task = asyncio.create_task(slack_handler.start_async())
        yield
        logger.info("Closing Slack Socket Mode Handler...")
        await slack_handler.close_async()
        task.cancel()
    else:
        logger.warning("SLACK Tokens missing. Running Web-Only Setup Mode.")
        yield

app = FastAPI(title="Mothership 2026", lifespan=lifespan)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

class SetupData(BaseModel):
    SLACK_BOT_TOKEN: str
    SLACK_APP_TOKEN: str
    TOGETHERAI_API_KEY: str = ""
    SILICONFLOW_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    CEREBRAS_API_KEY: str = ""
    QDRANT_URL: str
    QDRANT_KEY: str

def is_setup_complete():
    return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"))


# The 3-Stack Configuration
STACK_CONFIG = {
    "LOGIC": {"P": "together_ai/deepseek-ai/deepseek-r1", "E": "deepseek/deepseek-chat", "R": "deepseek/deepseek-chat"},
    "SPEED": {"P": "cerebras/llama-4-scout", "E": "siliconflow/mimo-v2-flash", "R": "siliconflow/deepseek-v3.2"},
    "EFFICIENCY": {"P": "siliconflow/deepseek-v3.2", "E": "siliconflow/mimo-v2-flash", "R": "siliconflow/mimo-v2-flash"}
}

@app.get("/")
async def health_check():
    if not is_setup_complete():
        return RedirectResponse(url="/setup")
    return {"status": "🛰️ Mothership Online", "domain": "glondor.xyz", "ephemeral_mode": "ACTIVE"}

@app.get("/setup", response_class=HTMLResponse)
async def setup_wizard():
    if is_setup_complete():
        return RedirectResponse(url="/")
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<html><body><h1>Setup Wizard Template Missing</h1><p>{str(e)}</p></body></html>"

@app.post("/api/setup")
async def save_setup(data: SetupData):
    env_file = ".env"
    if not os.path.exists(env_file):
        open(env_file, 'a').close()
    
    for key, value in data.model_dump().items():
        if value:
            set_key(env_file, key, value)
            os.environ[key] = value
            
    logger.info("Configuration saved. Reboot recommended to fully load tokens.")
    # Exit down to trigger a restart via process manager (e.g. docker/fly)
    asyncio.create_task(shutdown_server())
    return {"status": "success"}

async def shutdown_server():
    await asyncio.sleep(2)
    os._exit(0)


async def run_stack(name: str, prompt: str):
    """Executes the Planner -> Executor -> Reviewer pipeline for a given stack."""
    cfg = STACK_CONFIG[name]
    try:
        # Step 1: PLANNER
        logger.info(f"[{name}] Generating Plan...")
        plan_res = await acompletion(
            model=cfg["P"], 
            messages=[
                {"role": "system", "content": "You are a concise planner. Break down the user request into 3 execution steps."},
                {"role": "user", "content": prompt}
            ]
        )
        plan = plan_res.choices[0].message.content

        # Step 2: EXECUTOR
        logger.info(f"[{name}] Executing Plan...")
        exec_res = await acompletion(
            model=cfg["E"], 
            messages=[
                {"role": "system", "content": f"Execute the following plan precisely:\n{plan}"},
                {"role": "user", "content": prompt}
            ]
        )
        execution = exec_res.choices[0].message.content

        # Step 3: REVIEWER
        logger.info(f"[{name}] Reviewing Output...")
        rev_res = await acompletion(
            model=cfg["R"], 
            messages=[
                {"role": "system", "content": f"You are a reviewer. Polish the provided execution output which was created to fulfill the user request: '{prompt}'. Fix errors and format cleanly. Output ONLY the polished response."},
                {"role": "user", "content": execution}
            ]
        )
        final_output = rev_res.choices[0].message.content
        
        return {"name": name, "output": final_output, "status": "success"}

    except Exception as e:
        logger.error(f"[{name}] Stack Failed: {str(e)}")
        return {"name": name, "output": str(e), "status": "error"}

async def handle_vibe(event, say):
    thread_ts = event.get("thread_ts", event["ts"])
    # Strip <@U...> Slack mentions
    raw_text = event["text"]
    query = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
    
    # Fast UX Acknowledgment
    await say(text="🚀 *Mothership Engines Engaged.* Running 3-Stack AI Tournament...", thread_ts=thread_ts)
    
    # Trigger Parallel Pipeline 
    tasks = [run_stack(name, query) for name in STACK_CONFIG.keys()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out catastrophic failures
    valid_results = [r for r in results if isinstance(r, dict) and r["status"] == "success"]
    
    if not valid_results:
        await say(text="🚨 **All AI compute stacks failed to process the request. Check API balances.**", thread_ts=thread_ts)
        return

    # Dynamic Judging Prompt
    judge_system = f"You are an elite autonomous judge evaluating AI pipelines. Review the candidate outputs below for the user query: '{query}'. Choose the most accurate, comprehensive, and fastest answer. Output the winning stack's name in bold, followed by its complete response. Provide a 1-sentence explanation of why it won at the bottom."
    
    judge_prompt = ""
    for r in valid_results:
        judge_prompt += f"--- CANDIDATE: {r['name']} ---\n{r['output']}\n\n"

    try:
        # Judge makes the final call
        judge = await acompletion(
            model="deepseek/deepseek-chat", 
            messages=[
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_prompt}
            ]
        )
        winner_text = judge.choices[0].message.content
        await say(text=f"🏆 *TOURNAMENT WINNER*\n\n{winner_text}", thread_ts=thread_ts)
    except Exception as e:
        logger.error(f"Judge Evaluation Failed: {e}")
        await say(text="🚨 **Judge evaluation failed. Falling back to first available output.**\n\n" + valid_results[0]["output"], thread_ts=thread_ts)

if slack_app:
    slack_app.event("app_mention")(handle_vibe)

if __name__ == "__main__":
    import uvicorn
    # In production on Fly.io, uvicorn is launched via the Dockerfile CMD.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
