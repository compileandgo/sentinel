import os
import re
from typing import Dict, List, Optional
from supabase import create_client, Client
import jwt

JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

class AuthenticatedUser:
    def __init__(self, user_id: str, email: str, client: Client):
        self.id = user_id
        self.email = email
        self.client = client

    @property
    def user_id(self) -> str:
        return self.id

def get_user_client(token: str) -> Client:
    """Returns a Supabase client scoped to the user's JWT token to enforce RLS."""
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(token)
    return client

def get_admin_client() -> Client:
    """Returns a Supabase client with service role admin privileges (for background tasks)."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def verify_token(token: str) -> dict:
    """Validates a Supabase JWT token using the Supabase auth API."""
    try:
        temp_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        res = temp_client.auth.get_user(token)
        user = res.user
        if not user:
            raise ValueError("No user found for this token")
        return {
            "sub": user.id,
            "email": user.email
        }
    except Exception as e:
        raise ValueError(f"Invalid token: {str(e)}")

# DB Operations

def db_list_briefs(user: AuthenticatedUser) -> List[Dict]:
    """Lists all chats and briefs belonging to the user from the database."""
    try:
        # Select user's chats
        chats_res = user.client.table("chats").select("id, title, created_at, updated_at").order("updated_at", desc=True).execute()
        chats = chats_res.data or []
        
        # Select briefs for those chats
        briefs_res = user.client.table("research_briefs").select("chat_id, filename, title, created_at, content").execute()
        briefs_by_chat = {b["chat_id"]: b for b in (briefs_res.data or [])}
        
        result = []
        for chat in chats:
            chat_id = chat["id"]
            brief = briefs_by_chat.get(chat_id)
            
            # Map database keys to frontend schema
            result.append({
                "filename": brief["filename"] if brief else chat_id,
                "title": chat["title"],
                "date": chat["updated_at"][:16].replace("T", " ") + " UTC",
                "run_id": chat_id,
                "size": len(brief["content"]) if brief else 0
            })
        return result
    except Exception as e:
        print(f"Error listing database briefs: {e}")
        return []

def db_get_brief_content(user: AuthenticatedUser, filename: str) -> Optional[Dict]:
    """Retrieves chat history, brief content, and memory fields from the database."""
    # Check if filename is a UUID (chat_id) or actual filename
    chat_id = None
    is_uuid = re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", filename, re.IGNORECASE)
    
    try:
        if is_uuid:
            chat_id = filename
            brief_res = user.client.table("research_briefs").select("content").eq("chat_id", chat_id).execute()
        else:
            brief_res = user.client.table("research_briefs").select("chat_id, content").eq("filename", filename).execute()
            if brief_res.data:
                chat_id = brief_res.data[0]["chat_id"]
                
        if not chat_id:
            return None
            
        # Get brief content
        content = ""
        if brief_res.data:
            content = brief_res.data[0]["content"]

        # Get chat summary/brief_summary memory fields
        chat_meta = user.client.table("chats").select("summary, brief_summary").eq("id", chat_id).execute()
        summary = ""
        brief_summary = ""
        if chat_meta.data:
            summary = chat_meta.data[0].get("summary") or ""
            brief_summary = chat_meta.data[0].get("brief_summary") or ""
            
        # Get chat messages
        messages_res = user.client.table("messages").select("role, content, type, created_at").eq("chat_id", chat_id).order("created_at", desc=False).execute()
        messages = messages_res.data or []
        
        chat_history = []
        for msg in messages:
            raw_content = msg["content"]
            # Supabase may return jsonb columns as a list — flatten to plain string
            if isinstance(raw_content, list):
                raw_content = " ".join(
                    str(part.get("text", part) if isinstance(part, dict) else part)
                    for part in raw_content
                )
            elif not isinstance(raw_content, str):
                raw_content = str(raw_content)

            msg_data = {
                "role": msg["role"],
                "content": raw_content
            }
            if msg.get("type") and msg["type"] != "text":
                msg_data["type"] = msg["type"]
            # Convert date to standard display format
            msg_data["date"] = msg["created_at"][:16].replace("T", " ") + " UTC"
            chat_history.append(msg_data)
            
        return {
            "content": content,
            "chat_history": chat_history,
            "chat_id": chat_id,
            "summary": summary,
            "brief_summary": brief_summary,
        }
    except Exception as e:
        print(f"Error fetching brief content from DB: {e}")
        return None

def db_create_chat(user: AuthenticatedUser, title: str) -> str:
    """Creates a new chat session for the user."""
    res = user.client.table("chats").insert({
        "title": title,
        "user_id": user.id
    }).execute()
    if not res.data:
        raise Exception("Failed to create chat in database")
    return res.data[0]["id"]

def db_update_chat_memory(
    user: AuthenticatedUser,
    chat_id: str,
    summary: Optional[str] = None,
    brief_summary: Optional[str] = None
) -> None:
    """Persists updated memory fields (rolling summary / brief summary) for a chat."""
    payload: Dict = {}
    if summary is not None:
        payload["summary"] = summary
    if brief_summary is not None:
        payload["brief_summary"] = brief_summary
    if payload:
        try:
            user.client.table("chats").update(payload).eq("id", chat_id).execute()
        except Exception as e:
            print(f"Error updating chat memory for {chat_id}: {e}")

def db_save_message(user: AuthenticatedUser, chat_id: str, role: str, content: str, msg_type: str = "text") -> None:
    """Saves a message to the database."""
    user.client.table("messages").insert({
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "type": msg_type
    }).execute()

def db_save_message_admin(chat_id: str, role: str, content: str, msg_type: str = "text") -> None:
    """Saves a message using the admin client (bypass user context, for background jobs)."""
    admin = get_admin_client()
    admin.table("messages").insert({
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "type": msg_type
    }).execute()

def db_save_brief_admin(chat_id: str, title: str, content: str, filename: str) -> None:
    """Saves a brief using the admin client (bypass user context, for background jobs)."""
    admin = get_admin_client()
    # Check if brief already exists
    existing = admin.table("research_briefs").select("id").eq("chat_id", chat_id).execute()
    if existing.data:
        admin.table("research_briefs").update({
            "title": title,
            "content": content,
            "filename": filename,
            "updated_at": "now()"
        }).eq("chat_id", chat_id).execute()
    else:
        admin.table("research_briefs").insert({
            "chat_id": chat_id,
            "title": title,
            "content": content,
            "filename": filename
        }).execute()
        
    # Also update the chat table's title and updated_at timestamp to bubble it up in recent list
    admin.table("chats").update({"title": title, "updated_at": "now()"}).eq("id", chat_id).execute()

def db_delete_chat(user: AuthenticatedUser, chat_id: str) -> bool:
    """Deletes a chat and all cascading records (messages/briefs)."""
    try:
        res = user.client.table("chats").delete().eq("id", chat_id).execute()
        return len(res.data) > 0
    except Exception as e:
        print(f"Error deleting chat {chat_id}: {e}")
        return False

def db_rename_chat(user: AuthenticatedUser, chat_id: str, new_title: str) -> bool:
    """Renames a chat title in both chats and research_briefs tables."""
    try:
        # Update chats table
        chats_res = user.client.table("chats").update({"title": new_title}).eq("id", chat_id).execute()
        if not chats_res.data:
            return False
            
        # Update research_briefs table (if exists)
        user.client.table("research_briefs").update({"title": new_title}).eq("chat_id", chat_id).execute()
        return True
    except Exception as e:
        print(f"Error renaming chat {chat_id}: {e}")
        return False
