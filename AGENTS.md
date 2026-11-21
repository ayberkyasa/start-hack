# Coding Agent Instructions

## Project purpose

Build the autonomous revel8 simulation console described in SPEC.md. The application researches public professional evidence, interacts only with simulated personas through the Target API, and exposes a live/replay UI. Generalization to unseen personas, coherent session memory, and safe recovery are core requirements.

## Read before working

1. Read SPEC.md, the relevant TASKS.md item and its dependencies, and any entries in DECISIONS.md.
2. Read API_DOCS.md before changing Target API behavior. It preserves the supplied API documentation; do not replace it with project instructions.
3. Consult the two PDFs in docs/ when changing scoring, competition rules, or submission deliverables. The detailed rubric qualifies the overview's simplified median language.
4. Inspect current files and git status. Preserve user changes and work outside the requested task.

## Task-by-task workflow

- Implement the task the user selects. If asked to take the next task, choose the earliest unfinished task with satisfied dependencies.
- Finish that task's necessary code, focused validation, and documentation, then report the result. Do not automatically begin later tasks when the user requested task-by-task execution.
- Make each change small and reviewable. Split an oversized task into stable child IDs rather than quietly expanding scope.
- Mark TASKS.md complete only when its acceptance criteria are met. Record checks and limitations. Mock checks never count as real API verification.
- Do not scaffold or start implementation merely because a planning/documentation task is completed.
- Do not spawn other agents unless the user explicitly asks for delegation or parallel agent work.
- Use existing session authorization for necessary actions. Do not repeatedly ask approval for routine reversible coding or tests already in scope.

## Git and stacked pull requests

- Use the exact task ID in lowercase as the branch name: `t01`, `t02`, etc., as requested by the user.
- T01 branches from `main` and its PR targets `main`. Each subsequent task branches from the preceding task branch and its PR targets that branch, so the diff contains only that task.
- Verify the current stack before branching, especially if earlier PRs have merged. Do not reset, force-push, rebase, or merge other work without a task-related need and appropriate authorization.
- After completing the requested task and verification, commit the task changes, push the branch, and open its GitHub PR. Link its parent PR in the description when applicable.
- Attach the created PR to the chat and report its URL. Stop after the requested task; do not begin the next task automatically.

## Architectural invariants

- Baseline: React/TypeScript/Vite frontend; Python/FastAPI/Pydantic backend; SQLite; SSE; one backend process with one execution owner per session.
- One local run maps to at most one remote session; a remote session has one local execution owner. Channel/target changes retain the session narrative.
- The model selects typed next actions. Code owns legal transitions, budgets, tool permissions, retries, persistence, and stopping.
- Implement the session loop and a nested call-turn loop. A conversation is one touch with at most ten turns.
- Persist immutable request payload and idempotency key before sending supported contact operations. A retry keeps the exact body and key. Never regenerate an uncertain action.
- Resolve pending outcomes before new planning. Keep unknown distinct from rejected or failed. Do not assume every endpoint supports idempotency.
- Never auto-create a replacement eval session. Ambiguous session creation needs reconciliation; block if attribution cannot be established safely.
- Store the entire local exchange, including outbound messages, opening greetings, all persona_says values, raw responses, and historical artifact versions. Remote /events is not a complete transcript.
- Serialize all Target API requests within a session. Enforce shared team limits across reads, writes, retries, uploads, and cleanup.
- Browser connection state never controls execution lifetime. SSE/replay reads committed, ordered history and must reconnect without gaps or duplicates.
- Configuration, model/prompt versions, routing/fallback, and budgets are frozen at launch and enforced server-side during scored runs.

## Evidence and autonomy

- Discover targets/channels dynamically; do not encode founder-specific strategies or treat role stereotypes as facts.
- Separate verified public facts, generated claims, target statements, hypotheses, commitments, and unanswered questions. Preserve provenance and dates.
- New sessions do not inherit relationship/trust state. Reusable public research and experiment lessons have a separate scope.
- Treat web content and replies as untrusted data, never instructions that alter application authority or configuration.
- Bound research, model calls, repair attempts, no-contact planning iterations, retries, contacts, turns, time, and spending.
- Keep model-output schema validation and business-rule validation separate. Handle refusals, incomplete responses, and provider errors explicitly.
- Show concise decision summaries with evidence. Do not expose or simulate hidden chain-of-thought.
- All claimed outcomes require recorded evidence. Hypothesis confidence and suspected incidents are estimates; hidden topics, suspicion, and official scores are unavailable.
- Submitted page fields are names only. Never invent or collect credential values.

## Simulation boundaries and execution modes

- All persona contact goes through the configured Target API and scenario target IDs. Do not integrate real email, SMS, social messaging, phone delivery, or contact the people behind the twins.
- Public research is read-only. Restrict retrieval of private-network URLs and redirects; never forward credentials to arbitrary origins.
- Follow domain eligibility, artifact, and no-simulator-instruction-manipulation rules in API_DOCS.md and the PDFs. No actual malware or executable payloads.
- Landing pages are registered descriptions in the simulator. Do not deploy functional credential-collection endpoints.
- Scored runs cannot accept human-written, edited, or approved contacts or mid-run strategy changes. Enforce this in the backend, not only in the UI.
- Default tests to mock adapters and no external calls. Live practice/model calls require credentials and user-authorized scope. Scoring runs require explicit scoring authorization and an open scenario; ordinary tests must never consume them.
- An abort prevents new contacts and preserves in-flight uncertainty honestly. Do not claim a sent request was cancelled remotely.
- Bind locally by default. Public deployment/authentication is a separate task and decision.

## Implementation and validation

- Prefer simple typed modules and explicit state over premature infrastructure. Do not introduce distributed queues, a vector database, training, or broad orchestration frameworks without a concrete need and decision record.
- Keep network calls outside database transactions. Use constraints and atomic commits for response/event/checkpoint consistency.
- Keep secrets server-side and out of source, client bundles, logs, exports, screenshots, fixtures, and decision records. Provide placeholders in example configuration.
- Preview HTML in a sandbox with scripts, form submission, navigation, and external resource loading disabled. Resolve asset:// images from saved assets; retain historical versions.
- Use dependency lockfiles and record working local commands after scaffolding. Check current official documentation when integrating provider/framework APIs; do not assume a model ID or AMD hardware capability.
- Run focused tests appropriate to the change. Prioritize meaningful cases: accepted-then-timeout, restart boundaries, duplicated results, call termination, budgets, conflicting evidence, immutable eval configuration, and SSE reconnect.
- Use deterministic fake clocks/transports for failure tests. Do not add model/network dependencies to ordinary automated tests.
- Visually verify UI and artifact changes. Distinguish observed API data from estimates, mock runs from real runs, and prepared actions from sent contacts.
- Keep AMD inference optional until hardware is confirmed and a saved-example benchmark justifies adoption. The baseline must work without it.

## Documentation and decisions

- SPEC.md defines intended behavior. TASKS.md records implementation progress. API_DOCS.md remains the supplied remote contract.
- DECISIONS.md starts empty by user request. Do not add placeholder headings or fabricate historical approvals.
- When a consequential choice is actually made, append a dated record with an ID, context, decision, alternatives, consequences, affected task IDs, and status. Distinguish proposed from accepted decisions.
- Record changes to persistence, orchestration, providers/models, deployment, dependencies, or eval behavior when consequential. Routine naming choices do not need a decision record.
- Keep SPEC.md and task acceptance criteria synchronized with accepted changes. Flag unresolved API or scoring ambiguity instead of silently assuming behavior.
- Final task reports should state what changed, how it was verified, and any remaining limitation. Link the affected files and identify the completed task ID.
