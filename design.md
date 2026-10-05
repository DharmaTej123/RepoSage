# Design — RepoSage (Codebase Onboarding & Tech-Debt Copilot)

## 1. Architecture overview

```text
Client (React)
   |
   v
FastAPI (submit / status / results / graph / copilot)
   |
   v
Job Queue (Redis + RQ/Celery) -----> Worker
                                      |
                                      v
                              LangGraph Orchestrator
                                      |
                         +------------+-------------+
                         | Manager / Investigation |
                         | Agent                   |
                         +------------+-------------+
                                      |
                +---------------------+----------------------+
                |                     |                      |
                v                     v                      v
         Architecture           Dependency Risk        Git History &
            Agent                   Agent                Ownership Agent
                |                     |                      |
                +---------------------+----------------------+
                                      |
                                      v
                         Evidence / Finding Normalizer
                                      |
                                      v
                         +-------------------------------+
                         | Risk / Impact Reasoning       |
                         | + conflict resolution        |
                         +---------------+---------------+
                                         |
                                         v
                               Test Coverage Gap
                               (sandboxed; uses graph)
                                         |
                                         v
                                Evidence Validation
                                         |
                                         v
                                  Synthesis Agent
                              /                                                v                     v
                       onboarding.md        tech-debt-report.md
                             |                     |
                             +----------+----------+
                                        |
                          Persist Postgres + Neo4j
                                  + pgvector
```

**Why multi-agent, not one big prompt:** each specialist has a different tool surface and failure mode (AST parser, OSV API, git history, sandboxed test runner). The Manager Agent decides which analyses are applicable; independent specialists run in parallel; structured findings are normalized and validated before synthesis. This keeps deterministic work deterministic, limits LLM usage, and makes failures isolated and observable.

## 2. Agent graph (LangGraph)

The graph is stateful and resumable. Shared state uses `TypedDict` plus reducers for append-only collections.

```python
class RunState(TypedDict):
    job_id: str
    repo_id: str
    repo_path: str
    revision: str
    language: str
    manifest_files: list[str]

    architecture_graph: dict | None
    dependency_report: dict | None
    ownership_map: dict | None
    coverage_gaps: dict | None

    findings: Annotated[list[dict], operator.add]
    evidence: Annotated[list[dict], operator.add]
    investigation_plan: dict | None
    conflicts: Annotated[list[dict], operator.add]

    agent_status: dict[str, str]
    agent_metrics: dict[str, dict]
    onboarding_doc: str | None
    tech_debt_report: dict | None
    copilot_context: dict | None

    errors: Annotated[list[str], operator.add]
```

### Core graph

```text
START
  |
  v
ingest
  |
  v
manager / investigation planner
  |
  +-------------------+-------------------+
  |                   |                   |
  v                   v                   v
architecture       dependency          git-history
mapper             risk                ownership
  |                   |                   |
  +-------------------+-------------------+
                      |
                      v
              finding normalizer
                      |
                      v
             tech-debt/risk reasoning
                      |
                      v
              coverage-gap agent
                      |
                      v
              evidence validation
                      |
             +--------+---------+
             |                  |
          conflicts?          no conflict
             |                  |
             v                  |
       conflict resolver        |
             |                  |
             +--------+---------+
                      |
                      v
                  synthesis
                      |
                      v
             persist run/results
                      |
                     END
```

The graph may conditionally skip dependency analysis when no supported manifest exists, skip coverage when no test runner is discoverable, and skip other specialists when their required inputs are unavailable. The manager should not dynamically invent arbitrary workflows in v1; it selects from a bounded set of supported specialist tasks.

### Query-time graph

```text
User question
      |
      v
Query Manager / Router
      |
      +-------------+-------------+-------------+
      |             |             |             |
     Graph        Vector          Git         Source
    Retrieval    Retrieval      History      Retrieval
      |             |             |             |
      +-------------+-------------+-------------+
                    |
                    v
             Evidence Collector
                    |
                    v
              Answer Generator
                    |
                    v
          Answer + source references
```

## 3. Finding and Evidence contracts

All specialist agents produce structured findings.

```python
class Evidence(TypedDict):
    source_type: Literal[
        "file", "line", "graph", "git", "command", "external_api"
    ]
    source: str
    location: str | None
    excerpt: str | None
    metadata: dict
```

```python
class Finding(TypedDict):
    id: str
    agent: str
    category: str
    title: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    confidence: float
    description: str
    affected_components: list[str]
    evidence: list[Evidence]
    recommendation: str | None
    deterministic_signals: dict
    status: Literal["observed", "inferred", "validated", "disputed"]
```

Rules:
- Deterministic analyzers provide facts/signals.
- Agents provide interpretation, prioritization, and recommendations.
- High-severity findings should pass evidence validation before appearing as validated findings.
- Final synthesis may only make claims that can be traced to findings/evidence or explicitly labeled inference.
- A missing data source must never be represented as a clean result.

## 4. Agent responsibilities & tools

| Agent | Tools | Output |
|---|---|---|
| Manager / Investigation | repository metadata, run configuration, prior findings | bounded investigation plan + routing decisions |
| Architecture Mapper | Python `ast`, `networkx`, Neo4j driver | module/file graph + centrality + provenance |
| Dependency Risk | manifest parser, OSV API, PyPI JSON API | dependency findings + external evidence |
| Git History & Ownership | GitPython | churn, contribution concentration, historical ownership evidence |
| Test Coverage Gap | Docker SDK, sandboxed `pytest --cov`, architecture graph | coverage metrics + coverage-risk findings |
| Finding Normalizer | schema validation, provenance checks | normalized Finding/Evidence records |
| Risk / Impact Reasoning | findings + graph metrics + deterministic signals | prioritized/correlated technical-debt findings |
| Evidence Validator | repository files, graph, git data, analyzer outputs | validated/disputed findings |
| Conflict Resolver | conflicting findings + evidence | resolved finding or explicit unresolved conflict |
| Synthesis | LangChain retrieval + pgvector + validated findings, LLM | onboarding.md + tech-debt-report.md + run diff |
| Query Manager | graph/vector/git/source retrieval tools | query plan |
| Answer Generator | retrieved evidence + validated findings, LLM | evidence-backed copilot answer |

The project should avoid making every agent an LLM agent. Deterministic analyzers remain ordinary services/tools where they are more reliable and cheaper.

## 5. Architecture graph / Neo4j model

Neo4j is the structural knowledge layer, not merely a visualization backend.

Suggested relationships:

```text
Developer ──AUTHORED──> Commit
Commit ──MODIFIED──> File
File ──CONTAINS──> Module
Module ──IMPORTS──> Module
Module ──CONTAINS──> Class
Class ──CALLS──> Function
Test ──TESTS──> Module
Module ──DEPENDS_ON──> Package
```

Node/relationship provenance should include repository revision and source location where applicable.

The graph must support queries such as:
- direct and transitive dependencies of a module
- approximate blast radius of a change
- highly central modules
- high-centrality modules with poor coverage
- modules with concentrated historical contribution
- relationships between risky components and their dependencies/tests

## 6. Sandboxing design

Test execution is the only step that runs arbitrary repository code, so it gets the strictest isolation:

- Dedicated Docker container per run.
- `--network=none`.
- CPU, memory, process-count where supported, and wall-clock limits.
- Repository mounted read-only except isolated scratch output.
- No credentials or host environment secrets.
- No host filesystem access beyond the intended repository mount.
- Worker captures stdout/stderr/coverage artifacts.
- Container is destroyed immediately after success, failure, or timeout.
- Sandbox configuration is treated as part of the security boundary and validated by an automated isolation test.

## 7. Data stores

- **Postgres** — repos, runs, job metadata, statuses, findings, evidence metadata, evaluation results.
- **Neo4j** — structural repository graph and graph-query surface.
- **pgvector** — semantic embeddings for relevant source/document chunks and generated knowledge artifacts.
- **Redis** — job queue and transient coordination.
- **Repository working directory** — immutable per-run source snapshot with lifecycle cleanup.

Avoid duplicating the same fact across stores unless there is a clear retrieval reason. Postgres is the system of record for run/finding metadata; Neo4j is the relationship store; pgvector is the semantic retrieval index.

## 8. Tech-debt prioritization

Use deterministic signals as inputs to prioritization rather than asking an LLM to invent a score.

Example signal set:

```text
centrality
change_frequency
lines_changed
coverage
dependency_severity
bus_factor_concentration
```

The prioritizer normalizes these signals, produces a priority/risk score, and records the contributing factors.

The LLM is then responsible for:
- explaining the engineering implication,
- correlating related findings,
- proposing remediation,
- identifying uncertainty.

This separation makes the ranking reproducible and auditable.

## 9. API surface

- `POST /runs` — `{repo_url | repo_path}` → `{job_id}` (202 Accepted)
- `GET /runs/{job_id}/status` — overall + per-agent status and metrics
- `GET /runs/{job_id}/results` — onboarding doc, tech-debt report, findings, evidence metadata
- `GET /runs/{job_id}/graph` — frontend-friendly graph
- `GET /repos/{repo_id}/history` — prior runs for diffing
- `GET /runs/{job_id}/findings/{finding_id}` — finding + evidence + contributing signals
- `POST /runs/{job_id}/query` — repository copilot question → evidence-backed answer

Optional later:
- `GET /runs/{job_id}/agents/{agent_name}/trace`
- `GET /evaluations/{suite_id}`

## 10. Frontend

React + TypeScript + Vite + Tailwind. Views:

1. **Overview** — run health, repository revision, major findings, analysis completeness.
2. **Graph explorer** — dependency graph; click a node to see centrality, coverage, ownership, dependencies and risk.
3. **Tech-debt report** — sortable/filterable findings with contributing signals.
4. **Finding detail** — severity, confidence, evidence, source locations, related findings.
5. **Agent trace** — agent status, timings, tool calls, retries and raw structured output.
6. **Copilot** — natural-language repository questions with source/evidence references.

## 11. Failure handling and resumability

Every specialist node has a bounded execution contract:
- transient tool failure → retry according to policy
- deterministic analyzer error → record failed status + continue where possible
- unavailable external service → mark data unavailable
- no applicable input → skipped/not-applicable
- agent timeout → terminate node and persist timeout
- interrupted workflow → resume from last checkpoint

Synthesis must explicitly report incomplete analysis instead of treating missing evidence as a negative finding.

## 12. Observability, cost and performance

- LangSmith traces are correlated to `job_id` and agent/node identifiers.
- Record latency, LLM tokens, tool calls, retries, errors and status for every agent.
- Deterministic stages should not consume LLM tokens.
- Configurable repository size, git-history window, sandbox limits, retrieval limits and LLM budget.
- Preserve partial results so a single non-critical failure does not discard completed analysis.

## 13. Evaluation strategy

Use a small fixed evaluation suite across 2–3 representative Python repositories.

Evaluation categories:
- architecture relationship accuracy
- blast-radius query accuracy
- ownership/churn accuracy
- dependency finding accuracy
- coverage-risk identification
- evidence attribution accuracy
- technical-debt prioritization agreement with expected rankings
- onboarding Q&A correctness
- unsupported-claim/hallucination rate

Include a deterministic baseline for selected tasks and compare:
1. deterministic analyzers alone,
2. deterministic analyzers + synthesis,
3. full evidence-backed agentic pipeline.

The purpose is to demonstrate that orchestration and reasoning improve the useful outcome, not merely increase system complexity.

## 14. Non-functional notes

- **Idempotency / re-runs:** re-analyzing the same repo creates a new run row linked to the same `repo_id` and revision; previous results are retained.
- **Revision awareness:** every finding and graph record is associated with the analyzed repository revision.
- **Evidence-first design:** generated prose never becomes the source of truth for repository facts.
- **Cost control:** deterministic analyzers do the bulk of extraction; LLM calls are reserved for planning, interpretation, validation, prioritization and synthesis where they add value.
- **Security:** repository code is treated as untrusted input; only the sandbox may execute it.
- **v2 extension points (not built in v1):** tree-sitter for multi-language parsing, GitHub Action / PR-comment integration, scheduled re-analysis, autonomous remediation/PR generation.
