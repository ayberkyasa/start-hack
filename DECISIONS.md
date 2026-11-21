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
