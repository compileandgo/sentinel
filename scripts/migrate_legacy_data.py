import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Adjust path to import src.web.db
sys.path.append(str(Path(__file__).parent.parent))

from src.web.db import get_admin_client

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_legacy_data.py <user_email>")
        sys.exit(1)
        
    email = sys.argv[1]
    admin = get_admin_client()
    
    # 1. Fetch user ID from auth.users via Auth Admin API
    print(f"Fetching user ID for {email}...")
    try:
        users_res = admin.auth.admin.list_users()
        user = next((u for u in users_res if u.email == email), None)
        if not user:
            print(f"Error: User with email {email} not found in Supabase Auth.")
            sys.exit(1)
        user_id = user.id
        print(f"Found user ID: {user_id}")
    except Exception as e:
        print(f"Failed to query auth.users: {e}")
        sys.exit(1)
        
    output_dir = Path("output")
    if not output_dir.exists():
        print("No output directory found.")
        sys.exit(0)
        
    print("Reading legacy files from output/...")
    
    # Track which markdown files have been processed to handle standalone files later
    processed_md = set()
    
    # 2. Process chat JSON files
    for chat_file in output_dir.glob("*.chat.json"):
        print(f"\nProcessing chat history: {chat_file.name}")
        try:
            with open(chat_file, "r", encoding="utf-8") as f:
                chat_history = json.load(f)
        except Exception as e:
            print(f"  Error reading {chat_file.name}: {e}")
            continue
            
        if not chat_history:
            print("  Empty chat history, skipping.")
            continue
            
        # Determine title
        first_user_msg = next((m["content"] for m in chat_history if m["role"] == "user"), None)
        title = first_user_msg or chat_file.stem.replace("chat-", "").replace("-", " ")
        if title.startswith("Chat: "):
            title = title[6:]
        if len(title) > 80:
            title = title[:77] + "..."
            
        # Create chat
        try:
            chat_res = admin.table("chats").insert({
                "user_id": user_id,
                "title": title
            }).execute()
            if not chat_res.data:
                raise Exception("Failed to insert chat row")
            chat_id = chat_res.data[0]["id"]
            print(f"  Created chat database entry: {chat_id}")
        except Exception as e:
            print(f"  Error creating chat entry: {e}")
            continue
            
        # Insert messages
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content")
            msg_type = msg.get("type", "text")
            
            # Skip any malformed messages
            if not role or not content:
                continue
                
            try:
                admin.table("messages").insert({
                    "chat_id": chat_id,
                    "role": role,
                    "content": content,
                    "type": msg_type
                }).execute()
            except Exception as e:
                print(f"    Error saving message: {e}")
                
        # Check for matching markdown brief
        # e.g., chat-who-is-the-prime-minister-of-india-6718.chat.json -> chat-who-is-the-prime-minister-of-india-6718.md
        brief_md_file = output_dir / (chat_file.stem + ".md")
        if brief_md_file.exists():
            print(f"  Found matching report brief: {brief_md_file.name}")
            try:
                with open(brief_md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()
                filename = brief_md_file.name
                
                admin.table("research_briefs").insert({
                    "chat_id": chat_id,
                    "title": title,
                    "content": md_content,
                    "filename": filename
                }).execute()
                print(f"    Successfully stored brief content.")
                processed_md.add(brief_md_file.name)
            except Exception as e:
                print(f"    Error saving brief content: {e}")
                
    # 3. Process standalone markdown briefs
    for md_file in output_dir.glob("*.md"):
        if md_file.name in processed_md or md_file.parent.name == "subagents":
            continue
            
        # If it's a chat report that had no JSON, or a normal standalone report
        print(f"\nProcessing standalone brief: {md_file.name}")
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                md_content = f.read()
        except Exception as e:
            print(f"  Error reading {md_file.name}: {e}")
            continue
            
        title = md_file.stem.replace("-", " ").title()
        
        # Create a chat for it
        try:
            chat_res = admin.table("chats").insert({
                "user_id": user_id,
                "title": title
            }).execute()
            if not chat_res.data:
                raise Exception("Failed to insert chat row")
            chat_id = chat_res.data[0]["id"]
            print(f"  Created chat entry: {chat_id}")
        except Exception as e:
            print(f"  Error creating chat entry: {e}")
            continue
            
        # Insert initial user message and assistant brief response
        try:
            admin.table("messages").insert({
                "chat_id": chat_id,
                "role": "user",
                "content": f"Research on: {title}"
            }).execute()
            
            admin.tableStatus("messages").insert({
                "chat_id": chat_id,
                "role": "assistant",
                "content": f"Here is the synthesized intelligence report on {title}.",
                "type": "brief"
            }).execute()
        except Exception as e:
            print(f"  Error inserting placeholder messages: {e}")
            
        # Save research brief
        try:
            admin.table("research_briefs").insert({
                "chat_id": chat_id,
                "title": title,
                "content": md_content,
                "filename": md_file.name
            }).execute()
            print(f"  Successfully stored standalone brief content.")
        except Exception as e:
            print(f"  Error saving brief content: {e}")
            
    print("\nData migration completed successfully!")

if __name__ == "__main__":
    main()
