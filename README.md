# RepoSage - Codebase Onboarding & Tech-Debt Copilot

RepoSage is an evidence-driven, multi-agent system that analyzes a Python
repository and produces an onboarding guide, a technical-debt report, and an
interactive copilot. Deterministic code analysis is kept strictly separate from
LLM-based reasoning: repository facts originate from deterministic analyzers and
external data sources, and every important finding carries traceable evidence.

v1 scope: Python repositories only. No autonomous code modification, no
multi-language/tree-sitter support, no Kubernetes.

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

## Deployment

Containerized via docker compose (see docker-compose.yml and
infra/). The backend and worker share one image; the frontend builds to static
assets. See DEPLOYMENT.md for the Railway/Docker pattern.
