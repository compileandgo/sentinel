# Sentinel Presentation Slides Content

This document contains slide-by-slide layouts, speaking notes, and technical concepts to be parsed by presentation generation engines or AI slide creators.

---

## Slide 1: Title Slide
* **Slide Layout**: Title and Subtitle with Presenter Details
* **Slide Title**: Sentinel
* **Subtitle**: Distributed Multi-Agent Geopolitical Intelligence and Research Platform
* **Technical Keywords**: LangGraph Cyclic Workflows, Hybrid RAG with Reciprocal Rank Fusion, Vector Semantic Caching, Distributed Redis State Manager.

---

## Slide 2: The Problem Space (The Why)
* **Slide Layout**: Two-column (Current Limitations vs. Real-World Impact)
* **Column 1: Technical Limitations of Standard LLM Workflows**:
  * Linear Prompt Chains: Unable to self-correct, loop, or pause for human feedback.
  * Factual Hallucinations: No cross-model verification or factual validation before compiling reports.
  * Ingestion Constraints: Standard document parsing scrambles multi-column layouts, tables, and scanned texts, polluting vector database embeddings.
  * API Overhead: Repeatedly querying LLMs for similar or identical user queries incurs significant latency and financial costs.
* **Column 2: Real-World Geopolitical Research Needs**:
  * Credibility Scoring: Geopolitical news streams are highly polarized and require automated bias tracking.
  * Temporal Chronology: Reports must follow strict chronological timelines to map chain-of-event logic.
  * Verifiable Citations: Every single factual claim must map back to an exact source URL or chunk ID.

---

## Slide 3: System Architecture (The Three-Pillar Topology)
* **Slide Title**: System Architecture
* **Slide Layout**: Three Columns (Web/App, State/Event, Data/RAG)
* **Column 1: Web & Application Layer (FastAPI & Nginx)**:
  * Nginx acts as the entry point, configured with proxy buffering disabled to allow unbuffered, real-time Server-Sent Events (SSE).
  * FastAPI runs the async request handlers. Heavy agent graph executions are offloaded to a background ThreadPoolExecutor to prevent blocking the main asyncio event loop.
* **Column 2: State & Event Broker Layer (Upstash Redis)**:
  * Run states are stored in distributed Redis hashes (HSET) with a 24-hour TTL.
  * Live logs, status updates, and plan_ready prompts are published to Redis Pub/Sub channels (sse:run_id).
  * Rate-limiting and run cancellation states are tracked globally across nodes.
* **Column 3: Data & Storage Layer (Supabase & Pinecone)**:
  * Supabase manages user authentication, relational schemas (chats, messages, reports), and Postgres Full-Text Search.
  * Pinecone hosts the 768-dimensional dense vector embeddings.

---

## Slide 4: Multi-Agent Orchestration (LangGraph)
* **Slide Title**: LangGraph State Machine
* **Slide Layout**: Diagram Description and Technical Rationale
* **Core Concepts**:
  * Shared State (ResearchState): A central TypedDict container passed, updated, and returned by every node in the graph. Contains plan paths, raw intel lists, bias matrices, timelines, and final reports.
  * Cyclic Transitions: Unlike static chains, LangGraph allows conditional routing, letting nodes loop back to previous states if evaluation thresholds are not met.
  * Process Isolation: LangGraph nodes run in isolated context variables, permitting concurrent task execution.

---

## Slide 5: Node-by-Node Execution - Phase 1: Planning and Human Gate
* **Slide Title**: Phase 1: Planning & Human-in-the-Loop
* **Slide Layout**: Left (lead_researcher Node) / Right (Human Pause Gate)
* **Left: lead_researcher Node**:
  * Evaluates query intent and classifies the domain (Geopolitical, Economic, Scientific).
  * Formulates a structured research plan breaking down the query into distinct sub-tasks.
  * Outputs a plan document (research_plan.md) and publishes a plan_ready event.
* **Right: Human-in-the-Loop Gate**:
  * The execution thread enters a blocking state (waiting on a threading.Event object).
  * Avoids wasting API calls or compute resources on incorrect search paths.
  * Resume: User sends POST /api/research/resume, which sets the event flag, updates the Redis approval key, and triggers the next graph node.

---

## Slide 6: Node-by-Node Execution - Phase 2: Parallel Retrieval
* **Slide Title**: Phase 2: Concurrent Multi-Channel Retrieval
* **Slide Layout**: Focus on spawn_subagents Node
* **Parallel Execution Engine**:
  * Subagents are executed concurrently using a ThreadPoolExecutor.
  * Prevents network I/O bottlenecks by fanning out web queries simultaneously.
* **Retrieval Sources Per Subagent**:
  * Channel 1 (Internal RAG): Queries the Pinecone dense vector index and local BM25.
  * Channel 2 (Tavily AI Search): Fetches live web pages, extracts clean text snippets, and compiles source URLs.
  * Channel 3 (GDELT Project API): Queries real-time global news database API for geopolitical context.

---

## Slide 7: Node-by-Node Execution - Phase 3: Verification & Output
* **Slide Title**: Phase 3: Verification, Chronology, & Synthesis
* **Slide Layout**: Three Columns (Cross-Examiner, Timeline, Evaluation)
* **Column 1: cross_examiner Node (Consensus Check)**:
  * Evaluates raw data using dual-model validation (Gemini 1.5/2.0 vs Llama-3.3 on Groq).
  * Computes model agreement scores and flags direct factual contradictions.
  * Scores source credibility and identifies potential media bias.
* **Column 2: timeline_compiler & eval_report Nodes**:
  * Chronology Compiler: Parses text chunks, extracts date entities, and orders milestones chronologically.
  * Sufficiency Evaluator: Compares gathered data against the initial research plan. If data is incomplete, it loops back to Lead Researcher. If complete, it routes to the Synthesizer.
* **Column 3: synthesizer Node (Report Output)**:
  * Compiles executive summary, bias scores, chronological timeline, and raw findings into a Markdown report.
  * Appends strict inline Markdown citations linking to verified URLs.

---

## Slide 8: The RAG Pipeline - Multi-Channel Search
* **Slide Title**: Three-Channel Hybrid Search
* **Slide Layout**: Grid showing Search Channels and Embeddings
* **Embedding Model (FastEmbed BGE)**:
  * Local CPU execution using ONNX-quantized BAAI/bge-base-en-v1.5.
  * Generates 768-dimensional dense vector representations.
* **Search Channel 1: Dense Vector Retrieval (Pinecone)**:
  * Queries Pinecone index using cosine similarity matching. Optimal for conceptual search.
* **Search Channel 2: Local Sparse Keyword Search (BM25)**:
  * Local Pinecone-Text BM25Encoder fit against project corpus. Scores exact query keyword frequency.
* **Search Channel 3: Database Full-Text Search (Supabase FTS)**:
  * Runs Postgres tsquery using GIN index. Optimal for exact acronyms, codes, and names.

---

## Slide 9: The RAG Pipeline - Reciprocal Rank Fusion & Chunking
* **Slide Title**: RRF Fusion and Document Chunking
* **Slide Layout**: Technical Formula and Chunk Strategy
* **Reciprocal Rank Fusion (RRF) Formula**:
  * Math: RRF_Score(d) = Sum_{m in M} (1 / (k + r_m(d)))
  * Fuses Dense, BM25, and FTS rankings. Uses smoothing constant k=60. Fuses candidate documents without needing score normalization.
* **Parent-Child Chunking Strategy**:
  * Problem: Small chunks retrieve best, but lack context for LLM synthesis. Large chunks preserve context but dilute vector query math.
  * Solution: Child chunks (200 words) are embedded and stored in Pinecone. Parent chunks (1000 words) are stored in Supabase.
  * Execution: RAG searches child chunks, resolves their parent IDs, and returns the expanded Parent Chunk to the LLM.

---

## Slide 10: Performance Optimization - Semantic Cache
* **Slide Title**: Vector Semantic Q&A Cache
* **Slide Layout**: Math and Benchmarks Comparison
* **Cosine Similarity Thresholding**:
  * Math: Cosine_Similarity(a, b) = (a . b) / (||a|| ||b||)
  * Logic: incoming query is embedded using BGE. We compute cosine similarity against previous queries in Supabase.
  * Match: If similarity is greater than or equal to 0.90, the system bypasses LLM and web search entirely, returning the cached response.
* **Performance Benchmarks**:
  * Cache Miss (Fresh Search + LLM): ~16,550 ms response time.
  * Cache Hit (Vector Semantic Match): ~1,130 ms response time.
  * Impact: 14.6x speedup, 100% LLM token savings, 95% CPU load reduction.

---

## Slide 11: Enterprise Voice Engine
* **Slide Title**: Speech-to-Text & Text-to-Speech Engine
* **Slide Layout**: Two Columns (Voice Input / Audio Synthesis)
* **Speech-to-Text Input (STT)**:
  * Capture: MediaRecorder browser API captures 16kHz audio in WebM.
  * VAD Silence Stop: JavaScript VoiceController tracks audio volume. Automatically triggers stop and backend post after 7 seconds of silence.
  * Transcription: Backend sends WebM payload to Groq Whisper-large-v3.
  * Vocabulary Boost: Feeds a system vocabulary prompt to Whisper containing technical acronyms (e.g. RAG, Pinecone, GDELT, BM25) to prevent transcription misspelling.
* **Text-to-Speech Output (TTS)**:
  * Uses browser HTML5 SpeechSynthesis API. Allows users to listen to compiled reports with local voice models at 1.0x rate.

---

## Slide 12: Deployment Architecture (AWS EC2)
* **Slide Title**: Production Deployment Configuration
* **Slide Layout**: System Configuration Details
* **Server Environment**:
  * AWS EC2 running Ubuntu 26.04 LTS.
  * 2GB Virtual Swap File configured in /etc/fstab to prevent OOM errors during local BGE model execution.
* **Nginx Configuration**:
  * Port 80 reverse proxy pointing to Uvicorn on 127.0.0.1:8000.
  * proxy_buffering off; explicitly configured. Disables Nginx buffering so FastAPI SSE output streams instantly.
  * proxy_read_timeout set to 86400s to maintain long-lived SSE connections.
* **Supervisor Setup**:
  * systemd sentinel.service unit manages the ASGI server process. Configured for restart-always with 3-second recovery delay.

---

## Slide 13: Scaling Blueprint (Targeting 10k Concurrent Users)
* **Slide Title**: Scaling to 10,000 Concurrent Active Users
* **Slide Layout**: Five Key Upgrades
* **1. AWS Application Load Balancer (ALB)**:
  * Sits in front of app servers. Handles HTTPS SSL termination and balances incoming traffic.
* **2. Auto Scaling Group (ASG)**:
  * Dynamically scales the pool of app instances (3 to 6 x t3.medium EC2 instances) based on CPU load.
* **3. Celery Distributed Task Queue**:
  * Offloads the LangGraph research runs from the main web server threads to dedicated background Celery workers on ECS.
* **4. Supabase Database Pooling**:
  * Routes queries through Supabase pgBouncer on transaction mode (port 6543) to prevent PostgreSQL connection exhaustion.
* **5. Multi-Key Rotation**:
  * Cycles Google Gemini and Groq API keys in a round-robin pool to prevent provider rate-limits.
