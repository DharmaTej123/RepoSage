# RepoSage — Architecture Diagram

Technology is labelled at every component. Three views:
1. **System architecture** — client → API → queue → worker → stores, with the tech at each box.
2. **Agent pipeline (worker internals)** — the LangGraph nodes and the tools each uses.
3. **Data model** — the core persistence relationships.

---

## 1. System architecture (tech at each component)

```mermaid
flowchart TB
    subgraph CLIENT["🖥️ Frontend"]
        UI["Web app<br/><b>React + TypeScript</b><br/>Vite · Tailwind<br/>react-flow / d3-force graph"]
    end

    subgraph API["⚙️ API layer"]
        FAST["REST API<br/><b>FastAPI</b> (async)<br/>Pydantic v2 schemas<br/>202 Accepted on submit"]
    end

    subgraph QUEUE["📬 Job queue"]
        REDIS["<b>Redis</b> + <b>RQ</b><br/>enqueue analysis<br/>(sync fallback in dev/test)"]
    end

    subgraph WORKER["🧠 Worker process"]
        LG["Orchestrator<br/><b>LangGraph</b> stateful graph<br/>checkpointer = resume<br/>TypedDict state + reducers"]
        ING["Ingestion<br/><b>GitPython</b> clone/copy<br/>size + language + manifest detect"]
    end

    subgraph SANDBOX["🔒 Sandbox (untrusted code only)"]
        DOCK["<b>Docker</b> container<br/>network=none · read-only fs<br/>cap_drop ALL · pids/cpu/mem/timeout<br/>pytest --cov inside"]
    end

    subgraph EXT["🌐 External APIs"]
        OSV["<b>OSV.dev</b> vuln DB<br/>(httpx batch query)"]
        PYPI["<b>PyPI JSON API</b><br/>release-date / staleness"]
    end

    subgraph STORES["💾 Datastores"]
        PG["<b>Postgres</b><br/>SQLAlchemy + Alembic<br/>system of record:<br/>repos·runs·jobs·findings·evidence·metrics"]
        NEO["<b>Neo4j</b><br/>structural graph<br/>imports·authors·commits·packages"]
        VEC["<b>pgvector</b><br/>code/doc embeddings<br/>semantic retrieval"]
    end

    subgraph OBS["📊 Observability"]
        LS["<b>LangSmith</b> tracing<br/>correlated to job_id<br/>latency · tokens · retries"]
    end

    UI -->|REST / JSON| FAST
    FAST -->|enqueue job_id| REDIS
    FAST -->|read status/results| PG
    REDIS -->|dequeue| LG
    FAST -.->|synchronous ingest| ING
    ING --> LG
    LG -->|run tests| DOCK
    LG -->|vuln + release lookups| OSV
    LG -->|release dates| PYPI
    LG -->|run/finding metadata| PG
    LG -->|graph nodes/edges| NEO
    LG -->|chunks + embeddings| VEC
    LG -.->|traces| LS
    FAST -->|graph queries| NEO
    FAST -->|copilot vector search| VEC

    classDef client fill:#ede9fe,stroke:#7c3aed,color:#4c1d95;
    classDef api fill:#dbeafe,stroke:#2563eb,color:#1e3a8a;
    classDef infra fill:#fee2e2,stroke:#dc2626,color:#7f1d1d;
    classDef worker fill:#dcfce7,stroke:#16a34a,color:#14532d;
    classDef store fill:#fef3c7,stroke:#d97706,color:#78350f;
    classDef ext fill:#f1f5f9,stroke:#64748b,color:#1e293b;

    class UI client;
    class FAST api;
    class REDIS,DOCK infra;
    class LG,ING worker;
    class PG,NEO,VEC store;
    class OSV,PYPI,LS ext;
```

---

## 2. Agent pipeline — nodes & tools (worker internals)

```mermaid
flowchart TD
    START([initial RunState]) --> ING[ingest node<br/><i>validate inputs</i>]
    ING --> MGR{{manager / investigation<br/><i>bounded plan: enable / skip + reason</i>}}

    MGR -->|fan-out| ARCH["architecture mapper<br/><b>tools:</b> python ast · networkx · Neo4j driver<br/><i>→ module graph + centrality</i>"]
    MGR -->|fan-out| DEP["dependency risk<br/><b>tools:</b> manifest parser · OSV API · PyPI API (httpx)<br/><i>→ CVE + staleness findings</i>"]
    MGR -->|fan-out| GIT["git history &amp; ownership<br/><b>tools:</b> GitPython<br/><i>→ churn · bus-factor · ownership</i>"]

    ARCH --> COV["coverage gap<br/><b>tools:</b> Docker SDK · pytest --cov · centrality<br/><i>→ coverage × centrality risk</i>"]
    DEP --> COV
    GIT --> COV

    COV --> NORM["normalize<br/><i>dedupe + canonical severity order</i>"]
    NORM --> REASON["reasoning (deterministic)<br/><b>evidence store → validate → conflict resolve → risk score → correlate</b>"]
    REASON --> SYN["synthesis<br/><b>tools:</b> pgvector RAG + validated findings (+ LLM prose)<br/><i>→ onboarding.md + tech-debt report + run diff</i>"]
    SYN --> END([persisted artifacts])

    classDef det fill:#e6f0ff,stroke:#3b82f6,color:#1e3a8a;
    classDef llm fill:#fef3c7,stroke:#d97706,color:#78350f;
    classDef io fill:#dcfce7,stroke:#16a34a,color:#14532d;
    class ARCH,DEP,GIT,COV,NORM,REASON det;
    class SYN llm;
    class ING,MGR io;
```

**Legend:** Blue = deterministic (zero LLM tokens) · Amber = LLM-capable · Green = control/IO.
Every node runs through `run_node(...)` → emits status + latency + tool_calls + retries + errors, retries transient failures (bounded), and never aborts the run on a single node failure.

---

## 3. Data model (persistence)

```mermaid
erDiagram
    REPOSITORY ||--o{ RUN : "has many (per revision)"
    RUN ||--|| JOB : "tracked by"
    RUN ||--o{ FINDING : produces
    FINDING ||--o{ EVIDENCE : "backed by"
    RUN ||--o{ AGENT_METRIC : records

    REPOSITORY {
        string id PK
        string source
        string source_type
        string language
    }
    RUN {
        string id PK
        string repo_id FK
        string revision "analyzed HEAD (immutable)"
        float size_mb
        json manifest_files
        json artifacts "onboarding + tech-debt"
    }
    JOB {
        string id PK
        string run_id FK
        string status "pending|running|complete|failed"
        json agent_status "per-node outcome"
        string error
    }
    FINDING {
        string id PK
        string run_id FK
        string agent
        string category
        string severity
        float confidence
        string status "observed|inferred|validated|disputed"
        json deterministic_signals
    }
    EVIDENCE {
        string id PK
        string finding_id FK
        string source_type "file|line|graph|git|command|external_api"
        string source
        string location
    }
    AGENT_METRIC {
        string id PK
        string run_id FK
        string agent
        int latency_ms
        int tool_calls
        int retries
    }
```

> Postgres is the system of record for everything above. Neo4j separately holds the structural graph (modules/imports/authors/commits/packages) keyed by revision; pgvector holds code/doc embeddings. The rule is one authoritative home per fact — no cross-store duplication without a retrieval reason.

---

## 4. Request lifecycle (sequence)

```mermaid
sequenceDiagram
    participant U as Client (React)
    participant A as FastAPI
    participant G as GitPython ingest
    participant Q as Redis/RQ
    participant W as Worker (LangGraph)
    participant S as Docker sandbox
    participant D as Postgres/Neo4j/pgvector

    U->>A: POST /runs {repo_url}
    A->>G: clone + detect lang/manifests + capture HEAD
    A->>D: idempotency check (repo_id + revision)
    A->>Q: enqueue analysis(run_id)
    A-->>U: 202 { job_id }
    Q->>W: dequeue job
    W->>W: manager plan → specialists (parallel)
    W->>S: run tests (no network, read-only, limits)
    S-->>W: coverage.json + exit code (or TIMEOUT/UNAVAILABLE)
    W->>W: normalize → reason → synthesize
    W->>D: persist findings + artifacts + graph + embeddings
    U->>A: GET /runs/{job_id}/results
    A->>D: read findings + artifacts + completeness
    A-->>U: onboarding + tech-debt + evidence
```
