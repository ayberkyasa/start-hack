## D001 — Local development toolchain

- Date: 2026-11-21
- Status: adopted for T01; revisitable if subsequent integration requires a change.
- Context: the agreed stack needs repeatable installs and simple local startup.
- Decision: manage the Python application with uv and commit `backend/uv.lock`;
  manage the frontend with npm and commit `frontend/package-lock.json`. Use a root
  Makefile for setup, separate development servers, static checks, and frontend
  build. Require Python 3.12+ and Node.js 22.12+. Bind both servers to loopback.
- Alternatives: pip requirements plus a separate locking tool; pnpm; a container
  environment. These add setup choices without a current requirement.
- Consequences: contributors need uv, npm, and Make; locked install commands are
  reproducible. SQLite, providers, and run execution remain later tasks. The
  frontend uses Vite's local `/api` proxy; static preview has no API proxy.
- Affected tasks: T01, T02, T19.

## D002 — Task branches and stacked GitHub PRs

- Date: 2026-11-21
- Status: accepted by explicit user instruction.
- Context: implementation will proceed one task at a time with incremental review.
- Decision: use task-named branches (`t01`, `t02`, ...). T01 targets `main`;
  each later task starts from the preceding task branch and targets it in its PR.
  Complete checks, commit, push, and open the task's PR before stopping.
- Alternatives: independent PRs against main or one long implementation branch.
- Consequences: each PR isolates its task's diff; parent merges require checking
  the stack before further work. No automatic merging or force-pushing.
- Affected tasks: T01–T43.

## D003 — Versioned configuration snapshots

- Date: 2026-11-21
- Status: adopted for T02.
- Context: runs need comparable configuration records across restarts and secret rotations.
- Decision: keep credentials in server settings and build snapshots from a separate
  immutable public model. Hash schema-versioned, compact, sorted JSON with SHA-256.
  Include resolved limits, scenario ID, and caller-supplied code revision.
- Alternatives: hash the raw environment or record only overrides. Both make a
  run harder to reproduce when defaults or credentials change.
- Consequences: call sites can persist the exact JSON and digest together. Changes
  to the snapshot format require versioning. Initial runtime limits are local
  development defaults. Competition budgets and provider availability still need validation.
- Affected tasks: T02, T04, T15, T40.

## D004 — Transcript compatibility and evidence provenance

- Date: 2026-11-21
- Status: adopted for T03.
- Context: a remote response may gain fields or event types between practice and
  eval. A replay reader also needs to distinguish API evidence from local analysis.
- Decision: use separate local record types for observations, decisions, and
  evidence-linked assessments. Validate required fields on known remote events.
  Project unknown event types to their original type and IDs. Keep additional
  remote fields outside the typed projection.
- Alternatives: reject any wire change, or expose the entire remote payload in
  every transcript entry.
- Consequences: additive wire changes can be read without guessing their meaning.
  Future raw-response storage must retain the redacted source independently of
  these projections. Serializing a projection reconstructs only its documented fields.
- Affected tasks: T03, T05, T17.

## D005 — Local SQLite repository and process ownership

- Date: 2026-11-21
- Status: adopted for T04.
- Context: the console must reopen saved history and reject a second backend
  using the same data file. Existing domain records already define the JSON layout.
- Decision: use Python's sqlite3 module and numbered SQL migrations. Persist
  typed JSON and use generated relational keys for ownership and foreign keys.
  Keep insert batches and conditional lifecycle updates in synchronous transactions.
  Hold a committed SQLite exclusive lock in a sibling file for the backend lifetime.
- Alternatives: an ORM with separate mapped classes, a PID file requiring stale
  lock cleanup, or an exclusive lock on the data file itself.
- Consequences: the database stays readable while its backend is idle. The OS
  releases the ownership lock on process exit. Use a local filesystem and the
  same database path across restarts. Schema changes require a migration.
- Affected tasks: T04, T05.

## D006 — Timeline cursors and response identity

- Date: 2026-11-21
- Status: adopted for T05.
- Context: saved receipts can overlap or arrive again after restart. Earlier
  databases already contain typed history without public cursors.
- Decision: assign a database-wide integer sequence at insertion. Project a
  receipt before its nested events in wire order. Within a run, use the remote
  event ID for remote entries, the message or conversation ID for receipts, and
  the conversation ID plus turn count for turns. Decisions and assessments keep
  their record IDs. A repeated identity retains its first timeline entry.
- Alternatives: order by reported timestamps, use offset pagination, or allocate
  a counter per run. The database-wide cursor also works when timestamps tie.
- Consequences: per-run sequence numbers may skip numbers. Readers resume
  strictly after their last cursor. Migration 002 backfills T04 history in
  stored row order. Redacted raw responses remain separate and addressable by
  attempt ID.
- Affected tasks: T05, T17.
