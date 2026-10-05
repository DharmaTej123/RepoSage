# Tasks — RepoSage (Codebase Onboarding & Tech-Debt Copilot)

Each task lists the requirement(s) it satisfies so progress stays traceable back to requirements.md.

## Phase 0 — Foundations
- [x] 0.1 Scaffold FastAPI project, Postgres schema (repos, runs, jobs, findings, evidence, agent_metrics) — (Req 7, 12, 15)
- [x] 0.2 Docker Compose for local dev: Postgres, Redis, Neo4j, pgvector-enabled Postgres
- [x] 0.3 Repository ingestion endpoint: clone/copy into isolated working dir, size-limit check, language/manifest detection — (Req 1)
- [x] 0.4 Persist repository revision/HEAD and immutable run metadata — (Req 1)
- [x] 0.5 Define application configuration for repository size, history window, sandbox limits, coverage threshold, bus-factor threshold, staleness threshold, and LLM budget
- [x] 0.6 Define common `Finding` and `Evidence` schemas with provenance and validation rules — (Req 7)

## Phase 1 — Architecture Mapper Agent
- [x] 1.1 AST-based import parser for a Python codebase → module dependency edge list
- [x] 1.2 Centrality computation (networkx) over the edge list
- [x] 1.3 Neo4j write layer: persist files/modules/relationships + centrality + revision
- [x] 1.4 Handle unparsable files gracefully (log + continue) — (Req 2)
- [x] 1.5 Capture file/module/class/function relationships where reliably available
- [x] 1.6 Capture provenance for graph relationships (source file/location + relationship type)
- [x] 1.7 Implement graph queries for direct/transitive dependencies and approximate blast radius
- [x] 1.8 Implement graph queries for high-centrality modules and high-centrality/low-coverage candidates

## Phase 2 — Dependency Risk Agent
- [x] 2.1 Manifest parser (requirements.txt / pyproject.toml)
- [x] 2.2 OSV API client, batch query, CVE severity extraction
- [x] 2.3 PyPI release-date lookup, staleness flagging (config threshold)
- [x] 2.4 Graceful degradation when OSV is unreachable — (Req 3)
- [x] 2.5 Distinguish direct/transitive dependencies where metadata permits
- [x] 2.6 Emit structured findings with external-source provenance
- [x] 2.7 Distinguish clean result from unavailable vulnerability data

## Phase 3 — Git History & Ownership Agent
- [x] 3.1 GitPython-based commit log mining, windowed to configurable recency
- [x] 3.2 Per-module churn + primary-author computation
- [x] 3.3 Bus-factor flagging (config threshold) — (Req 4)
- [x] 3.4 Build developer → commit → file/module relationships for historical ownership queries
- [x] 3.5 Distinguish historical contribution from formal ownership in output
- [x] 3.6 Emit structured findings and deterministic ownership signals

## Phase 4 — LangGraph Agentic Orchestration
- [x] 4.1 Define `RunState` TypedDict and reducers
- [x] 4.2 Add Manager/Investigation Agent with bounded task-routing decisions
- [x] 4.3 Wire fan-out (architecture / dependency / git-history) → finding normalization
- [x] 4.4 Support conditional skipping based on repository characteristics
- [x] 4.5 Add structured Finding/Evidence normalization node
- [x] 4.6 Add per-node status, metrics, timing, retry count and error capture
- [x] 4.7 Add bounded retries for transient tool failures
- [x] 4.8 Add LangGraph checkpointing and resume support
- [x] 4.9 Distinguish failed / skipped / not-applicable / no-finding states
- [x] 4.10 LangSmith tracing wired to job_id and agent/node identifiers
- [x] 4.11 Preserve partial state/results when non-critical nodes fail

## Phase 5 — Test Coverage Gap Agent + Sandboxing
- [x] 5.1 Build sandbox Docker image (no network, resource/time limits)
- [x] 5.2 Worker-side container lifecycle: run, timeout-kill, destroy — (Req 6)
- [x] 5.3 Coverage run (`pytest --cov --cov-report=json`) inside sandbox
- [x] 5.4 Cross-reference coverage % against centrality from state → risk flags — (Req 5)
- [x] 5.5 Skip-with-reason path when no test runner is discoverable
- [x] 5.6 Persist test exit code, duration, stdout/stderr and coverage status
- [x] 5.7 Add automated sandbox isolation test confirming outbound network access is blocked (`tests/test_sandbox_isolation.py`: network probe uses the runner's real `isolation_run_kwargs`; skips cleanly without Docker; a Docker-free contract test guards the isolation flags)
- [x] 5.8 Ensure repository code is never executed outside the sandbox

## Phase 6 — Evidence, Risk & Tech-Debt Reasoning
- [x] 6.1 Aggregate specialist findings into a normalized evidence store
- [x] 6.2 Build deterministic risk signals: centrality, churn, coverage, dependency severity, bus-factor concentration
- [x] 6.3 Implement normalized technical-debt priority/risk scoring
- [x] 6.4 Preserve contributing signals and score explanation per finding
- [x] 6.5 Correlate related findings affecting the same component/risk area
- [x] 6.6 Avoid double-counting correlated observations
- [x] 6.7 Add Evidence Validation Agent for high-severity/high-confidence findings
- [x] 6.8 Mark findings as observed / inferred / validated / disputed
- [x] 6.9 Add Conflict Resolver for contradictory specialist findings
- [x] 6.10 Preserve unresolved conflicts explicitly rather than silently selecting a winner

## Phase 7 — Synthesis Agent
- [x] 7.1 Code + doc chunking and embedding into pgvector
- [x] 7.2 RAG-backed onboarding.md generation (architecture overview, reading order, ownership, dependencies, high-risk areas) — (Req 10)
- [x] 7.3 Tech-debt report generation with combined severity/impact ranking and per-finding source attribution — (Req 10)
- [x] 7.4 Diff-against-previous-run logic: new/changed/resolved findings
- [x] 7.5 Ensure synthesis distinguishes unavailable analysis from clean results
- [x] 7.6 Ensure every final claim maps to Finding/Evidence or is explicitly labeled inference
- [x] 7.7 Persist generated artifacts against repository revision

## Phase 8 — Repository Knowledge & Interactive Copilot
- [x] 8.1 Build query-time retrieval layer over Neo4j, pgvector, git history and source files
- [x] 8.2 Implement Query Manager/Router that chooses graph/vector/git/source retrieval based on question type
- [x] 8.3 Implement graph-aware questions: dependency and blast-radius queries
- [x] 8.4 Implement ownership/history questions
- [x] 8.5 Implement onboarding questions: reading order, architecture, request flow
- [x] 8.6 Implement evidence-backed Answer Generator
- [x] 8.7 Return source/file references with answers
- [x] 8.8 Preserve short-term conversation state for follow-up questions
- [x] 8.9 Add guardrail preventing unsupported claims when required evidence is unavailable

## Phase 9 — API Completion
- [x] 9.1 `POST /runs`, `GET /runs/{id}/status`, `GET /runs/{id}/results`, `GET /runs/{id}/graph`, `GET /repos/{id}/history`
- [x] 9.2 Add `GET /runs/{id}/findings/{finding_id}` for evidence/provenance inspection
- [x] 9.3 Add `POST /runs/{id}/query` for interactive repository questions
- [x] 9.4 Add job queue wiring (Redis + RQ/Celery), worker process
- [x] 9.5 Ensure APIs expose incomplete/failed/skipped analysis explicitly
- [x] 9.6 Add idempotency/revision-aware run handling

## Phase 10 — Frontend
- [x] 10.1 React/TS/Vite/Tailwind scaffold (reuse DocuMind primitives)
- [x] 10.2 Overview/dashboard with run health and analysis completeness
- [x] 10.3 Graph explorer view (react-flow/d3-force) — (Req 13)
- [x] 10.4 Tech-debt report table (sort/filter + contributing signals) — (Req 13)
- [x] 10.5 Finding detail view with evidence/source locations
- [x] 10.6 Agent trace view with status, latency, retries, tool calls and structured output
- [x] 10.7 Copilot interface with evidence references
- [x] 10.8 Module detail panel showing centrality, coverage, ownership, dependencies and risk explanation

## Phase 11 — Evaluation
- [x] 11.1 Select 2–3 representative open-source Python repositories
- [x] 11.2 Create a small ground-truth set for architecture relationships
- [x] 11.3 Create ground-truth ownership/churn cases
- [x] 11.4 Create dependency-risk and coverage-risk expected findings
- [x] 11.5 Create expected answers for onboarding/coplaner questions
- [x] 11.6 Implement finding precision/recall evaluation
- [x] 11.7 Implement evidence attribution accuracy evaluation
- [x] 11.8 Implement onboarding Q&A correctness evaluation
- [x] 11.9 Track unsupported-claim/hallucination rate
- [x] 11.10 Implement deterministic-only baseline for selected tasks
- [x] 11.11 Compare deterministic baseline vs. full evidence-backed agentic pipeline
- [x] 11.12 Persist evaluation results for regression testing

## Phase 12 — End-to-end validation & packaging
- [x] 12.1 Run full pipeline against 2–3 real open-source Python repos of varying size — harness: `python -m scripts.validate_pipeline` (clones six/cachecontrol/click via `IngestionService`, runs the full workflow, asserts synthesis + onboarding/tech-debt artifacts). Requires a Docker host + network; run there to record results.
- [x] 12.2 Validate sandbox isolation (attempt network call from inside sandboxed test run, confirm it's blocked) — covered by `tests/test_sandbox_isolation.py` and `scripts.validate_pipeline` (`--skip-pipeline`), which run the network probe under the production isolation flags. Requires a Docker host to execute the live assertion.
- [x] 12.3 Validate checkpoint/resume by interrupting a run and resuming without rerunning completed nodes
- [x] 12.4 Validate partial-failure behavior by making one specialist unavailable
- [x] 12.5 Validate conflict-resolution behavior with a controlled contradictory finding scenario
- [x] 12.6 Validate evidence citations on final onboarding/tech-debt output
- [x] 12.7 README with architecture diagram, agent graph, data model, setup instructions, sample output, evaluation results
- [x] 12.8 Deployment (Railway/Docker, matching DocuMind's pattern)
