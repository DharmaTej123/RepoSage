# RepoSage — One-Page Cheat Sheet

*Day-of skim. Full detail in [INTERVIEW.md](./INTERVIEW.md), diagrams in [ARCHITECTURE.md](./ARCHITECTURE.md).*

## 30-sec pitch
Multi-agent **codebase onboarding + tech-debt copilot**. Point it at a Python repo → get a living **onboarding guide** + **tech-debt report** + an interactive **copilot**. Core principle: **evidence-driven, not prompt-driven** — deterministic analyzers gather facts, agents turn them into structured findings with provenance, important ones are validated, debt is scored deterministically, and synthesis assembles the output (claims trace to evidence or are labeled inference). Untrusted repo code runs only in a locked-down Docker sandbox.

**Positioning:** *evidence-first, LLM-optional agentic system.* The AI is the orchestration (planning manager, parallel specialists, validation/conflict/retry/resume) + classical AI (PageRank centrality, graph-traversal reasoning, vector retrieval). Runs fully today with **no LLM**; the LLM is a decoupled prose-rendering seam that can never be the source of truth.

## Stack (what + why)
- **LangGraph** — stateful, resumable agent graph (parallel fan-out, conditional skip, checkpoint resume).
- **FastAPI** — async API, Pydantic validation, 202 on submit.
- **Redis + RQ** — job queue so long analysis doesn't block the API.
- **Postgres** (SQLAlchemy/Alembic) — system of record. **Neo4j** — relationship graph. **pgvector** — semantic RAG.
- **Python `ast`** + **networkx** (centrality), **GitPython** (churn/ownership), **OSV + PyPI** via httpx (vuln/staleness), **Docker** (sandbox), **LangSmith** (traces).
- **React + TS + Vite + Tailwind** (react-flow graph).

## Agents / nodes
`ingest → manager → [architecture ‖ dependency ‖ git_history] → coverage(sandbox) → normalize → reason → synthesis → persist`
- **Manager** = *bounded* planner (fixed workflow set, enable/skip + reason) — NOT autonomous.
- **Deterministic** (no LLM): architecture, dependency, git, coverage, normalize, reason (validate→conflict→score→correlate), query routing, synthesis assembly, copilot answering. **Runs fully with no LLM / no API key today.**
- **LLM = optional seam (not wired):** rendering the structured synthesis + copilot output into fluent prose, constrained to retrieved evidence. Decoupled by design so the LLM is never the source of truth.

## State
`RunState` = TypedDict. Append-only channels (findings/metrics/errors/conflicts) use `operator.add` reducers → parallel nodes merge, don't clobber → partial results survive a failure.

## Key invariants (say these)
- **unavailable ≠ clean** · **inferred ≠ observed**
- High-severity finding must carry evidence or be marked inference.
- Risk **score is deterministic**; LLM only *explains* it.
- Repo code **only** runs in the sandbox.

## Fallbacks (quick table)
| Situation | Response |
|---|---|
| No manifest / no tests / no .git | manager skips that specialist **with a reason** |
| OSV down | mark portion **"unavailable"**, run continues |
| Docker unavailable | `UnavailableSandboxRunner` — never run code unsandboxed; coverage = unavailable |
| Sandbox timeout | kill container, status `TIMEOUT`, destroy |
| Unparsable file | log + continue (never abort) |
| Specialist throws | node `FAILED` + others preserved, synthesis notes the gap |
| Transient error | bounded retries (default 3) |
| Interrupted run | resume from LangGraph checkpoint |
| Copilot no evidence | explicit "insufficient evidence", no fabrication |

## Sandbox flags (security boundary, single source of truth `isolation_run_kwargs`)
`network_disabled + network_mode=none` · `read_only` fs · repo mounted RO + scratch tmpfs · `cap_drop=ALL` · `no-new-privileges` · cpu/mem/pids/timeout limits · non-root · always destroyed. Proven by an automated network-block test.

## Evidence model
`Finding{severity, confidence, status: observed|inferred|validated|disputed, deterministic_signals, evidence[]}` · `Evidence{source_type: file|line|graph|git|command|external_api, source, location}`.
Tech-debt signals: centrality · churn · lines_changed · coverage · dependency_severity · bus_factor → normalized score + preserved contributing signals + explanation.

## API
`POST /runs` (202) · `GET /runs/{id}/status|results|graph` · `GET /runs/{id}/findings/{fid}` · `POST /runs/{id}/query` · `GET /repos/{id}/history`. Status exposes `incomplete/failed/skipped` explicitly.

## Evaluation (proves agents earn their keep)
Offline fixtures with known ground truth → precision/recall/F1, blast-radius, ownership, finding detection, evidence attribution, Q&A correctness, **hallucination rate**. Compares **deterministic baseline vs full pipeline**; results persisted for regression.

## Top Q&A one-liners
- **AI without an LLM?** AI = agentic orchestration (planning/validation/conflict/retry/resume) + classical AI (centrality, graph traversal, retrieval). Deterministic-first by design; LLM is an optional, decoupled prose seam — not the source of truth.
- **Copilot without an LLM?** Analysis is pre-computed; per question it's `route → retrieve → format`: graph questions are computed via traversal, ownership from mined report, open-ended via vector similarity — then templated with citations. More reliable than an LLM for structured Qs; templated not conversational.
- **Why multi-agent not one prompt?** Different tool surfaces/failure modes; parallel, isolated failures, deterministic where possible, resumable, observable.
- **Anti-hallucination?** Evidence-or-inference findings → validation disputes unsupported ones → synthesis/copilot use only retrieved evidence; score is deterministic.
- **Resume?** LangGraph checkpointer replays from last completed node.
- **Living artifacts?** New run row per revision; synthesis diffs vs prior (new/changed/resolved); idempotent on same revision.
- **Limitations/next?** Python-only v1 (tree-sitter = v2); blast radius is a static-import approximation (dynamic imports surfaced honestly); v2: GitHub Action/PR comments, scheduled re-analysis, autonomous remediation.
