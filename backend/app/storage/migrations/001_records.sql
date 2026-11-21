PRAGMA application_id = 0x52384331;

-- The JSON is the serialized domain record. Generated keys let SQLite enforce
-- ownership without a second writable copy of the same identifier.
CREATE TABLE runs (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.run_id')) NOT NULL UNIQUE,
    scenario_id TEXT AS (json_extract(body, '$.configuration.scenario_id')) NOT NULL,
    UNIQUE(id, scenario_id)
);

CREATE TABLE sessions (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.session_id')) NOT NULL UNIQUE,
    run_id TEXT AS (json_extract(body, '$.run_id')) NOT NULL UNIQUE,
    scenario_id TEXT AS (json_extract(body, '$.scenario_id')) NOT NULL,
    UNIQUE(id, run_id),
    FOREIGN KEY(run_id, scenario_id) REFERENCES runs(id, scenario_id)
);

CREATE TABLE actions (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.action_id')) NOT NULL UNIQUE,
    run_id TEXT AS (json_extract(body, '$.run_id')) NOT NULL REFERENCES runs(id),
    session_id TEXT AS (json_extract(body, '$.session_id')),
    conversation_id TEXT AS (json_extract(body, '$.conversation_id')),
    UNIQUE(id, run_id),
    CHECK(conversation_id IS NULL OR session_id IS NOT NULL),
    FOREIGN KEY(session_id, run_id) REFERENCES sessions(id, run_id),
    FOREIGN KEY(conversation_id, session_id) REFERENCES conversations(id, session_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE attempts (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.attempt_id')) NOT NULL UNIQUE,
    action_id TEXT AS (json_extract(body, '$.action_id')) NOT NULL REFERENCES actions(id)
);

CREATE TABLE events (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.record_id')) NOT NULL UNIQUE,
    run_id TEXT AS (json_extract(body, '$.run_id')) NOT NULL REFERENCES runs(id),
    action_id TEXT AS (json_extract(body, '$.action_id')),
    kind TEXT AS (json_extract(body, '$.kind')) NOT NULL
        CHECK(kind IN ('observation', 'assessment', 'decision')),
    greeting_conversation_id TEXT AS (CASE
        WHEN kind = 'observation' AND json_extract(body, '$.content.kind') = 'greeting'
        THEN json_extract(body, '$.content.response.conversation_id') END),
    UNIQUE(id, greeting_conversation_id),
    FOREIGN KEY(action_id, run_id) REFERENCES actions(id, run_id)
);

CREATE TABLE conversations (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.conversation_id')) NOT NULL UNIQUE,
    session_id TEXT AS (json_extract(body, '$.session_id')) NOT NULL REFERENCES sessions(id),
    greeting_id TEXT AS (json_extract(body, '$.greeting_observation_id')) NOT NULL,
    FOREIGN KEY(greeting_id, id) REFERENCES events(id, greeting_conversation_id)
        DEFERRABLE INITIALLY DEFERRED,
    UNIQUE(id, session_id)
);

CREATE TABLE artifact_versions (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.version_id')) NOT NULL UNIQUE
);

CREATE TABLE evidence_sources (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.source_id')) NOT NULL UNIQUE
);

CREATE TABLE memory_entries (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.entry_id')) NOT NULL UNIQUE,
    session_id TEXT AS (json_extract(body, '$.session_id')) NOT NULL REFERENCES sessions(id),
    source_id TEXT AS (json_extract(body, '$.source_id')) REFERENCES evidence_sources(id)
);

CREATE TABLE model_usage (
    body TEXT NOT NULL CHECK(json_valid(body)),
    id TEXT AS (json_extract(body, '$.usage_id')) NOT NULL UNIQUE,
    run_id TEXT AS (json_extract(body, '$.run_id')) NOT NULL REFERENCES runs(id)
);
