# Sentinel Presentation Guide and Script

This document provides a slide-by-slide guide and speaking script for presenting the Sentinel Geopolitical Intelligence platform to a technical audience, stakeholders, or examiners.

---

## Slide 1: Title and Overview
* **Slide Title**: Sentinel: Distributed Multi-Agent Geopolitical Intelligence Platform
* **Key Talking Points**:
  * Traditional single-agent LLMs hallucinate, lack verification, and fail on long-horizon research tasks.
  * Sentinel is an enterprise-grade deep research engine that structures research into state-driven, multi-agent workflows.
  * Built using a modern technical stack: FastAPI, LangGraph, Upstash Redis, Supabase, and Pinecone.

---

## Slide 2: The Three-Pillar Architecture
* **Slide Title**: System Infrastructure Architecture
* **Speaking Script**:
  > "To understand Sentinel, we must look at its three core structural pillars:
  >
  > 1. The Application Layer: Powered by Nginx and FastAPI. Nginx acts as our reverse proxy with proxy buffering disabled to allow real-time Server-Sent Events (SSE) logs to stream directly to the browser.
  > 2. The State Layer: Powered by Upstash Redis. Because deep research runs are long-lived and background-threaded, we do not store state in local server memory. All run progress, rate limits, and live execution logs are stored in distributed Redis hashes and broadcast via Redis Pub/Sub channels.
  > 3. The Storage and Search Layer: Powered by Supabase Postgres and Pinecone. Supabase handles database transactions, full-text keyword indexing, and user authentication. Pinecone handles high-density vector similarity lookups."

---

## Slide 3: The Research Agent Graph (LangGraph)
* **Slide Title**: The Multi-Agent State Machine
* **Speaking Script**:
  > "Instead of running a simple chain of LLM prompts, Sentinel uses LangGraph to construct a state-driven cyclic graph. The entire workflow passes a single, shared state dictionary between specialized nodes. Let's walk through this execution graph node-by-node."

---

## Slide 4: Nodes 1 & 2 — Lead Researcher and Human-in-the-Loop
* **Slide Title**: Node 1: Lead Researcher | Node 2: Human-in-the-Loop Pause
* **Speaking Script**:
  > "The entry point of the graph is the Lead Researcher node. 
  >
  > * Role of Lead Researcher: When a user submits a query, this node acts as the supervisor. It analyzes the topic complexity, classifies the domain (e.g., Geopolitical, Economic, or Scientific), and generates a structured research plan. It breaks down the main topic into distinct sub-tasks for our parallel workers.
  > * Role of the Human-in-the-Loop Pause: Deep research can be expensive and time-consuming. Instead of executing immediately, the graph halts. The Lead Researcher writes the research plan, publishes a plan_ready event to Redis, and pauses. The backend thread waits on a threading.Event object. The execution only resumes when the user reviews the plan on the frontend and clicks 'Proceed', which signals FastAPI to toggle the approval flag in Redis."

---

## Slide 5: Node 3 — Spawning Parallel Subagents
* **Slide Title**: Node 3: Parallel Subagents Pool
* **Speaking Script**:
  > "Once approved, the graph moves to the Spawn Subagents node.
  >
  > * Role of Spawn Subagents: Rather than running sequentially, Sentinel spawns multiple child agent threads concurrently using Python's ThreadPoolExecutor.
  > * Subagent Search Loop: Each subagent is assigned a specific sub-task from the research plan. To gather intelligence, each subagent queries three distinct sources:
  >   1. Our internal Hybrid RAG database for historical context.
  >   2. The Tavily AI search engine for live web data.
  >   3. The GDELT Project API to query real-time worldwide news databases.
  > All retrieved text fragments are consolidated into the shared raw intelligence backlog."

---

## Slide 6: Nodes 4 & 5 — Cross-Examiner and Timeline Compiler
* **Slide Title**: Node 4: Cross-Examiner | Node 5: Timeline Compiler
* **Speaking Script**:
  > "With raw data gathered, we enter the verification phase.
  >
  > * Role of the Cross-Examiner: Geopolitical news is often filled with bias, contradictions, and misinformation. The Cross-Examiner node runs a cross-model consensus check. It uses Google Gemini and Groq (Llama-3.3) to evaluate the gathered sources independently. If the models disagree on key facts, the node marks a contradiction flag, highlights the source bias, and scores the factual credibility of the intel.
  > * Role of the Timeline Compiler: Raw intelligence lacks structural timing. The Timeline Compiler parses all verified reports, extracts date stamps, milestones, and chronological indicators, and builds a chronological event index. This ensures the final output has a clear historical progression."

---

## Slide 7: Nodes 6 & 7 — Sufficiency Evaluator and Synthesizer
* **Slide Title**: Node 6: Sufficiency Evaluator | Node 7: Synthesizer (The Output)
* **Speaking Script**:
  > "The final steps ensure quality control and compile the report.
  >
  > * Role of the Sufficiency Evaluator: This node calculates an information coverage score and checks for uncited claims. If the information is insufficient and we have not exceeded our maximum loop iteration count, the evaluator triggers a conditional route back to the Lead Researcher to gather more data. If the information is sufficient, it routes to the Synthesizer.
  > * Role of the Synthesizer: The Synthesizer takes the verified intel, the event timeline, and the bias matrix, and generates a structured executive markdown report. Crucially, it formats strict inline citations linking back to the source URLs and documents retrieved during the search loop."

---

## Slide 8: The RAG Engine — Hybrid Search and RRF
* **Slide Title**: 3-Channel Hybrid Search & Reciprocal Rank Fusion
* **Speaking Script**:
  > "To retrieve the correct document context, Sentinel does not rely on simple vector database lookups. Instead, we use a 3-channel retrieval pipeline:
  >
  > * Channel 1: Dense Semantic Vector Search. We generate a 768-dimensional embedding locally using the BGE model on CPU and query Pinecone.
  > * Channel 2: Sparse Keyword Search. We fit a BM25 encoder locally against all document terms to score exact word matches.
  > * Channel 3: Database Full-Text Search. We execute a Postgres tsquery in Supabase.
  >
  > We then merge the results using Reciprocal Rank Fusion (RRF). RRF calculates a unified score for each chunk based on its rank position in all three channels, using a smoothing constant of k=60. This guarantees that whether a user searches by semantic meaning, exact acronym, or document ID, the correct context is retrieved."

---

## Slide 9: Optimization — Semantic Q&A Cache
* **Slide Title**: Vector Semantic Caching
* **Speaking Script**:
  > "To minimize LLM API latency and token cost, we built a semantic cache layer. 
  >
  > When a user chats with Sentinel, we compute the BGE vector embedding of their question and run a cosine similarity query against previously answered questions stored in Supabase. If the similarity score is 0.90 or higher, the system immediately returns the cached answer. This cuts response latency from 16.5 seconds down to 1.1 seconds, saves 100% of LLM token costs, and reduces server load by 95%."

---

## Slide 10: Production Scaling & Conclusion
* **Slide Title**: Scaling to 10,000 Concurrent Users
* **Speaking Script**:
  > "Sentinel is currently deployed on a single AWS EC2 instance using systemd and an Nginx reverse proxy. 
  >
  > To scale this architecture to support 10,000 concurrent active users, we have designed a clear roadmap:
  > 1. Add an AWS Application Load Balancer to terminate SSL and distribute traffic.
  > 2. Put the EC2 application servers into an Auto Scaling Group.
  > 3. Migrate the background agent graph threads to a distributed Celery worker pool running on ECS.
  > 4. Enable Supabase's transaction pooler (pgBouncer) to manage database connections.
  >
  > This modular architecture separates routing, state storage, and background processing, enabling cost-effective scaling as traffic grows. Thank you, and I am now open to your questions."
