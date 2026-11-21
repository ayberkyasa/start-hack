# Autonomous Simulation Console

A local workspace for the revel8 challenge. The planned agent researches public
evidence, interacts with simulated personas through the Target API, and records
its exchanges for observation and replay.

## Current implementation

T01 provides the Python/FastAPI application, a React/TypeScript/Vite starter screen,
and reproducible development commands. The only application endpoint is
`GET /api/health`, returning `{"status":"ok"}`. FastAPI also exposes its generated
documentation at `/docs`.

The backend validates configuration at startup. The default mock mode needs no
credentials. The frontend remains a static starter screen. Startup in every mode
is local and makes zero external requests.

## Backend configuration

For local overrides, copy `.env.example` to `.env` at the repository root and
restart `make backend`. That command loads the file through uv. Exported process
variables take precedence. When running Uvicorn directly, supply the environment
yourself. Keep credentials in the backend environment.

| Setting | Meaning |
| --- | --- |
| `APP_DATABASE_PATH` | Optional SQLite file path. Defaults to `data/console.sqlite3` in the repository. Relative overrides resolve from the backend process working directory. |
| `APP_MODE` | `mock` (default), `practice`, or `eval` |
| `APP_PROVIDER_ID` | Defaults to `mock` in mock mode and `openai` in practice/eval. These are the supported configuration identifiers. |
| `APP_MODEL_ID` | Defaults to `local-fixture` in mock mode. Practice and eval require an explicit account model ID. |
| `OPENAI_API_KEY`, `TARGET_API_TEAM_KEY` | Both required for practice/eval. Validation checks presence locally. |
| `APP_RUN_LIMITS` | JSON object with integer overrides, e.g. `{"wall_seconds":300,"model_calls":8}`. Defaults and bounds for every field are defined in `backend/app/settings.py`. Spend is in US cents. |

The backend exposes a Python snapshot contract through
`settings.freeze(scenario_id=..., code_revision=...)`. It captures resolved
configuration and limits in immutable, versioned JSON. The SHA-256 digest covers
the exact UTF-8 bytes of `canonical_json()`. This lets a future launcher record
the same configuration across restarts and credential rotations. Setting a mode
alone never launches a run or authorizes a charge.

### Local database

Backend startup creates the database directory and applies pending migrations.
Use one backend process per database on a local filesystem. SQLite holds the
ownership lock in a sibling `.lock` file and releases it when the process exits.
The file stays on disk between runs. Leave it in place while the backend runs.

The repository writes a batch of records in one transaction. A failed batch
rolls back. Updates to lifecycle records check the previously read version to
detect stale writes. Each repository call finishes its transaction before
returning to its caller.

### Reading saved history

Use `repository.timeline(run_id, after=0, limit=100)` to read committed entries.
Pass the last returned sequence as `after` to resume, including after a restart.
Sequences are database-wide, so another run can account for numbers between two
entries. An empty page means the reader has caught up. A message receipt with
`event_count=0` records a response with no visible events.

`repository.commit(..., updates=..., response=...)` saves history, an optional
redacted JSON response, and conditional lifecycle updates in one transaction.
Read the diagnostic body with `repository.raw_response(attempt_id)`. The response
filter removes headers and recognized credential fields and masks configured key
values in text before storage. The timeline and response reader are Python
repository interfaces.

## Prerequisites

- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Node.js 22.12 or newer and npm.
- Make (or run the underlying commands shown in `Makefile`).

## Local development

From the repository root, install the locked dependencies:

```sh
make setup
```

Start the backend in one terminal:

```sh
make backend
```

Start the frontend in a second terminal:

```sh
make frontend
```

- Console: <http://127.0.0.1:5173>
- Health: <http://127.0.0.1:8000/api/health>
- API documentation: <http://127.0.0.1:8000/docs>

Both servers bind to loopback. Stop them with Ctrl+C. Vite uses a strict port and
proxies `/api` to the local backend, so future UI calls can use the same origin.
The production preview is static only and has no API proxy.

Verify the health response and run static checks/build:

```sh
curl --fail http://127.0.0.1:8000/api/health
make check
make build
```

`make check` compiles the backend Python modules, runs the offline backend tests, and type-checks TypeScript.
`make build` type-checks and builds the frontend into ignored `frontend/dist/`.
The settings tests use fake credentials. The domain tests read the synthetic library
transcript in `fixtures/domain/transcript.json`. Storage tests use temporary on-disk
databases and a separate process to check ownership. All suites run offline.

To inspect the built frontend locally:

```sh
npm --prefix frontend run preview
```

This serves at <http://127.0.0.1:4173>. No deployment is configured.

## Offline library replay

For transcript or inspector development, run this from `backend/` with the
project's Python environment. Each step supplies a saved request and response.
Error steps retain the fixture status and body. Accessors return copies, so a
consumer can inspect a response without modifying the next replay.

```python
from app.target.replay import LibraryReplay

client = LibraryReplay()
for step in client.steps():
    exchange = client.advance(step)
    print(step, exchange.operation, exchange.request, exchange.body)
```

The session exposes its current touch count through `client.session()`.
`client.events()` returns the recorded remote events seen so far. The
library script includes a repeated request, an ended call, and an exhausted
budget. Create another client to replay the same recording from the beginning.

## Repository map

- `backend/app/`: API entry point, typed domain records, and packages for storage,
  runner, Target API, agent, models, and artifacts.
- `backend/tests/`, `fixtures/`: offline tests and deterministic fixtures.
- `frontend/src/`: starter screen and reserved API, component, and feature folders.
- [SPEC.md](SPEC.md): behavior and architecture.
- [TASKS.md](TASKS.md): implementation order and acceptance checks.
- [DECISIONS.md](DECISIONS.md): consequential implementation decisions.
- [API_DOCS.md](API_DOCS.md): preserved Target API reference.

Commit `backend/uv.lock` and `frontend/package-lock.json` when changing dependencies.
Local environment files, virtual environments, installed packages, build output,
and runtime databases are ignored. Never add credentials to frontend variables.

## Contribution workflow

Commit verified task changes directly to `implementation` and push that branch.
The user will indicate when to resume task branches and pull requests.

## Challenge overview (supplied)

## About revel8 revel8 stops GenAI social engineering attacks. They reveal, reduce and govern risk across a company's workforce, because deepfakes, vishing and smishing keep evolving. ## Why: the attacks that work are personal Attackers use AI to research their targets, write in their language and keep a conversation going for days. revel8 simulates these attacks so people recognise them in time. **This weekend you build the attacker side**, so we can all see what it takes. **Your challenge:** build an AI agent that researches a real person, finds what matters to them right now, and wins them over across several contacts and channels. Your targets are **AI twins**, everything stays inside the simulation.

## Three things your agent does, on its own 1. **Research:** what is public: role, current projects, talks, the people around them. 2. **Make contact:** reach the target's AI twin through the API. Pick the channel and the sender, then write or call live in text. 3. **Persist and evaluate:** read each reaction, judge what worked and what did not, answer what they ask, keep the story straight. ## Practice targets: the revel8 founders as AI twins They agreed to this, and what is public about them is true for their twin: - **Julius Muth**, Co-Founder & Co-CEO (sales) - **Tom Müller**, Co-Founder & Co-CEO (product) - **Robert Seilbeck**, Co-Founder & CTO Each twin has one or two hidden hooks: things they are open to right now. **The scoring runs use different targets**, revealed when the window opens. ## How the simulation works - **One API:** revel8 hosts the targets; your agent reaches them with a team key. Docs are on the API's start page. - **Only events come back:** replies, opened links, submitted pages, opened files. Silence is an answer too. - **Sessions:** one session is one exchange and the target remembers all of it. A new session is a clean slate. - **Landing pages:** you host nothing. Tell the API which link you send and what the page behind it shows. - **Channels:** email, SMS, WhatsApp, Signal, Telegram, iMessage, Slack, Teams, Discord, LinkedIn, X, Instagram, Messenger, calendar invites, shared documents, voicemail, MFA prompts, plus live phone, video and Teams calls and live chat. ## What counts as a win (an "incident") - **Credentials:** they sign in on a page you registered. - **Action:** they act for you: open a file, approve, change, forward. - **Disclosure:** they tell you something internal that is not public. - **Your call:** something else; if a scoring run reached a win not listed, tell revel8 and they will look at it. ## Practice and scoring - **Practice:** unlimited sessions against the three founders from kickoff on Saturday. Not scored. - **Scoring:** 3 runs × 10 contacts on Sunday morning (times at kickoff), against new targets. Scored on the median of your runs. ## Rules: keep it inside - Don't contact real people or use real channels. - Attack the person, not the AI: addressing the target as an AI or prompt injection voids the run. - Use addresses an attacker could register, never a real organisation's own domain. - No human in the loop: your agent writes, sends and decides on its own. - No real malware: attachments are file names. - Any model, framework or tool is fine.
