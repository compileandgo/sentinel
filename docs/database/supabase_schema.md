# Supabase Database Schema

This document details the PostgreSQL database tables, vector indexes, and Row Level Security (RLS) policies configured in Supabase.

---

## Database Setup

* **Database Engine**: PostgreSQL 15+.
* **Extensions Used**: `uuid-ossp`, `pgcrypto`, `vector` (`pgvector`).
* **Python SDK**: `supabase` (`supabase-py`).

---

## Table Definitions

### 1. `chats` Table
Stores chat session metadata for each user:
```sql
CREATE TABLE public.chats (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 summary TEXT,
 brief_summary TEXT,
 created_at TIMESTAMPTZ DEFAULT now(),
 updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_chats_user_id ON public.chats(user_id);
```

### 2. `messages` Table
Stores individual user and assistant messages in a chat:
```sql
CREATE TABLE public.messages (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 chat_id UUID NOT NULL REFERENCES public.chats(id) ON DELETE CASCADE,
 user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
 content TEXT NOT NULL,
 type TEXT DEFAULT 'text',
 created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_chat_id ON public.messages(chat_id);
```

### 3. `research_briefs` Table
Stores generated final research reports:
```sql
CREATE TABLE public.research_briefs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 chat_id UUID REFERENCES public.chats(id) ON DELETE SET NULL,
 filename TEXT NOT NULL UNIQUE,
 topic TEXT NOT NULL,
 content TEXT NOT NULL,
 created_at TIMESTAMPTZ DEFAULT now()
);
```

### 4. `research_chunks` Table
Stores parent and child text chunks for RAG search:
```sql
CREATE TABLE public.research_chunks (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 parent_id UUID REFERENCES public.research_chunks(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 chunk_text TEXT NOT NULL,
 metadata JSONB DEFAULT '{}'::jsonb,
 fts_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED,
 created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_chunks_fts ON public.research_chunks USING GIN(fts_vector);
```

### 5. `qa_cache` Table (Vector Semantic Cache)
Stores Q&A query embeddings for fast vector similarity caching:
```sql
CREATE TABLE public.qa_cache (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 chat_id TEXT NOT NULL,
 query_text TEXT NOT NULL,
 query_embedding JSONB NOT NULL,
 response_text TEXT NOT NULL,
 created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_qa_cache_chat_id ON public.qa_cache(chat_id);
```

---

## Row Level Security (RLS)

All tables enforcing user isolation enable Supabase RLS:

```sql
ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only read their own chats"
 ON public.chats FOR SELECT
 USING (auth.uid() = user_id);

CREATE POLICY "Users can only insert their own chats"
 ON public.chats FOR INSERT
 WITH CHECK (auth.uid() = user_id);
```
