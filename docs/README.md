# Sentinel Technical Documentation

Sentinel is an open-source, enterprise-grade deep research and geopolitical intelligence platform. It automates long-form technical research, multi-agent intelligence gathering, hybrid vector/keyword retrieval, and real-time streaming output.

---

## 🗺️ Documentation Directory

### 1. Architecture
* **[System Overview](architecture/overview.md)**: Overall architecture, request lifecycle, dataflow, and design choices.
* **[LangGraph Multi-Agent Workflows](architecture/agent_graph.md)**: StateGraph implementation, node execution order, supervisor agent, subagents, and cross-examiners.

### 2. Backend Engine
* **[FastAPI & SSE Streaming](backend/fastapi_app.md)**: FastAPI endpoints, thread executor isolation, JWT authentication, and Server-Sent Events (SSE).
* **[Redis State Manager & Pub/Sub](backend/redis_state.md)**: Upstash Redis integration, distributed state storage, Redis Pub/Sub, and cancellation flags.
* **[Sliding-Window Rate Limiting](backend/rate_limiting.md)**: Redis Sorted Set (ZSET) rate limiter implementation.

### 3. Retrieval-Augmented Generation (RAG)
* **[RAG Pipeline Overview](rag/pipeline_overview.md)**: Chunking strategies, embedding models, and context assembly.
* **[Hybrid Search & Reciprocal Rank Fusion (RRF)](rag/hybrid_search_rrf.md)**: 3-channel retrieval (Pinecone Dense + Local BM25 + Supabase FTS) and RRF fusion math.
* **[Semantic Q&A Caching](rag/semantic_caching.md)**: Vector similarity cache in Supabase using BGE embeddings.

### 4. Voice Processing
* **[Voice STT & TTS Engine](voice/voice_stt_tts.md)**: Groq Whisper-large-v3 Speech-to-Text, WebSpeech API, 7s VAD silence detection, and SpeechSynthesis TTS.

### 5. Deployment & Infrastructure
* **[AWS EC2 & Nginx Deployment](deployment/aws_ec2_setup.md)**: Ubuntu 26.04 setup, 2GB swap file creation, Nginx reverse proxy configuration, and systemd service management.
* **[10,000 Concurrent User Scaling Blueprint](deployment/scaling_10k.md)**: Load balancing (AWS ALB), Auto Scaling Groups, Celery task queues, and pgBouncer database pooling.

### 6. Database & Integrations
* **[Supabase Database Schema](database/supabase_schema.md)**: Table definitions, indexes, vector embeddings, and Row Level Security (RLS).
* **[External Services & LLM Key Pools](tools/external_integrations.md)**: Gemini, Groq, Tavily, GDELT, and API key rotation with self-healing failover.

### 7. Development Guide
* **[Developer Setup & Fitting Encoders](developer/setup_guide.md)**: Local installation, environment variables, fitting BM25 encoders, and running unit/integration tests.
