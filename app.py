#!/usr/bin/env python3
"""
TrainerCentral Automation & Chat Application
--------------------------------------------
Features:
1. Hourly Background Scheduler: Automatically analyzes .txt files in the folder
   using Anthropic Claude Sonnet 5.5 and posts matching entries to the TrainerCentral API.
2. REST API Backend (FastAPI): Exposes endpoints for chat, manual triggers, status, and logs.
3. Interactive Chat Interface: Powered by Anthropic Claude Sonnet 5.5 with tool execution.
4. Static Web Frontend: Modern UI with real-time chat, scheduler controls, and submissions feed.
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import anthropic

# Import core assignment processing logic
from process_assignments import (
    find_txt_files,
    load_file_contents,
    analyze_files_with_anthropic,
    fallback_local_analysis,
    post_entry_to_api,
    resolve_model_name,
    DEFAULT_API_BASE_URL,
    DEFAULT_TARGET_EMAIL,
    DEFAULT_MODEL,
)

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrainerCentralApp")

app = FastAPI(title="TrainerCentral Assignment Hub & Chat", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKSPACE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = WORKSPACE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

SCHEDULER_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", 3600))  # 1 Hour


# ---------------------------------------------------------------------------
# Background Hourly Scheduler
# ---------------------------------------------------------------------------
class HourlyScheduler:
    def __init__(self, interval_seconds: int = 3600):
        self.interval_seconds = interval_seconds
        self.is_active = True
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count = 0
        self.history: List[Dict[str, Any]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        """Start the background scheduler thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"Hourly scheduler started with interval: {self.interval_seconds}s")

    def stop(self):
        """Stop the background scheduler."""
        self._stop_event.set()

    def _run_loop(self):
        # Calculate initial next_run
        self.next_run = datetime.now(timezone.utc)
        while not self._stop_event.is_set():
            if self.is_active:
                logger.info("Executing scheduled hourly assignment check...")
                self.execute_job(trigger_source="scheduler")

            # Schedule next run
            now = datetime.now(timezone.utc)
            self.next_run = datetime.fromtimestamp(now.timestamp() + self.interval_seconds, tz=timezone.utc)

            # Wait in small intervals so stop_event is responsive
            elapsed = 0
            while elapsed < self.interval_seconds and not self._stop_event.is_set():
                time.sleep(1)
                elapsed += 1

    def execute_job(self, trigger_source: str = "manual") -> Dict[str, Any]:
        """Run the assignment detection and posting job."""
        with self._lock:
            start_time = datetime.now(timezone.utc)
            self.last_run = start_time
            self.run_count += 1

            record: Dict[str, Any] = {
                "run_id": self.run_count,
                "trigger": trigger_source,
                "timestamp": start_time.isoformat(),
                "status": "pending",
                "matched_files": [],
                "api_responses": [],
                "logs": [],
            }

            try:
                txt_files = find_txt_files(WORKSPACE_DIR)
                record["logs"].append(f"Found {len(txt_files)} text files in {WORKSPACE_DIR.name}")

                if not txt_files:
                    record["status"] = "warning"
                    record["logs"].append("No .txt files found to process.")
                    self.history.insert(0, record)
                    return record

                files_data = load_file_contents(txt_files)
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                model_name = resolve_model_name(os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL))
                target_email = os.environ.get("TARGET_EMAIL", DEFAULT_TARGET_EMAIL)

                analysis = None
                if api_key:
                    try:
                        record["logs"].append(f"Analyzing files with Anthropic model: {model_name}")
                        analysis = analyze_files_with_anthropic(
                            files_data=files_data,
                            target_email=target_email,
                            model_name=model_name,
                            api_key=api_key,
                        )
                    except Exception as err:
                        record["logs"].append(f"Anthropic API call failed: {err}. Using local fallback...")
                        analysis = fallback_local_analysis(files_data, target_email)
                else:
                    record["logs"].append("No ANTHROPIC_API_KEY configured. Using local fallback search...")
                    analysis = fallback_local_analysis(files_data, target_email)

                matches = analysis.get("matches", [])
                record["matched_files"] = [m.get("filename") for m in matches]
                record["logs"].append(f"Identified {len(matches)} matching file(s) for '{target_email}'.")

                api_url = os.environ.get("TRAINER_CENTRAL_API_URL", DEFAULT_API_BASE_URL)
                x_api_key = os.environ.get("TRAINER_CENTRAL_API_KEY")

                for m in matches:
                    text = m.get("text")
                    sender = m.get("sender")
                    filename = m.get("filename")
                    try:
                        res = post_entry_to_api(api_url, text, sender, x_api_key)
                        res_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {"text": res.text}
                        record["api_responses"].append({
                            "filename": filename,
                            "sender": sender,
                            "status_code": res.status_code,
                            "response": res_data,
                        })
                        record["logs"].append(f"Posted {filename} ({sender}) -> HTTP {res.status_code}")
                    except Exception as post_err:
                        record["logs"].append(f"Failed to post {filename}: {post_err}")

                record["status"] = "success"
            except Exception as exc:
                logger.error(f"Error during job execution: {exc}", exc_info=True)
                record["status"] = "failed"
                record["logs"].append(f"Fatal error: {exc}")

            # Keep only last 30 runs in history
            self.history.insert(0, record)
            if len(self.history) > 30:
                self.history = self.history[:30]

            return record

    def get_status(self) -> Dict[str, Any]:
        """Return the current scheduler status."""
        now = datetime.now(timezone.utc)
        seconds_until_next = None
        if self.next_run:
            diff = (self.next_run - now).total_seconds()
            seconds_until_next = max(0, int(diff))

        return {
            "active": self.is_active,
            "interval_seconds": self.interval_seconds,
            "interval_human": f"{self.interval_seconds // 60} minutes" if self.interval_seconds < 3600 else f"{self.interval_seconds // 3600} hour(s)",
            "run_count": self.run_count,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "seconds_until_next": seconds_until_next,
            "latest_job": self.history[0] if self.history else None,
        }


scheduler = HourlyScheduler(interval_seconds=SCHEDULER_INTERVAL_SECONDS)


@app.on_event("startup")
def on_startup():
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown():
    scheduler.stop()


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/status")
def get_status():
    txt_files = [f.name for f in find_txt_files(WORKSPACE_DIR)]
    return {
        "scheduler": scheduler.get_status(),
        "workspace": {
            "directory": str(WORKSPACE_DIR),
            "files_count": len(txt_files),
            "files": txt_files,
        },
        "target_email": os.environ.get("TARGET_EMAIL", DEFAULT_TARGET_EMAIL),
        "model": resolve_model_name(os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)),
    }


@app.post("/api/scheduler/trigger")
def trigger_scheduler_now():
    """Trigger the assignment job immediately."""
    result = scheduler.execute_job(trigger_source="manual_web_ui")
    return {"message": "Job executed successfully", "result": result}


@app.post("/api/scheduler/toggle")
def toggle_scheduler():
    """Pause or resume the hourly scheduler."""
    scheduler.is_active = not scheduler.is_active
    status = "resumed" if scheduler.is_active else "paused"
    return {"message": f"Scheduler {status}", "active": scheduler.is_active}


@app.get("/api/scheduler/history")
def get_scheduler_history():
    return {"history": scheduler.history}


@app.get("/api/files")
def get_files_info():
    """List details of all .txt files in the folder."""
    files = find_txt_files(WORKSPACE_DIR)
    target_email = os.environ.get("TARGET_EMAIL", DEFAULT_TARGET_EMAIL).lower()
    items = []
    for f in files:
        content = f.read_text(encoding="utf-8", errors="replace")
        has_match = target_email in content.lower()
        items.append({
            "name": f.name,
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            "contains_target": has_match,
            "preview": content[:180] + ("..." if len(content) > 180 else ""),
        })
    return {"files": items}


@app.get("/api/remote-entries")
def get_remote_entries():
    """Fetch current entries from the live TrainerCentral Assignments API."""
    api_url = f"{DEFAULT_API_BASE_URL.rstrip('/')}/api/entries?limit=10"
    try:
        r = requests.get(api_url, timeout=10)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch remote entries: {e}")


# ---------------------------------------------------------------------------
# Chat Interface Endpoint
# ---------------------------------------------------------------------------
@app.post("/api/chat")
def chat_with_assistant(req: ChatRequest):
    """
    Handle natural language chat requests using Anthropic Claude Sonnet 5.5.
    Equipped with system awareness and action execution capabilities.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "reply": "⚠️ **Anthropic API key is not configured.** Please add `ANTHROPIC_API_KEY` to your `.env` file to chat with Claude Sonnet 5.5."
        }

    model_name = resolve_model_name(os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL))
    target_email = os.environ.get("TARGET_EMAIL", DEFAULT_TARGET_EMAIL)
    txt_files = [f.name for f in find_txt_files(WORKSPACE_DIR)]
    sched_info = scheduler.get_status()

    # System prompt provides rich context to Claude
    system_prompt = f"""You are the TrainerCentral AI Assignment & Automation Assistant.
You have access to the local workspace containing student assignment notification files.
Your capabilities:
1. Help users inspect, analyze, and manage assignment submission files.
2. Monitor and report on the hourly background scheduler.
3. Help trigger assignment processing to the TrainerCentral API (https://trainer-central-assigments-api.onrender.com).

Current Workspace State:
- Directory: {WORKSPACE_DIR}
- Target Email to track: {target_email}
- Text files found ({len(txt_files)}): {', '.join(txt_files) if txt_files else 'None'}
- Hourly Scheduler: {'Active' if sched_info['active'] else 'Paused'} (Interval: {sched_info['interval_human']})
- Total Runs executed: {sched_info['run_count']}
- Last Run: {sched_info['last_run'] or 'None yet'}
- Next Run in: {sched_info['seconds_until_next']} seconds

If the user asks you to 'run the job', 'process assignments', or 'sync now', indicate that you will trigger the job, and the backend will execute it.
Answer user questions clearly, formatting responses with markdown, bullet points, or code blocks when helpful.
"""

    # Build conversation messages
    messages = []
    if req.history:
        for msg in req.history[-6:]:  # Keep recent context
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": req.message})

    # Check for direct action triggers in the user message
    user_intent_lower = req.message.lower()
    action_result = None

    if any(k in user_intent_lower for k in ["run now", "run job", "process assignment", "sync now", "post now", "trigger job"]):
        logger.info("Chat requested manual job execution.")
        job_res = scheduler.execute_job(trigger_source="chat_command")
        action_result = {
            "action": "trigger_job",
            "status": job_res["status"],
            "matches": job_res["matched_files"],
            "logs": job_res["logs"],
        }
        # Add system context that the job just completed
        messages.append({
            "role": "user",
            "content": f"[System Context: The assignment processing job was just executed. Status: {job_res['status']}. Matches: {job_res['matched_files']}. API Results: {len(job_res['api_responses'])} entries posted.] Please confirm this to the user."
        })

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        reply_text = response.content[0].text
        return {
            "reply": reply_text,
            "action_executed": action_result,
            "scheduler_status": scheduler.get_status(),
        }
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        return {
            "reply": f"❌ **Error calling Anthropic Claude ({model_name}):** {str(e)}",
            "action_executed": action_result,
        }


# ---------------------------------------------------------------------------
# Serve Static Frontend
# ---------------------------------------------------------------------------
@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>TrainerCentral Backend is running. Frontend loading...</h1>")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"\n=======================================================")
    print(f"🚀 TrainerCentral Server & Scheduler starting...")
    print(f"📡 Web & Chat UI:  http://localhost:{port}")
    print(f"🕒 Hourly Sync:    Running every {SCHEDULER_INTERVAL_SECONDS} seconds")
    print(f"=======================================================\n")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
