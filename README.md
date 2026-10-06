# RepoSage - Codebase Onboarding & Tech-Debt Copilot

RepoSage is an evidence-driven, multi-agent system that analyzes a Python
repository and produces an onboarding guide, a technical-debt report, and an
interactive copilot. Deterministic code analysis is kept strictly separate from
LLM-based reasoning: repository facts originate from deterministic analyzers and
external data sources, and every important finding carries traceable evidence.

v1 scope: Python repositories only. No autonomous code modification, no
multi-language/tree-sitter support, no Kubernetes.

## Is this an "AI" project? (positioning)

Yes — RepoSage is an **agentic AI system**, and it is deliberately
**deterministic-first**. "AI" here is broader than "calls an LLM":

- **Agentic orchestration is the core.** A Manager / Investigation agent *plans*
  which specialists apply to a given repository (bounded routing), independent
  specialist agents run in parallel, and a reasoning tail performs evidence
  validation, conflict resolution, correlation, and risk scoring with bounded
  retries and checkpoint/resume. That autonomous, stateful control flow — not a
  single prompt — is what makes it agentic.
- **Classical AI / graph + IR techniques do the analysis.** PageRank-style
  centrality and graph traversal (dependency and blast-radius reasoning),
  churn/ownership inference, deterministic risk scoring, intent-based query
  routing, and vector similarity retrieval are all AI/ML-adjacent methods, not
  CRUD.
- **The LLM is an optional presentation seam, by design.** Repository *facts*
  come from deterministic analyzers and external data; the LLM's only sanctioned
  job is to render validated evidence into fluent prose. That boundary is the
  whole point: it makes outputs reproducible, auditable, and hallucination-free,
  and lets the system run and be evaluated fully offline. The seams are
  architected (clean `(answer, sources)` / structured-artifact contracts, an
  embeddings-provider abstraction, token-budget config, LangSmith hooks) so a
  real model is a drop-in — but no model is required for the system to work.

**Accurate one-liner:** *evidence-first, LLM-optional agentic system — the
deterministic core is the product; generative AI is a decoupled rendering layer
that can never be the source of truth for a repository fact.*

## Core pipeline

```
Repository
  -> deterministic extraction (AST, manifests, git)
  -> codebase knowledge graph + evidence
  -> specialist agents (architecture / dependency / git-history / coverage)
  -> Manager / Investigation Agent (bounded routing)
  -> finding normalization
  -> risk / tech-debt reasoning (deterministic scoring)
  -> evidence validation
  -> conflict resolution (preserves unresolved conflicts)
  -> synthesis (onboarding + tech-debt + diff)
  -> interactive repository copilot
```

## Agent graph (LangGraph)

```
START -> ingest -> manager
  -> { architecture | dependency | git_history }   (parallel fan-out)
  -> coverage    (sandboxed; runs after specialists for centrality x coverage)
  -> normalize
  -> reason      (validation -> conflict -> scoring -> correlation)
  -> synthesis -> END
```

Features: conditional skipping, bounded retries, checkpointing/resume, partial
failure isolation (a failed specialist does not kill the run), and explicit
failed / skipped / not-applicable / no-finding states. Observability via
per-node metrics (status, latency, retries, tool calls, LLM tokens) and
optional LangSmith tracing keyed by job_id / run_id.

## Storage responsibilities

| Store       | Responsibility |
|-------------|----------------|
| PostgreSQL  | System of record: repos, runs, jobs, findings, evidence, agent metrics, artifacts |
| Neo4j       | Structural knowledge graph (Developer->Commit->File->Module; IMPORTS/CONTAINS/TESTS/DEPENDS_ON) for reasoning/queries |
| pgvector    | Semantic retrieval over code / doc / artifact chunks |
| Redis       | Job queue / transient coordination |
| Working dir | Per-run immutable repository snapshot |

Fallbacks: when Neo4j or Redis are unavailable, the system degrades to an
in-memory graph store and a synchronous in-process queue so it still runs
locally without Docker.

## Data model (findings & evidence)

Every finding carries: id, agent, category, severity, confidence, description,
affected components, evidence references, recommendation, deterministic signals,
and status (observed | inferred | validated | disputed). Evidence sources:
file/line, graph relationship, git history, command output, external API.

## Sandboxing (untrusted repository code)

Repository test suites run only inside a Docker sandbox started with
network=none, read-only repo mount, isolated writable scratch, CPU/memory/pids
limits, cap_drop ALL, no-new-privileges, a wall-clock timeout, and guaranteed
container teardown. An automated test (tests/test_sandbox_isolation.py) proves
outbound network is blocked (runs where Docker is available).

## Setup

Prerequisites: Python 3.11+ (dev on 3.13), Node 18+ (dev on 24), Docker +
Docker Compose (for Postgres/pgvector, Redis, Neo4j, and the sandbox).

Backend:
- cd backend
- python -m venv .venv and activate it
- pip install -r requirements.txt
- copy .env.example to .env and adjust
- uvicorn app.main:app --reload

Infrastructure: docker compose up -d  (Postgres+pgvector, Redis, Neo4j)

Worker: cd backend, then python -m app.worker

Frontend: cd frontend, npm install, then start the vite dev server.

Tests: cd backend, then python -m pytest -q

Evaluation: cd backend, then python -m app.evaluation.run eval_results.json

## Sample output (evaluation, fixture repos)

```
architecture_dependency.f1    : 1.0
blast_radius.f1               : 1.0
ownership.accuracy            : 1.0
finding_detection.f1          : 1.0
qa_correctness.accuracy       : 1.0
evidence_attribution.accuracy : 1.0
hallucination_rate            : 0.0
```

The evaluation also records a deterministic-only baseline vs the full agentic +
evidence-backed pipeline, demonstrating the agentic layer adds validation,
correlation, ranking, conflict handling, and evidence-backed Q&A without
degrading deterministic accuracy.

## Interactive copilot (examples)

- What depends on PaymentService?
- Who has historically worked on this module? (historical contribution, not ownership)
- Why is this module considered high risk?
- What should I read first?
- What is the approximate blast radius of changing this module?

The query router chooses graph / vector / git / source retrieval per question
type. Answers include source references; when evidence is unavailable the
copilot says so instead of fabricating an answer.

### How the copilot works without an LLM

The copilot does not re-analyze the repository per question. The heavy analysis
already ran during the pipeline, producing structured data (an import graph with
centrality, an ownership report, embedded code chunks). Each question flows
through the same `route -> retrieve -> format` shape as an LLM RAG system, but
every slot is deterministic:

1. **Route (intent classification).** Keyword/pattern rules classify the
   question and extract the target module ("what depends on X" -> dependency,
   "blast radius of X" -> blast_radius, "who worked on X" -> ownership, "what
   should I read first" -> reading_order). No model.
2. **Retrieve (the actual answering).**
   - *Graph* questions are **graph algorithms**: "what depends on X" is a
     dependents traversal; blast radius is reachability over the import graph.
     These answers are *computed and exact*, not approximated.
   - *Ownership* questions read the pre-mined contributor/churn report.
   - *Open-ended* questions rank code chunks by vector cosine similarity.
   - *Source* lookups return the actual file lines for a module.
3. **Format.** A template renders the retrieved items and attaches the
   `Evidence` each retriever carried. If nothing is retrieved, it returns an
   explicit "insufficient evidence" answer.

For structured questions (dependencies, blast radius, ownership, reading order)
this is **more reliable than an LLM** because the answers are derived from the
graph/git facts rather than generated. The trade-off: answers are accurate and
provenance-backed but **templated rather than conversational**, and offline
free-text relevance uses a deterministic hashing embedder (so graph/git answers
stay sharp, while semantic phrasing is where an optional LLM layer would add the
most value).

## Deployment

Containerized via docker compose (see docker-compose.yml and
infra/). The backend and worker share one image; the frontend builds to static
assets. See DEPLOYMENT.md for the Railway/Docker pattern.
