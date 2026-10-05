# Requirements — RepoSage (Codebase Onboarding & Tech-Debt Copilot)

## Product summary

A multi-agent system that ingests a Git repository and produces two living artifacts: an **onboarding guide** (architecture map, suggested reading order, ownership) and a **tech-debt report** (dependency risk, test-coverage gaps on high-centrality code, ownership/bus-factor risk). Re-running analysis on a repo updates both artifacts, so they stay current as the codebase changes — this is what separates it from a one-off static-analysis script.

RepoSage is deliberately **evidence-driven**: deterministic analyzers collect repository facts, specialist agents turn those facts into structured findings, an evidence-validation stage checks important conclusions against repository evidence, and synthesis produces the final artifacts. The system should demonstrate useful agentic behavior without requiring every analysis step to be an LLM call.

v1 scope: single-language (Python) repos. Multi-language (via tree-sitter) is a documented v2 extension, not a v1 requirement.

---

## 1. Repository Ingestion

**User story:** As a developer, I want to point the system at a Git repository so that it can be analyzed without manual setup.

- WHEN a user submits a repository URL or uploads a local path, THE SYSTEM SHALL clone/copy the repository into an isolated working directory before any analysis begins.
- IF the repository exceeds a configured size limit, THEN THE SYSTEM SHALL reject the job with a clear error rather than attempting analysis.
- WHEN ingestion completes, THE SYSTEM SHALL detect the primary language(s) and package manifest files present (requirements.txt, pyproject.toml, package.json) and record them in run metadata.
- IF the repository has no detectable Python entry points or manifest, THEN THE SYSTEM SHALL fail the job with a message stating v1 supports Python repositories only.
- THE SYSTEM SHALL record repository metadata including commit/HEAD identifier, repository size, detected language, detected manifests, and ingestion timestamp.
- THE SYSTEM SHALL make the repository snapshot associated with a run immutable so all findings can be traced to the analyzed revision.

## 2. Architecture Mapping Agent

**User story:** As a new engineer, I want a map of how modules depend on each other so I know what to read first.

- WHEN ingestion completes, THE SYSTEM SHALL parse the codebase's import graph using AST analysis and build a directed module-dependency graph.
- THE SYSTEM SHALL compute a centrality score per module (e.g. in-degree/PageRank-style) representing how many other modules depend on it.
- WHEN the graph is built, THE SYSTEM SHALL persist nodes and edges to the graph store so downstream agents and the frontend can query it.
- IF a module cannot be parsed (syntax error, dynamic imports THE SYSTEM cannot resolve), THEN THE SYSTEM SHALL log it as unparsed and continue rather than aborting the whole run.
- THE SYSTEM SHALL capture available file, module, class, function, import, and test relationships where they can be determined reliably.
- THE SYSTEM SHALL expose graph queries sufficient to determine direct/indirect dependencies and approximate change blast radius.
- THE SYSTEM SHALL retain provenance for graph relationships, including the source file and relationship type.

## 3. Dependency Risk Agent

**User story:** As a maintainer, I want to know which dependencies are vulnerable or abandoned so I can prioritize upgrades.

- WHEN a manifest file is detected, THE SYSTEM SHALL extract the full list of direct dependencies and pinned versions.
- WHEN the dependency list is extracted, THE SYSTEM SHALL query a public vulnerability database (OSV) for each dependency version and record any matching CVEs with severity.
- THE SYSTEM SHALL flag a dependency as "stale" WHERE its last published release is older than a configurable threshold (default 18 months).
- IF the vulnerability API is unreachable, THEN THE SYSTEM SHALL mark that portion of the report as "unavailable" rather than silently omitting it or failing the whole run.
- THE SYSTEM SHALL distinguish direct dependencies from transitive dependencies when dependency metadata permits.
- THE SYSTEM SHALL preserve external-source provenance for vulnerability and release-date findings.
- THE SYSTEM SHALL distinguish "no vulnerability found" from "vulnerability data unavailable."

## 4. Git History & Ownership Agent

**User story:** As an engineering manager, I want to see ownership concentration and churn hotspots so I can spot bus-factor risk.

- WHEN ingestion completes, THE SYSTEM SHALL mine commit history to compute, per module: primary author(s), commit count in the last 12 months, and last-modified date.
- THE SYSTEM SHALL compute a churn score per module based on commit frequency and lines changed.
- THE SYSTEM SHALL flag a module as "bus-factor risk" WHERE a single author accounts for more than a configurable percentage (default 80%) of its recent commits.
- WHILE mining history on repositories with a very long commit log, THE SYSTEM SHALL cap analysis to a configurable recent window (default 2 years) to bound runtime.
- THE SYSTEM SHALL retain author-to-module and commit-to-file/module relationships needed for historical ownership queries.
- THE SYSTEM SHALL distinguish primary contributor concentration from absolute ownership, since git history is evidence of historical contribution rather than a formal ownership declaration.
- THE SYSTEM SHALL support identifying high-churn modules and modules with unusually concentrated historical contribution.

## 5. Test Coverage Gap Agent

**User story:** As a maintainer, I want to know which high-importance modules are under-tested so I can prioritize test-writing effort.

- WHEN the architecture graph and centrality scores are available, THE SYSTEM SHALL execute the repository's test suite inside an isolated sandbox with coverage instrumentation enabled.
- WHEN coverage results are produced, THE SYSTEM SHALL cross-reference per-module coverage percentage against that module's centrality score from the Architecture Mapping Agent.
- THE SYSTEM SHALL flag a module as a "coverage gap risk" WHERE it has above-median centrality AND below a configurable coverage threshold (default 50%).
- IF the test suite fails to run (missing dependencies, no discoverable test runner), THEN THE SYSTEM SHALL report coverage analysis as skipped with a reason, and continue producing the rest of the report.
- THE SYSTEM SHALL record test-run status, exit code, duration, coverage artifact location, and skip/failure reason.
- THE SYSTEM SHALL distinguish low coverage from unavailable coverage.

## 6. Sandboxed Execution Safety

**User story:** As an operator, I want untrusted repository code to never run with access to the host system or network.

- WHEN the Test Coverage Gap Agent executes repository code, THE SYSTEM SHALL run it inside a container with no outbound network access and a resource/time limit.
- IF a sandboxed run exceeds its time limit, THEN THE SYSTEM SHALL terminate it and record a timeout rather than allowing indefinite execution.
- THE SYSTEM SHALL NOT execute any repository code outside the sandbox at any stage of analysis.
- THE SYSTEM SHALL mount repository content read-only where practical and provide only an isolated writable scratch area for generated artifacts.
- THE SYSTEM SHALL prevent access to host credentials, environment secrets, and unrelated host filesystem paths.
- THE SYSTEM SHALL destroy the sandbox after execution completes, fails, or times out.

## 7. Evidence Model & Specialist Findings

**User story:** As a maintainer, I want every important recommendation to be explainable from repository evidence rather than unsupported LLM output.

- THE SYSTEM SHALL define a common structured `Finding` model containing category, title, severity, confidence, description, affected components, recommendation, and evidence references.
- THE SYSTEM SHALL define an `Evidence` model that can reference files/lines, graph relationships, git history, deterministic command output, or external API results.
- EACH specialist agent SHALL produce structured findings rather than free-form prose as its primary output.
- EACH finding with a severity or recommendation SHALL include one or more evidence references unless the finding is explicitly marked as an inference.
- THE SYSTEM SHALL retain provenance from raw analyzer output through specialist findings and final synthesized claims.
- THE SYSTEM SHALL distinguish observed facts from agent inference and recommendation.

## 8. Agentic Investigation & Orchestration

**User story:** As a user, I want the system to decide which analyses are needed and coordinate independent specialists without making every step an LLM call.

- THE SYSTEM SHALL use a Manager/Investigation Agent to determine which specialist analyses are applicable based on repository characteristics and the user's objective.
- THE SYSTEM SHALL support parallel execution of independent specialist analyses.
- THE SYSTEM SHALL allow a specialist to be skipped when its required input or tool is unavailable, with an explicit reason.
- THE SYSTEM SHALL support evidence validation for high-severity or high-confidence findings.
- WHEN specialist findings conflict, THE SYSTEM SHALL preserve both findings and invoke a bounded conflict-resolution step rather than silently selecting one.
- THE SYSTEM SHALL support bounded retries for transient tool failures.
- THE SYSTEM SHALL checkpoint run state so an interrupted run can resume without rerunning completed stages.
- THE SYSTEM SHALL distinguish tool failure, agent failure, "no finding", and "not applicable" states.
- THE SYSTEM SHALL expose per-agent status, timing, tool-call count, retry count, and error information.

## 9. Tech-Debt Prioritization

**User story:** As a maintainer, I want technical debt ranked by engineering impact rather than by isolated warning counts.

- THE SYSTEM SHALL combine deterministic signals such as centrality, churn, coverage, dependency severity, and bus-factor concentration into a normalized risk/priority model.
- THE SYSTEM SHALL preserve the individual contributing signals for every prioritized finding.
- THE SYSTEM SHALL explain why an issue received its priority rather than exposing only a final score.
- THE SYSTEM SHALL identify correlated findings that affect the same component or risk area where practical.
- THE SYSTEM SHALL avoid double-counting multiple observations that represent the same underlying issue.
- THE SYSTEM SHALL distinguish deterministic score components from LLM-generated interpretation.

## 10. Synthesis Agent (Onboarding Doc + Tech-Debt Report)

**User story:** As a new engineer or maintainer, I want a single readable document instead of four raw JSON reports.

- WHEN all applicable upstream agents have completed, failed, or reported a skip reason, THE SYSTEM SHALL synthesize an onboarding guide containing: architecture overview, a suggested reading order derived from centrality + low churn, module ownership, important dependencies, and known high-risk areas.
- WHEN all applicable upstream agents have completed, THE SYSTEM SHALL synthesize a tech-debt report ranking issues by combined severity and engineering impact.
- THE SYSTEM SHALL cite which agent/data source backs each claim in the synthesized documents (no unattributed findings).
- THE SYSTEM SHALL distinguish unavailable analysis from a clean result.
- WHERE a repository is re-analyzed, THE SYSTEM SHALL diff the new tech-debt report against the previous run and highlight newly introduced, changed, and resolved issues.
- THE SYSTEM SHALL preserve the previous run rather than overwriting it.

## 11. Repository Knowledge & Interactive Copilot

**User story:** As a developer joining an unfamiliar repository, I want to ask questions about the codebase and receive evidence-backed answers.

- THE SYSTEM SHALL index relevant code and documentation chunks for semantic retrieval.
- THE SYSTEM SHALL support natural-language repository questions after an analysis run completes.
- THE SYSTEM SHALL route queries to the appropriate retrieval mechanism (graph, vector, git history, source files, or a combination) based on the question.
- THE SYSTEM SHALL support graph-aware questions such as "what depends on X?" and "what is the likely blast radius of changing X?"
- THE SYSTEM SHALL support ownership/history questions such as "who has historically worked on X?"
- THE SYSTEM SHALL support onboarding questions such as "what should I read first?" and "how does this request flow through the system?"
- THE SYSTEM SHALL provide evidence/file references with answers.
- THE SYSTEM SHALL preserve short-term conversation/session state for follow-up questions.

## 12. Job Orchestration & Status Tracking

**User story:** As a user, I want to trigger an analysis run and check its progress without blocking.

- WHEN a user submits a repository for analysis, THE SYSTEM SHALL create a job record and return a job ID immediately rather than blocking until completion.
- WHILE a job is running, THE SYSTEM SHALL expose per-agent status (pending/running/complete/failed/skipped) via a status endpoint.
- WHEN a job completes, THE SYSTEM SHALL persist the onboarding guide, tech-debt report, and raw per-agent outputs, retrievable by job ID.
- IF an agent fails, THEN THE SYSTEM SHALL mark only that agent as failed and allow the Synthesis Agent to proceed with the remaining outputs plus a note of what's missing.
- THE SYSTEM SHALL support resumable runs using persisted checkpoints.
- THE SYSTEM SHALL ensure repeated requests for the same repository revision can be handled idempotently according to a documented policy.

## 13. Frontend Visualization

**User story:** As a user, I want to explore the architecture graph and reports visually, not just read raw markdown.

- WHEN a job completes, THE SYSTEM SHALL render the module-dependency graph as an interactive visualization (zoom, click-to-inspect module detail).
- THE SYSTEM SHALL display the tech-debt report as a sortable/filterable list (by severity, module, category).
- THE SYSTEM SHALL display per-agent trace information so a user can see which agent produced which finding and its evidence.
- THE SYSTEM SHALL show the evidence/provenance behind an individual finding.
- THE SYSTEM SHALL allow a user to inspect why a module was ranked as high risk, including its contributing metrics.
- THE SYSTEM SHALL provide an interactive question interface for the Repository Knowledge & Copilot capabilities.

## 14. Evaluation & Quality

**User story:** As an Agentic AI engineer, I want to demonstrate that the multi-agent architecture improves useful outcomes and does not merely add orchestration complexity.

- THE SYSTEM SHALL include a small evaluation suite of known repository questions and expected answers/findings across representative Python repositories.
- THE SYSTEM SHALL evaluate architecture relationship accuracy, finding precision/recall, evidence attribution accuracy, and onboarding Q&A correctness.
- THE SYSTEM SHALL track hallucination/unsupported-claim rate for synthesized findings and copilot answers.
- THE SYSTEM SHALL compare at least one deterministic-only baseline with the agentic/evidence-backed pipeline for selected tasks.
- THE SYSTEM SHALL record evaluation results so architectural changes can be compared over time.

## 15. Observability, Cost & Performance

**User story:** As an operator, I want to understand where a run spends time, tokens, and compute.

- THE SYSTEM SHALL trace LangGraph execution with a correlation identifier linked to `job_id`.
- THE SYSTEM SHALL record per-agent latency, LLM token usage, tool calls, retries, and errors where applicable.
- THE SYSTEM SHALL make it possible to identify which stages are deterministic and which stages require LLM reasoning.
- THE SYSTEM SHALL support configurable limits for repository size, history window, sandbox runtime, and LLM context/cost.
- THE SYSTEM SHALL preserve partial results when a non-critical stage fails.
