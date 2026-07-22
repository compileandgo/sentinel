import sys
import os
import json
import uuid
import datetime
import asyncio
import concurrent.futures
import threading
import re
from pathlib import Path
import time
from typing import Dict, List, Optional
import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt

# Adjust path to import from src
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.agent.graph import build_graph
from src.config import Config
from src.web.db import (
    AuthenticatedUser,
    verify_token,
    get_user_client,
    get_admin_client,
    db_list_briefs,
    db_get_brief_content,
    db_create_chat,
    db_save_message,
    db_save_message_admin,
    db_save_brief_admin,
    db_delete_chat,
    db_rename_chat,
    db_update_chat_memory
)

app = FastAPI(title="Sentinel Geopolitical Intelligence Workspace")

# Global dict of active runs
active_runs = {}
active_cancellations = set()
active_resumes = {}

# Security JWT Dependency
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> AuthenticatedUser:
    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        print(f"[AUTH DEBUG] Unverified header: {header}")
        payload = verify_token(token)
        user_id = payload.get("sub")
        email = payload.get("email")
        if not user_id:
            print("[AUTH ERROR] Invalid token claims: sub/user_id not found")
            raise HTTPException(status_code=401, detail="Invalid token claims")
        client = get_user_client(token)
        return AuthenticatedUser(user_id=user_id, email=email, client=client)
    except ValueError as e:
        print(f"[AUTH ERROR] Token verification failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))

class ResearchRequest(BaseModel):
    topic: str
    max_iterations: int = 1
    max_subagents: int = 3
    run_id: Optional[str] = None

class StdoutRedirector:
    def __init__(self, callback):
        self.callback = callback
        self.original_stdout = sys.stdout

    def write(self, s):
        try:
            self.original_stdout.write(s)
            self.original_stdout.flush()
        except Exception:
            pass
        if s.strip():
            self.callback(s.strip())
        return len(s)

    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass

def run_agent_in_thread(run_id: str, chat_id: str, topic: str, max_iterations: int, max_subagents: int, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    from src.tools.llm import thread_local
    thread_local.run_id = run_id

    # Check for immediate cancellation before starting the graph
    if run_id in active_cancellations:
        print(f"   [Thread:{run_id}] Research run cancelled before starting.")
        active_resumes.pop(run_id, None)
        run_data = active_runs.get(run_id, {})
        run_data["status"] = "cancelled"
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "cancelled",
                "data": {
                    "message": "Research cancelled by user."
                }
            }
        )
        return

    # Dynamically update cost controls in Config
    Config.MAX_RESEARCH_ITERATIONS = max_iterations
    Config.MAX_SUBAGENTS = max_subagents
    
    # Initialize the compiled LangGraph
    try:
        graph = build_graph()
    except Exception as e:
        import traceback
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "error", "data": {"error": f"Failed to compile graph: {e}", "trace": traceback.format_exc()}}
        )
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "complete", "data": {}})
        return

    initial_state = {
        "topic": topic,
        "run_id": run_id,
        "plan_path": "",
        "start_time": time.time(),
        "research_backlog": [],
        "subagent_artifacts": [],
        "subagent_tasks": [],
        "raw_intel": [],
        "bias_matrix": [],
        "chronology": [],
        "iterations": 0,
        "eval_result": None,
        "uncited_ratio": None,
        "synthesis": "",
        "final_report": "",
    }

    # Setup stdout capture to queue
    def log_callback(message):
        # Push to async queue safely from thread
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "log",
                "data": {
                    "message": message,
                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
                }
            }
        )

    redirector = StdoutRedirector(log_callback)
    original_stdout = sys.stdout
    sys.stdout = redirector

    final_report = ""
    try:
        # Stream events from LangGraph synchronous runner
        for event in graph.stream(initial_state, stream_mode="updates"):
            # Check for cancellation before processing next updates
            if run_id in active_cancellations:
                print(f"   [Thread:{run_id}] Research run cancelled by user. Interrupting.")
                break

            # event keys represent completed node names
            for node_name, node_output in event.items():
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "status",
                        "data": {
                            "node": node_name,
                            "status": "completed"
                        }
                    }
                )

                # Extract update statistics
                intel_added = 0
                bias_added = 0
                chron_added = 0
                if isinstance(node_output, dict):
                    intel_added = len(node_output.get("raw_intel", []))
                    bias_added = len(node_output.get("bias_matrix", []))
                    chron_added = len(node_output.get("chronology", []))
                    if "final_report" in node_output:
                        final_report = node_output["final_report"]

                if intel_added or bias_added or chron_added:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {
                            "type": "data",
                            "data": {
                                "node": node_name,
                                "intel_added": intel_added,
                                "bias_added": bias_added,
                                "chron_added": chron_added
                            }
                        }
                    )

                # If lead_researcher finished on the first iteration, emit plan_ready and wait!
                if node_name == "lead_researcher" and isinstance(node_output, dict):
                    iterations = node_output.get("iterations", 0)
                    if iterations == 1:
                        tasks = []
                        for task in node_output.get("subagent_tasks", []):
                            tasks.append({
                                "subagent_id": task.get("subagent_id"),
                                "topic": task.get("topic"),
                                "task": task.get("task")
                            })
                        
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {
                                "type": "plan_ready",
                                "data": {
                                    "run_id": run_id,
                                    "topic": topic,
                                    "tasks": tasks
                                }
                            }
                        )
                        
                        # Wait on the thread event
                        print(f"   [Thread:{run_id}] Pausing execution after Lead Researcher to wait for plan approval...")
                        resume_event = active_resumes.get(run_id)
                        if resume_event:
                            resume_event.wait()
                        print(f"   [Thread:{run_id}] Plan approved or cancelled. Resuming...")

    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        if run_id not in active_cancellations:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "data": {"error": str(e), "trace": trace}}
            )
    finally:
        sys.stdout = original_stdout
        # Clean up resume event
        active_resumes.pop(run_id, None)
        # Update run outcomes
        run_data = active_runs.get(run_id, {})
        is_cancelled = run_id in active_cancellations
        
        if is_cancelled:
            run_data["status"] = "cancelled"
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "cancelled",
                    "data": {
                        "message": "Research cancelled by user."
                    }
                }
            )
            # Remove from cancellation tracking set
            active_cancellations.discard(run_id)
        else:
            run_data["status"] = "failed" if "error" in run_data else "completed"
            if final_report:
                run_data["final_report"] = final_report
                
                # Save completed research to Supabase Database
                try:
                    # Create unique slug for filename mapping
                    clean_topic = re.sub(r'[^a-zA-Z0-9\s-]', '', topic).strip()
                    clean_topic = re.sub(r'[\s-]+', '-', clean_topic).lower()
                    clean_topic = clean_topic[:40].strip("-")
                    if not clean_topic:
                        clean_topic = "research"
                    filename = f"research-{clean_topic}-{chat_id[:6]}.md"
                    
                    db_title = topic
                    title_match = re.search(r'<title>([\s\S]*?)</title>', final_report, re.IGNORECASE)
                    if title_match:
                        db_title = title_match.group(1).strip()
                    db_save_brief_admin(chat_id, db_title, final_report, filename)
                    db_save_message_admin(chat_id, "assistant", final_report, "brief")
                    print(f"   [Thread:{run_id}] Brief saved to Supabase successfully.")
                except Exception as e:
                    print(f"   [Thread:{run_id}] Failed to save brief to Supabase: {e}")
                    
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "complete", "data": {"final_report": final_report}})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve a minimal SVG favicon to prevent 404 errors in browser tabs."""
    from fastapi.responses import Response
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#171717"/>'
        '<circle cx="16" cy="16" r="6" fill="none" stroke="#50e3c2" stroke-width="2"/>'
        '<line x1="16" y1="4" x2="16" y2="10" stroke="#50e3c2" stroke-width="2" stroke-linecap="round"/>'
        '<line x1="24" y1="8" x2="21" y2="11" stroke="#50e3c2" stroke-width="2" stroke-linecap="round"/>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


# Patterns that identify trivial / non-researchable inputs
_TRIVIAL_PATTERN = re.compile(
    r"^\s*("
    r"hi+[!?.]?|hello+[!?.]?|hey+[!?.]?|howdy[!?.]?|yo+[!?.]?|sup[!?.]?"
    r"|good\s*(morning|afternoon|evening|night)[!?.]?"
    r"|how are you[!?.]?|what('?s| is) up[!?.]?|who are you[!?.]?"
    r"|thanks?[!?.]?|thank you[!?.]?|ok[!?.]?|okay[!?.]?|cool[!?.]?"
    r"|bye[!?.]?|goodbye[!?.]?|see you[!?.]?|help[!?.]?"
    r"|test[!?.]?|ping[!?.]?|check[!?.]?"
    r")\s*$",
    re.IGNORECASE,
)

# Endpoint to check email uniqueness
@app.get("/api/auth/check-email")
async def check_email(email: str):
    if not email or not email.strip():
        raise HTTPException(status_code=400, detail="Email is required")
    try:
        admin = get_admin_client()
        users = admin.auth.admin.list_users()
        email_clean = email.strip().lower()
        for u in users:
            if u.email and u.email.lower() == email_clean:
                return {"exists": True}
        return {"exists": False}
    except Exception as e:
        print(f"Error checking email availability: {e}")
        return {"exists": False}

# Endpoint to expose Supabase details to Frontend Auth forms
@app.get("/api/config")
async def get_web_config():
    return {
        "supabaseUrl": os.getenv("SUPABASE_URL"),
        "supabaseAnonKey": os.getenv("SUPABASE_ANON_KEY")
    }

@app.post("/api/research")
async def start_research(req: ResearchRequest, user: AuthenticatedUser = Depends(get_current_user)):
    topic_clean = req.topic.strip()

    if not topic_clean:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    # Block greetings and trivial inputs
    if _TRIVIAL_PATTERN.match(topic_clean):
        raise HTTPException(
            status_code=400,
            detail=(
                "Sentinel is a deep research platform and cannot respond to greetings or "
                "general conversation. Please enter a specific research topic (e.g. "
                "'AI chip supply chain risks', 'India semiconductor policy 2025')."
            )
        )

    # Block very short queries (< 10 chars)
    if len(topic_clean) < 10:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Your query is too short ({len(topic_clean)} characters). "
                "Please provide a specific, detailed research topic of at least 10 characters."
            )
        )

    run_id = req.run_id or f"{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:6]}"
    if run_id in active_cancellations:
        raise HTTPException(status_code=400, detail="Research run was cancelled by user.")

    try:
        # Create chat & user query message in DB to secure execution context
        chat_id = db_create_chat(user, topic_clean)
        db_save_message(user, chat_id, "user", topic_clean)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database initialization error: {e}")

    # Double-check for early cancellation after Supabase DB write completes
    if run_id in active_cancellations:
        raise HTTPException(status_code=400, detail="Research run was cancelled by user.")
    queue = asyncio.Queue()

    active_runs[run_id] = {
        "queue": queue,
        "status": "running",
        "topic": req.topic,
        "final_report": "",
        "chat_id": chat_id
    }
    # Initialize the resume event
    active_resumes[run_id] = threading.Event()

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Run graph stream inside a separate thread to prevent blocking the event loop
    loop.run_in_executor(
        executor,
        run_agent_in_thread,
        run_id,
        chat_id,
        req.topic,
        req.max_iterations,
        req.max_subagents,
        queue,
        loop
    )

    return {"run_id": run_id, "chat_id": chat_id}

@app.get("/api/stream/{run_id}")
async def stream_run(run_id: str, token: Optional[str] = Query(None)):
    if not token:
        raise HTTPException(status_code=401, detail="Token parameter is required for streaming")
    try:
        verify_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    if run_id not in active_runs:
        raise HTTPException(status_code=404, detail="Run ID not found")
        
    queue = active_runs[run_id]["queue"]
    
    async def event_generator():
        while True:
            try:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("complete", "cancelled"):
                    break
            except asyncio.CancelledError:
                break
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/research/cancel/{run_id}")
async def cancel_research(run_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    if run_id not in active_runs:
        raise HTTPException(status_code=404, detail="Run ID not found")
        
    chat_id = active_runs[run_id].get("chat_id")
    if chat_id:
        # Check if chat exists and belongs to the user
        res = user.client.table("chats").select("id").eq("id", chat_id).execute()
        if not res.data:
            raise HTTPException(status_code=403, detail="Not authorized to cancel this research")

    active_cancellations.add(run_id)
    # Wake up the paused thread if it is waiting
    resume_event = active_resumes.get(run_id)
    if resume_event:
        resume_event.set()
    return {"status": "cancelling"}

@app.post("/api/research/resume/{run_id}")
async def resume_research(run_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    if run_id not in active_runs:
        raise HTTPException(status_code=404, detail="Run ID not found")

    chat_id = active_runs[run_id].get("chat_id")
    if chat_id:
        # Check if chat exists and belongs to the user
        res = user.client.table("chats").select("id").eq("id", chat_id).execute()
        if not res.data:
            raise HTTPException(status_code=403, detail="Not authorized to resume this research")

    resume_event = active_resumes.get(run_id)
    if resume_event:
        resume_event.set()
        return {"status": "resuming"}
    return {"status": "not_paused"}


@app.get("/api/briefs")
async def get_briefs(user: AuthenticatedUser = Depends(get_current_user)):
    return db_list_briefs(user)

@app.get("/api/search")
async def search_chats(q: str, user: AuthenticatedUser = Depends(get_current_user)):
    query = q.strip()
    if not query:
        return []
    
    try:
        # 1. Search chats by title
        chats_res = user.client.table("chats")\
            .select("id, title, updated_at")\
            .ilike("title", f"%{query}%")\
            .order("updated_at", desc=True)\
            .execute()
        matched_chats = chats_res.data or []
        
        # 2. Search research briefs by content/title
        briefs_res = user.client.table("research_briefs")\
            .select("chat_id, title, content, filename")\
            .or_(f"content.ilike.%{query}%,title.ilike.%{query}%")\
            .execute()
        matched_briefs = briefs_res.data or []
        
        # 3. Search messages by content
        messages_res = user.client.table("messages")\
            .select("chat_id, content")\
            .ilike("content", f"%{query}%")\
            .execute()
        matched_messages = messages_res.data or []
        
        results_map = {}
        
        # Populate from matched chats
        for c in matched_chats:
            cid = c["id"]
            results_map[cid] = {
                "chat_id": cid,
                "filename": cid,
                "title": c["title"],
                "date": c["updated_at"],
                "snippet": "",
                "updated_at": c["updated_at"]
            }
            
        def extract_snippet(text, term):
            if not text:
                return ""
            idx = text.lower().find(term.lower())
            if idx == -1:
                return text[:100] + "..." if len(text) > 100 else text
            start = max(0, idx - 40)
            end = min(len(text), idx + len(term) + 60)
            snippet = text[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            return snippet
            
        # Populate/enhance from matched briefs
        for b in matched_briefs:
            cid = b["chat_id"]
            snippet = extract_snippet(b["content"], query)
            if cid in results_map:
                results_map[cid]["snippet"] = snippet
                results_map[cid]["filename"] = b["filename"]
            else:
                chat_detail = user.client.table("chats").select("title, updated_at").eq("id", cid).execute()
                if chat_detail.data:
                    c = chat_detail.data[0]
                    results_map[cid] = {
                        "chat_id": cid,
                        "filename": b["filename"],
                        "title": c["title"],
                        "date": c["updated_at"],
                        "snippet": snippet,
                        "updated_at": c["updated_at"]
                    }
                    
        # Populate/enhance from matched messages
        for m in matched_messages:
            cid = m["chat_id"]
            snippet = extract_snippet(m["content"], query)
            if cid in results_map:
                if not results_map[cid]["snippet"]:
                    results_map[cid]["snippet"] = snippet
            else:
                chat_detail = user.client.table("chats").select("title, updated_at").eq("id", cid).execute()
                if chat_detail.data:
                    c = chat_detail.data[0]
                    results_map[cid] = {
                        "chat_id": cid,
                        "filename": cid,
                        "title": c["title"],
                        "date": c["updated_at"],
                        "snippet": snippet,
                        "updated_at": c["updated_at"]
                    }
                    
        results_list = list(results_map.values())
        results_list.sort(key=lambda x: x["updated_at"], reverse=True)
        return results_list
    except Exception as e:
        print(f"Error searching chats: {e}")
        return []

@app.get("/api/briefs/{filename}")
async def get_brief_content(filename: str, user: AuthenticatedUser = Depends(get_current_user)):
    # Try fetching from DB first
    db_brief = db_get_brief_content(user, filename)
    if db_brief:
        return {
            "content": db_brief["content"],
            "chat_history": db_brief["chat_history"]
        }

    # Backward compatibility fallback to filesystem
    file_path = Path(Config.OUTPUT_DIR) / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Brief not found")
    try:
        content = file_path.read_text(encoding="utf-8")
        chat_history = []
        chat_path = file_path.with_suffix(".chat.json")
        if chat_path.exists() and chat_path.is_file():
            try:
                chat_history = json.loads(chat_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Error reading chat history: {e}")
        return {"content": content, "chat_history": chat_history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RenameRequest(BaseModel):
    new_title: str

@app.delete("/api/briefs/{filename}")
async def delete_brief(filename: str, user: AuthenticatedUser = Depends(get_current_user)):
    # Try DB deletion first
    is_uuid = re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", filename, re.IGNORECASE)
    if is_uuid:
        if db_delete_chat(user, filename):
            return {"status": "deleted"}
            
    # Try finding database match by filename
    brief_res = user.client.table("research_briefs").select("chat_id").eq("filename", filename).execute()
    if brief_res.data:
        chat_id = brief_res.data[0]["chat_id"]
        if db_delete_chat(user, chat_id):
            return {"status": "deleted"}

    # Fallback to filesystem deletion
    file_path = Path(Config.OUTPUT_DIR) / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Brief not found")
    try:
        file_path.unlink()
        chat_path = file_path.with_suffix(".chat.json")
        if chat_path.exists():
            chat_path.unlink()
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/briefs/{filename}")
async def rename_brief(filename: str, req: RenameRequest, user: AuthenticatedUser = Depends(get_current_user)):
    new_title = req.new_title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="New title cannot be empty")
        
    # Try DB renaming first
    is_uuid = re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", filename, re.IGNORECASE)
    if is_uuid:
        if db_rename_chat(user, filename, new_title):
            return {"status": "renamed", "new_filename": filename, "new_title": new_title}
            
    # Try finding database match by filename
    brief_res = user.client.table("research_briefs").select("chat_id").eq("filename", filename).execute()
    if brief_res.data:
        chat_id = brief_res.data[0]["chat_id"]
        if db_rename_chat(user, chat_id, new_title):
            return {"status": "renamed", "new_filename": filename, "new_title": new_title}
    
    # Fallback to filesystem renaming
    output_dir = Path(Config.OUTPUT_DIR)
    old_file_path = output_dir / filename
    if not old_file_path.exists() or not old_file_path.is_file():
        raise HTTPException(status_code=404, detail="Brief not found")
        
    clean_title = re.sub(r'[^a-zA-Z0-9\s-]', '', new_title).strip()
    clean_title = re.sub(r'[\s-]+', '-', clean_title).lower()
    new_filename = f"{clean_title}.md"
    new_file_path = output_dir / new_filename
    
    # Avoid collision
    if new_file_path.exists() and new_filename != filename:
        new_filename = f"{clean_title}-{uuid.uuid4().hex[:4]}.md"
        new_file_path = output_dir / new_filename

    try:
        content = old_file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        
        # Update title line
        title_updated = False
        for i, line in enumerate(lines[:5]):
            if line.startswith("# Intelligence Brief:"):
                lines[i] = f"# Intelligence Brief: {new_title}"
                title_updated = True
                break
            elif line.startswith("# Research Paper:"):
                lines[i] = f"# Research Paper: {new_title}"
                title_updated = True
                break
        
        if not title_updated and lines:
            if lines[0].startswith("# "):
                lines[0] = f"# {new_title}"
                
        new_content = "\n".join(lines)
        new_file_path.write_text(new_content, encoding="utf-8")
        
        if old_file_path != new_file_path:
            old_file_path.unlink()
            old_chat = old_file_path.with_suffix(".chat.json")
            if old_chat.exists():
                new_chat = new_file_path.with_suffix(".chat.json")
                old_chat.rename(new_chat)
            
        return {"status": "renamed", "new_filename": new_filename, "new_title": new_title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def find_relevant_brief_db(query: str, briefs: List[Dict]) -> Optional[str]:
    if not briefs:
        return None
        
    system_prompt = (
        "You are an intelligent routing assistant. Given a user query and a list of intelligence reports (filename and title), "
        "determine if any of the reports are relevant to the user query. "
        "Return ONLY the filename of the most relevant report (exactly as listed, e.g. '43c08bca-7389-491a-b620-6d4b4a17ef0d'), "
        "or return 'None' if no report is relevant.\n"
        "Do not include any explanation, quotes, or extra characters. Be concise and precise."
    )
    user_prompt = "Reports:\n"
    for b in briefs:
        user_prompt += f"- {b['filename']}: {b['title']}\n"
    user_prompt += f"\nQuery: {query}\n\nMost relevant filename (or 'None'):"
    
    try:
        from src.tools.llm import safe_llm_invoke
        from langchain_core.messages import SystemMessage, HumanMessage
        res = safe_llm_invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        ans = res.content.strip().replace("'", "").replace('"', "")
        if ans and ans != "None" and any(b['filename'] == ans for b in briefs):
            return ans
    except Exception as e:
        print(f"Error in find_relevant_brief_db: {e}")
    return None

# ── Memory constants ──────────────────────────────────────────────────────────
WINDOW_SIZE = 6          # Keep last N messages verbatim in every prompt
SUMMARY_THRESHOLD = 10   # Compress older turns once history exceeds this

def _non_brief_messages(chat_history: List[Dict]) -> List[Dict]:
    """Returns only user/assistant text turns (excludes brief cards)."""
    return [m for m in chat_history if m.get("type") != "brief"]

def build_context_for_prompt(
    chat_history: List[Dict],
    rolling_summary: str,
    brief_summary: str,
    brief_content: str,
) -> str:
    """
    Builds a token-efficient prompt context string using:
      1. Cached brief summary (or raw brief, hard-capped)
      2. Rolling summary of older turns
      3. Last WINDOW_SIZE messages verbatim
    """
    parts = []

    # 1. Research brief context
    if brief_summary:
        parts.append(f"[Research Brief Summary]\n{brief_summary}")
    elif brief_content:
        parts.append(f"[Research Brief]\n{brief_content[:6000]}")

    # 2. Rolling summary of older turns (compressed memory)
    if rolling_summary:
        parts.append(f"[Conversation Summary]\n{rolling_summary}")

    # 3. Recent verbatim window
    turns = _non_brief_messages(chat_history)
    window = turns[-WINDOW_SIZE:] if len(turns) > WINDOW_SIZE else turns
    if window:
        def _content_str(c):
            if isinstance(c, list):
                return " ".join(str(part.get("text", part) if isinstance(part, dict) else part) for part in c)
            return str(c)
        window_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {_content_str(m['content'])}"
            for m in window
        )
        parts.append(f"[Recent Messages]\n{window_text}")

    return "\n\n".join(parts)

async def maybe_compress_history(
    user: AuthenticatedUser,
    chat_id: str,
    chat_history: List[Dict],
    current_summary: str,
) -> str:
    """
    If the chat has exceeded SUMMARY_THRESHOLD non-brief turns, compress the
    oldest turns (everything outside the window) into a rolling summary and
    persist it.  Returns the (possibly updated) summary string.
    """
    from src.tools.llm import safe_llm_invoke
    from langchain_core.messages import SystemMessage, HumanMessage

    turns = _non_brief_messages(chat_history)
    if len(turns) <= SUMMARY_THRESHOLD:
        return current_summary

    # Only compress the portion that falls outside the kept window
    to_compress = turns[:-WINDOW_SIZE]
    if not to_compress:
        return current_summary

    def _content_str(c):
        if isinstance(c, list):
            return " ".join(str(part.get("text", part) if isinstance(part, dict) else part) for part in c)
        return str(c)
    history_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {_content_str(m['content'])}"
        for m in to_compress
    )
    prefix = f"Previous summary:\n{current_summary}\n\n" if current_summary else ""
    prompt = [
        SystemMessage(content=(
            "You are a conversation memory compressor. "
            "Produce a concise 3-5 sentence summary of the conversation below, "
            "preserving all key facts, decisions, and user preferences. "
            "Be dense and factual. Output only the summary text."
        )),
        HumanMessage(content=f"{prefix}New turns to compress:\n{history_text}"),
    ]
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, safe_llm_invoke, prompt)
        new_summary = res.content.strip()
        db_update_chat_memory(user, chat_id, summary=new_summary)
        return new_summary
    except Exception as e:
        print(f"[Memory] Compression failed: {e}")
        return current_summary

async def ensure_brief_summary(
    user: AuthenticatedUser,
    chat_id: str,
    brief_content: str,
    existing_brief_summary: str,
) -> str:
    """
    Lazily generates a compact brief summary the first time a Q&A is asked on
    a research chat.  Saves to DB and returns the summary.
    """
    if existing_brief_summary or not brief_content:
        return existing_brief_summary

    from src.tools.llm import safe_llm_invoke
    from langchain_core.messages import SystemMessage, HumanMessage

    prompt = [
        SystemMessage(content=(
            "You are a research analyst. Summarise the following intelligence report "
            "in 5-8 dense sentences covering its main findings, key entities, and "
            "conclusions. The summary will be used as context for follow-up Q&A."
        )),
        HumanMessage(content=brief_content[:8000]),
    ]
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, safe_llm_invoke, prompt)
        brief_summary = res.content.strip()
        db_update_chat_memory(user, chat_id, brief_summary=brief_summary)
        return brief_summary
    except Exception as e:
        print(f"[Memory] Brief summary generation failed: {e}")
        return ""

class ChatRequest(BaseModel):
    query: str
    brief_filename: Optional[str] = None
    new_session: Optional[bool] = False

def _build_system_prompt() -> str:
    return (
        "You are Sentinel, an advanced technology and geopolitical intelligence assistant.\n"
        "Your task is to answer the user's question directly, clearly, and analytically based on "
        "the provided report context where possible. If the context does not contain the answer, "
        "use your general knowledge to answer, but clearly state what is from the report and what "
        "is general knowledge. Use a professional, neutral tone. Format your response cleanly in markdown. "
        "Do not invent statistics that are not present in the context; if using general knowledge, specify "
        "that it is standard industry intelligence.\n\n"
        "DIAGRAMS: If the user asks you to draw, visualize, or diagram something, produce a Mermaid "
        "diagram inside a fenced code block with the language identifier 'mermaid'. "
        "Use graph TD for flows and hierarchies, sequenceDiagram for timelines, and mindmap for "
        "concept/actor maps. Keep diagrams under 12 nodes."
        "add a diagram when it clearly adds more value than prose."
    )

async def _resolve_chat_context(req: "ChatRequest", user: AuthenticatedUser):
    """
    Shared context-resolution logic used by both /api/chat and /api/chat/stream.
    Returns (target_filename, matched_filename, db_brief, context, chat_history,
             chat_id, rolling_summary, brief_summary).
    """
    matched_filename = None
    target_filename = req.brief_filename
    db_brief = None

    if target_filename:
        db_brief = db_get_brief_content(user, target_filename)

    if not db_brief and not target_filename and not req.new_session:
        db_briefs = db_list_briefs(user)
        matched_filename = find_relevant_brief_db(req.query, db_briefs)
        if matched_filename:
            target_filename = matched_filename
            db_brief = db_get_brief_content(user, target_filename)

    context = ""
    chat_history: List[Dict] = []
    chat_id: Optional[str] = None
    rolling_summary = ""
    brief_summary = ""

    if db_brief:
        context = db_brief["content"]
        chat_history = db_brief["chat_history"]
        chat_id = db_brief["chat_id"]
        rolling_summary = db_brief.get("summary", "")
        brief_summary = db_brief.get("brief_summary", "")
    elif target_filename:
        brief_path = Path(Config.OUTPUT_DIR) / target_filename
        if brief_path.exists():
            try:
                context = brief_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"Error reading local brief: {e}")
            chat_path = brief_path.with_suffix(".chat.json")
            if chat_path.exists():
                try:
                    chat_history = json.loads(chat_path.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"Error reading local chat history: {e}")

    return target_filename, matched_filename, db_brief, context, chat_history, chat_id, rolling_summary, brief_summary

async def _save_qa_to_db(
    user: AuthenticatedUser,
    req: "ChatRequest",
    target_filename: Optional[str],
    db_brief: Optional[Dict],
    context: str,
    chat_history: List[Dict],
    chat_id: Optional[str],
    assistant_response: str,
) -> tuple:
    """
    Persists user question + assistant answer and returns (chat_id, new_filename).
    For brand-new standalone sessions returns a new chat_id as filename.
    """
    if chat_id:
        db_save_message(user, chat_id, "user", req.query)
        db_save_message(user, chat_id, "assistant", assistant_response)
        user.client.table("chats").update({"updated_at": "now()"}).eq("id", chat_id).execute()
        return chat_id, None
    elif target_filename:
        brief_path = Path(Config.OUTPUT_DIR) / target_filename
        chat_path = brief_path.with_suffix(".chat.json")
        if not chat_history:
            title = target_filename.replace(".md", "").replace("-", " ").title()
            for line in context.splitlines()[:5]:
                if line.startswith("# Intelligence Brief:"):
                    title = line.replace("# Intelligence Brief:", "").strip()
                elif line.startswith("# Research Paper:"):
                    title = line.replace("# Research Paper:", "").strip()
            chat_history.append({"role": "user", "content": title})
            date_str = ""
            for line in context.splitlines()[:5]:
                if "Generated:" in line:
                    date_str = line.split("Generated:")[1].split("|")[0].strip().strip("* ")
            if not date_str:
                date_str = datetime.datetime.fromtimestamp(brief_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M UTC")
            chat_history.append({"role": "assistant", "type": "brief", "content": context, "date": date_str})
        chat_history.append({"role": "user", "content": req.query})
        chat_history.append({"role": "assistant", "content": assistant_response})
        chat_path.write_text(json.dumps(chat_history, indent=2, ensure_ascii=False), encoding="utf-8")
        return None, target_filename
    else:
        db_title = req.query[:40]
        title_match = re.search(r'<title>([\s\S]*?)</title>', assistant_response, re.IGNORECASE)
        if title_match:
            db_title = title_match.group(1).strip()
        new_chat_id = db_create_chat(user, db_title)
        db_save_message(user, new_chat_id, "user", req.query)
        db_save_message(user, new_chat_id, "assistant", assistant_response)
        return new_chat_id, None

@app.post("/api/chat")
async def chat_handler(req: ChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    from src.tools.llm import safe_llm_invoke
    from langchain_core.messages import SystemMessage, HumanMessage

    (
        target_filename, matched_filename, db_brief,
        context, chat_history, chat_id,
        rolling_summary, brief_summary
    ) = await _resolve_chat_context(req, user)

    # Lazily generate brief summary (one-time cost per research chat)
    if chat_id and context and not brief_summary:
        brief_summary = await ensure_brief_summary(user, chat_id, context, brief_summary)

    # Compress history if it has grown beyond the threshold
    if chat_id and chat_history:
        rolling_summary = await maybe_compress_history(user, chat_id, chat_history, rolling_summary)

    prompt_context = build_context_for_prompt(chat_history, rolling_summary, brief_summary, context)

    user_prompt = f"{prompt_context}\n\nUser Question: {req.query}" if prompt_context else f"User Question: {req.query}"

    try:
        loop = asyncio.get_running_loop()
        system_prompt = _build_system_prompt()
        if not chat_id:
            system_prompt += (
                "\n\nCRITICAL OUTPUT REQUIREMENT FOR THE FIRST MESSAGE IN THIS CHAT:\n"
                "At the very beginning of your response, prepend a short, professional, topic-specific title "
                "for this chat session enclosed inside <title> and </title> tags, followed by two newlines, "
                "then start your actual response. The title should be 3-6 words long and capture the core topic "
                "of the user's query. Example: <title>AI Hardware Supply Chain Vulnerabilities</title>\n"
                "Do not use generic titles like 'Research Query' or the exact user query. "
                "This title tag must only be included at the very beginning of the response."
            )
        res = await loop.run_in_executor(
            None, safe_llm_invoke,
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        assistant_response = res.content

        new_chat_id, _ = await _save_qa_to_db(
            user, req, target_filename, db_brief, context, chat_history, chat_id, assistant_response
        )

        if new_chat_id and not chat_id:
            return {"response": assistant_response, "filename": new_chat_id}
        return {"response": assistant_response, "matched_filename": target_filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stream")
async def chat_stream_handler(req: ChatRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Streaming SSE endpoint — yields tokens as they arrive from the LLM."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    from src.tools.llm import make_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    (
        target_filename, matched_filename, db_brief,
        context, chat_history, chat_id,
        rolling_summary, brief_summary
    ) = await _resolve_chat_context(req, user)

    # Lazily generate brief summary (one-time cost)
    if chat_id and context and not brief_summary:
        brief_summary = await ensure_brief_summary(user, chat_id, context, brief_summary)

    # Compress old history if needed
    if chat_id and chat_history:
        rolling_summary = await maybe_compress_history(user, chat_id, chat_history, rolling_summary)

    prompt_context = build_context_for_prompt(chat_history, rolling_summary, brief_summary, context)
    user_prompt = f"{prompt_context}\n\nUser Question: {req.query}" if prompt_context else f"User Question: {req.query}"

    system_prompt = _build_system_prompt()
    if not chat_id:
        system_prompt += (
            "\n\nCRITICAL OUTPUT REQUIREMENT FOR THE FIRST MESSAGE IN THIS CHAT:\n"
            "At the very beginning of your response, prepend a short, professional, topic-specific title "
            "for this chat session enclosed inside <title> and </title> tags, followed by two newlines, "
            "then start your actual response. The title should be 3-6 words long and capture the core topic "
            "of the user's query. Example: <title>AI Hardware Supply Chain Vulnerabilities</title>\n"
            "Do not use generic titles like 'Research Query' or the exact user query. "
            "This title tag must only be included at the very beginning of the response."
        )

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

    async def event_generator():
        full_response = ""
        try:
            llm = make_llm()
            async for chunk in llm.astream(messages):
                token = chunk.content
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

            # Stream complete — save to DB
            new_chat_id, _ = await _save_qa_to_db(
                user, req, target_filename, db_brief, context,
                chat_history, chat_id, full_response
            )
            result_filename = new_chat_id if (new_chat_id and not chat_id) else target_filename
            yield f"data: {json.dumps({'done': True, 'filename': result_filename, 'is_new': bool(new_chat_id and not chat_id)})}\n\n"

        except asyncio.CancelledError:
            # Client aborted — discard partial response, do not save
            pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Mount static folder
static_path = Path(__file__).resolve().parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
