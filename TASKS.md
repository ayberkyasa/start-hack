# Implementation Tasks

Work in dependency order, one requested task at a time. Check a task only after its acceptance criteria are verified; record a short completion note with the checks performed. Do not treat mock verification as live verification.

SPEC.md defines behavior; API_DOCS.md defines the remote contract. DECISIONS.md records consequential choices. Proposed defaults may be refined through explicit decision records and corresponding spec updates.

Each task should be a reviewable change. If a task grows too large, split it into stable child IDs and keep its dependencies explicit. No task authorizes live eval contacts merely by appearing in this backlog.

## Milestone A — Contracts and durable foundations

### T01 — Scaffold the application
- [x] Complete
- Depends on: none.
- Deliver: backend/frontend directories from SPEC.md, package manifests and lockfiles, development scripts, ignore rules, example environment file without secrets, basic run instructions.
- Accept: backend health endpoint and frontend shell start locally; documented commands work; no live calls occur on startup.
- Completed 2026-11-21: added FastAPI `/api/health`, React/Vite starter screen, package layout, uv/npm lockfiles, Makefile, ignore rules, and setup documentation. Recorded D001/D002 in DECISIONS.md and stacked-PR instructions in AGENTS.md.
- Verified: `make setup`, `make check`, `make build`; local backend health and Vite `/api` proxy return `{"status":"ok"}`; built preview serves HTML. Browser inspection at 1280 px and 390 px found no horizontal overflow or console errors. A guarded ASGI smoke check passes import/startup/health/shutdown with outbound sockets blocked.
- Scope: scaffold only; no runner, settings loader, live integration, or automated behavior test suite yet. No model or Target API calls were made.

### T02 — Add settings and frozen run configuration
- [x] Complete
- Depends on: T01.
- Deliver: typed settings, secret redaction, mock/practice/eval modes, configurable model/provider IDs, bounded runtime limits, local-only defaults.
- Accept: invalid/missing live configuration fails clearly; mock needs no key; configuration snapshots/hash are deterministic and exclude secret values.
- Completed 2026-11-21. FastAPI validates settings at startup. Mock starts with an empty environment. Practice and eval require a model ID and server-side keys. Versioned, frozen snapshots include limits, scenario, and code revision.
- Verified with `make check`. Eight offline tests cover startup, invalid live settings, all limit bounds, immutable snapshots, canonical serialization, and credential rotation. Credential validity and external services were not tested.

### T03 — Define domain and event contracts
- [x] Complete
- Depends on: T02.
- Deliver: typed run/session/action/attempt/conversation/observation/decision/assessment/artifact models; event discriminators; phase and terminal-reason definitions.
- Accept: fixtures cover empty observations, cross-channel replies, call greetings/turns, unknown fields, and the distinction between observed evidence and assessment.
- Completed 2026-11-21. Added typed history, run, session, action, attempt, conversation, and artifact records plus projections of message, greeting, and turn responses.
- Verified with `make check` using the synthetic library transcript. Six domain tests cover the T03 fixture cases, unknown event types, malformed known events, and JSON round trips. No live API verification.

### T04 — Establish SQLite persistence and migrations
- [x] Complete
- Depends on: T03.
- Deliver: migrations/repositories for runs, actions, attempts, events, conversations, evidence/memory, artifacts, and model usage; constraints and single-process ownership guard.
- Accept: state survives reopen; duplicate session ownership is rejected; migrations initialize a clean database; no database transaction spans a network wait.
- Completed 2026-11-21. Backend startup opens the local repository, acquires exclusive process ownership, and applies atomic schema migrations. SQLite enforces one run per session and one session per run.
- Verified with `make check`. Six storage tests use temporary files to exercise all record families across reopen, ownership collisions, atomic rollback, stale updates, failed migrations, process exit, and transaction boundaries during an async wait. No live services used.

### T05 — Implement the append-only timeline
- [x] Complete
- Depends on: T04.
- Deliver: ordered event append/query, stable local sequence, remote-ID deduplication, synthetic-observation deduplication, redacted raw-response storage.
- Accept: reprocessing a response does not duplicate timeline entries; pagination has no gaps; action/checkpoint/event changes can commit atomically.
- Completed 2026-11-21. Added migration 002, a run-scoped cursor reader, remote and synthetic deduplication, a redacted response archive keyed by attempt, and one transactional batch for history and lifecycle updates.
- Verified with `make check`. Six timeline tests cover v1 backfill, replay after reopen, overlapping remote events, pagination during append, redaction, and atomic rollback. All checks used local fixtures.

### T06 — Build deterministic Target API fixtures
- [ ] Complete
- Depends on: T03.
- Deliver: client protocol and mock implementation for discovery, sessions, messages, calls, pages, assets, history, and closure.
- Accept: scripted multi-contact fixtures cover reply, silence, another-channel reply, field submission, call termination, limits, and idempotent repeated contacts; mock execution has no network dependency.

## Milestone B — Remote adapter and safe execution

### T07 — Implement discovery and session read operations
- [ ] Complete
- Depends on: T02, T03, T06.
- Deliver: asynchronous real adapter for scenarios, channels, sessions, session detail, and event history; typed error normalization and timeout configuration.
- Accept: transport fixtures verify exact API paths/authentication and locked-scenario handling; secrets are redacted; no invented endpoints.

### T08 — Implement message and conversation operations
- [ ] Complete
- Depends on: T07.
- Deliver: message send, conversation start, turn, and end methods; idempotency header support; full response capture.
- Accept: HTTP fixtures match API_DOCS.md and retain greetings, persona_says, events, turns_used, and ended flags; declared attachments are supported.

### T09 — Implement session and artifact mutations
- [ ] Complete
- Depends on: T07.
- Deliver: session create/end, page registration, asset upload, operation-specific retry/reconciliation metadata.
- Accept: page replacement and unused eval-session reuse fixtures are represented accurately; unsupported idempotency guarantees are never assumed.

### T10 — Implement the shared request scheduler
- [ ] Complete
- Depends on: T07, T08, T09.
- Deliver: per-session serialization, team concurrency/rate limits, practice-session creation throttle, bounded backoff and Retry-After handling.
- Accept: fake-clock/concurrency tests show reads, writes, uploads, cleanup, and retries respect applicable limits; one slow session does not corrupt another.

### T11 — Implement durable outbound actions
- [ ] Complete
- Depends on: T04, T05, T08, T10.
- Deliver: immutable payload/key before send; attempt log; prepared/in-flight/unknown/resolved transitions; atomic response/checkpoint persistence.
- Accept: accepted-then-timeout retry uses identical payload/key and yields one logical contact; a changed payload requires a new action after resolution.

### T12 — Recover pending operations and session creation
- [ ] Complete
- Depends on: T09, T11.
- Deliver: startup recovery, server reconciliation, remote-session uniqueness, operation-specific handling of unacknowledged creation/upload/closure.
- Accept: injected crashes before send, after acceptance, and around commit preserve history without duplicate contacts; ambiguous eval creation blocks instead of opening another session.

## Milestone C — First complete run and visible transcript

### T13 — Implement budgets and legal runner transitions
- [ ] Complete
- Depends on: T03, T04, T10, T12.
- Deliver: session owner, persisted phases, deadline/contact/turn/research/model/iteration counters, stop reasons, graceful abort and closure state.
- Accept: no action runs in an illegal phase or beyond a cap; unresolved requests block new planning; abort preserves uncertain outcomes and starts no new contacts.

### T14 — Build the runner with a scripted planner
- [ ] Complete
- Depends on: T06, T11, T13.
- Deliver: preparation, session mapping, action loop, observation normalization, continuation, and finish using deterministic planner decisions.
- Accept: a mock message/reply/follow-up completes autonomously; silence remains visible; restart resumes the same session rather than restarting the story.

### T15 — Expose run command and query endpoints
- [ ] Complete
- Depends on: T14.
- Deliver: local launch/list/detail/timeline/abort endpoints, duplicate-launch protection, server-owned execution independent of browser connections.
- Accept: repeated launch request IDs create one run; direct requests cannot mutate a frozen configuration; disconnected clients do not stop the runner.

### T16 — Build the console shell and run launcher
- [ ] Complete
- Depends on: T01, T15.
- Deliver: three-column layout, run list, mode labels, configuration form, launch/status/abort controls, empty/error states.
- Accept: user launches a mock run and selects saved runs; invalid configuration is readable; no per-contact send/edit/approve control exists.

### T17 — Add resumable SSE delivery
- [ ] Complete
- Depends on: T05, T15.
- Deliver: persisted event stream, cursor/Last-Event-ID handling, heartbeat, history/live handoff, client reconnection logic.
- Accept: disconnect/reconnect during event creation produces an ordered timeline without missing/duplicate events; stream failure does not affect execution.

### T18 — Render the live exchange
- [ ] Complete
- Depends on: T16, T17.
- Deliver: outbound contacts, replies, no-visible-response entries, events, sender/channel metadata, waiting time, budget and usage display.
- Accept: complete mock exchange remains intact after refresh; prepared/unsent actions differ from sent messages; observations differ from assessments.

Milestone gate: start one mock run, watch an autonomous follow-up, refresh, and read the entire saved exchange. This gate does not establish real simulator effectiveness.

## Milestone D — Evidence, memory, and autonomous planning

### T19 — Add the model-provider contract and OpenAI adapter
- [ ] Complete
- Depends on: T02, T03, T04.
- Deliver: structured request/result interface, configurable model IDs, refusal/incomplete/error handling, bounded provider retries, token/latency/cost records.
- Accept: provider fixtures cover all result variants and frozen fallback order; unknown cost is not zero; failures cannot mutate a submitted action. Verify current official API contracts during implementation.

### T20 — Implement read-only research and evidence storage
- [ ] Complete
- Depends on: T04, T19.
- Deliver: public research adapter, source caching, factual extraction with provenance/dates/identity, conflicting/unavailable source handling, retrieval limits.
- Accept: fixture sources produce attributable facts; unsupported claims remain unverified; private-network URLs/redirects and credential forwarding are rejected.

### T21 — Implement the session continuity ledger
- [ ] Complete
- Depends on: T04, T05, T20.
- Deliver: distinct public facts, generated claims, target statements, commitments, identities, and unanswered questions with origin references.
- Accept: cross-channel exchanges retain commitments; new sessions do not inherit relationships; a generated claim never becomes a verified fact without evidence.

### T22 — Implement hypothesis tracking and context assembly
- [ ] Complete
- Depends on: T20, T21.
- Deliver: hypothesis evidence/status history, evidence-linked context construction, bounded summaries with access to underlying records.
- Accept: silence does not become proof of a hidden state; contradictory evidence weakens a hypothesis; context limits preserve critical questions/commitments and raw history.

### T23 — Implement the typed planner and composer
- [ ] Complete
- Depends on: T13, T19, T22.
- Deliver: evidence-based target/objective selection and legal next-action decisions, expected observations, brief summaries, composition, versioned prompts.
- Accept: varied unseen synthetic dossiers produce schema-valid decisions without persona-specific branches; responses address outstanding questions; research/planning loops are bounded.

### T24 — Implement deterministic and semantic validation
- [ ] Complete
- Depends on: T09, T21, T23.
- Deliver: payload/domain/budget/artifact checks; continuity and factuality review; bounded repair/reselection with recorded reasons.
- Accept: unsupported facts, contradictions, bad URLs, wrong channels, illegal domains, and simulator-directed instructions are rejected or repaired; exhausted repairs terminate predictably.

### T25 — Implement observation assessment and stop policy
- [ ] Complete
- Depends on: T21, T22, T23.
- Deliver: evidence-linked provisional outcomes, hypothesis/ledger updates, configured stop thresholds, no-useful-continuation detection.
- Accept: link open is not automatically a win; submitted field names are retained without values; suspected disclosure references exact reply evidence; no official score is fabricated.

### T26 — Connect the autonomous message loop
- [ ] Complete
- Depends on: T14, T23, T24, T25.
- Deliver: replace scripted decisions with the complete research/plan/compose/validate/execute/observe loop; retain deterministic test adapters.
- Accept: synthetic runs handle questions, silence, objections, conflicting facts, and provider failures without human assistance or unbounded loops.

### T27 — Implement the live-conversation inner loop
- [ ] Complete
- Depends on: T08, T13, T24, T25, T26.
- Deliver: active call state, greeting/turn persistence, next-turn or end decisions, shared memory, turn/deadline enforcement, turn attachments.
- Accept: call uses one touch, respects ten turns and ended=true, can end early, and resumes safely after an uncertain turn; accidental replacement calls are rejected.

### T28 — Run a controlled real-practice smoke test
- [ ] Complete
- Depends on: T18, T26, T27.
- Deliver: documented opt-in practice-run command/workflow, one authorized real run, saved redacted trace and discrepancy report.
- Accept: same application path works against the real API; remote touch counts and local history agree; no eval session is touched. Requires credentials and explicit scope to run practice, not just tests.

## Milestone E — Artifacts, inspection, and replay

### T29 — Add artifact versions and prerequisite execution
- [ ] Complete
- Depends on: T04, T09, T24, T26.
- Deliver: local immutable page versions, asset reuse by known hash/ID, registration state, dependency handling before contact dispatch.
- Accept: exact linked page exists in the current session before send; replacement retains old snapshots; unknown upload outcomes are not assumed safe to repeat.

### T30 — Add email and registered-page templates
- [ ] Complete
- Depends on: T29.
- Deliver: personal-note, service-notification, and page templates; escaped variables; inline styles and uploaded assets; declared attachment handling.
- Accept: templates have no placeholders, scripts, external images, or functional credential collection; sender format and actual destination remain visible and consistent.

### T31 — Add safe artifact previews
- [ ] Complete
- Depends on: T16, T29, T30.
- Deliver: sandboxed email/page previews at documented widths, sender/subject/URL presentation, local asset resolution.
- Accept: visually inspect representative renders; script execution, form submission, navigation, and external requests are blocked; selected historical versions render correctly.

### T32 — Add evidence and decision inspectors
- [ ] Complete
- Depends on: T18, T21, T22, T25.
- Deliver: evidence/source links, hypothesis status, commitments/questions, decision summaries, redacted payload/response/error details.
- Accept: every displayed assessment can link to evidence; verified facts and claims remain distinct; no hidden-state or official-score claims appear.

### T33 — Add conversation presentation
- [ ] Complete
- Depends on: T18, T27.
- Deliver: call contact groups with greetings/turns/events/hang-up, independent turn and touch counters, waiting states.
- Accept: replaying a call matches the stored sequence and shows one touch; cross-channel follow-up appears in the same session chronology.

### T34 — Add read-only replay and redacted export
- [ ] Complete
- Depends on: T31, T32, T33.
- Deliver: timeline stepping, playback speed, historical inspectors, portable redacted run package with version and evidence metadata.
- Accept: replay works with model/Target API access disabled; refresh retains selection; exports omit secrets and distinguish mock from real data.

### T35 — Add practice comparison and metrics
- [ ] Complete
- Depends on: T25, T34.
- Deliver: comparison by configuration/version, provisional outcome evidence, contacts, duration, factual/continuity issues, failures, token/cost usage.
- Accept: failures and repeated runs remain visible; no fabricated score or unexplained cost is shown; source records back every metric.

## Milestone F — Robustness, generalization, and delivery

### T36 — Complete the fault-injection regression suite
- [ ] Complete
- Depends on: T12, T17, T27, T29, T34.
- Deliver: integration coverage for crash windows, delayed/duplicate responses, timeout after acceptance, transient/permanent errors, abort races, session ambiguity, budget limits, and SSE reconnect.
- Accept: required recovery invariants in SPEC.md pass; unresolved outcomes are explicit; no duplicate contact or accidental eval replacement occurs.

### T37 — Evaluate generalization and freeze a baseline
- [ ] Complete
- Depends on: T28, T35, T36.
- Deliver: versioned synthetic evaluation set plus authorized repeated practice runs; rotating two-persona development/one-persona holdout report; limitations and regression findings.
- Accept: frozen configuration runs on held-out profiles unchanged; report includes failures, wrong facts, continuity, contacts, duration, and costs. Do not claim broad generalization from three founders.

### T38 — Verify eval execution locks and readiness
- [ ] Complete
- Depends on: T24, T29, T36, T37.
- Deliver: server-enforced immutable configuration, explicit run-launch boundaries, refusal of mid-run edits, validated fallback/domain/budget policy, readiness checklist using actual scenario status.
- Accept: direct API attempts cannot steer scored messages; unused session reuse is handled; closed eval prevents dispatch; completion/failure never silently starts another run.

### T39 — Prepare the architecture page and five-minute demo
- [ ] Complete
- Depends on: T34, T37.
- Deliver: one-page architecture, pitch outline, selected complete real replay, clearly labeled offline development fixture, documented startup/export instructions.
- Accept: rehearse within five minutes; explain evidence, adaptation, recovery, and outcomes; saved real thread plays without a live network dependency.

### T40 — Execute the authorized scoring runs
- [ ] Complete
- Depends on: T38, T39.
- Deliver: explicitly launched scoring runs within organizer window, preserved configurations/transcripts/artifacts, end-state records, final demo selection.
- Accept: no human messages/edits/approvals during runs; server run allowance respected; all records retained; official judgments distinguished from local assessments.
- Gate: only execute when the user authorizes scoring and the actual scenario is open. This task is not part of ordinary coding verification.

## Optional follow-up — AMD inference

### T41 — Identify AMD hardware and choose a workload
- [ ] Complete
- Depends on: T19.
- Deliver: actual credit provider/GPU/VRAM/OS/ROCm information, compatible serving options, one bounded proposed workload and evaluation set.
- Accept: record confirmed facts and unknowns; model sizing is justified by actual hardware; no assumption that all AMD GPUs support the same stack.

### T42 — Implement and benchmark the AMD adapter
- [ ] Complete
- Depends on: T22, T25, T35, T41.
- Deliver: isolated inference adapter, deployment instructions, capability/error normalization, saved-example benchmark against the baseline.
- Accept: compare factual quality, schema validity, latency, and cost; an unavailable GPU does not break the baseline; provider-specific limitations are explicit.

### T43 — Adopt a measured hybrid policy if justified
- [ ] Complete
- Depends on: T37, T42.
- Deliver: decision record adopting or rejecting the workload, frozen routing/fallback policy if adopted, regression report.
- Accept: adoption preserves generalization/recovery checks and provides a measured benefit; reject/defer otherwise. Re-run eval-readiness checks if execution changes.

## Completion record convention

Under a completed task add a short dated note: implementation references, checks run, result, and any unresolved limitation. Never mark live-run tasks complete on mocked results. Keep task IDs stable. When a consequential choice is made, link its DECISIONS.md record and update SPEC.md if behavior changes.
