CREATE TABLE timeline (
    sequence INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    record_id TEXT NOT NULL REFERENCES events(id),
    origin TEXT NOT NULL,
    identity TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(json_valid(payload)),
    UNIQUE(run_id, origin, identity)
);
CREATE INDEX timeline_by_run ON timeline(run_id, sequence);

-- Both old records and future inserts pass through the same projection.
-- Preserve the source receipt before its remote events, in wire-array order.
CREATE VIEW timeline_source AS
SELECT rowid AS source_order, 0 AS ordinal, run_id, id AS record_id,
    kind AS origin,
    CASE json_extract(body, '$.content.kind')
        WHEN 'message' THEN json_array('message', json_extract(body, '$.content.response.message_id'))
        WHEN 'greeting' THEN json_array('greeting', greeting_conversation_id)
        WHEN 'turn' THEN json_array('turn', json_extract(body, '$.content.conversation_id'),
                                     json_extract(body, '$.content.response.turns_used'))
        ELSE id
    END AS identity,
    coalesce(json_extract(body, '$.content.kind'), kind) AS kind,
    CASE WHEN kind = 'observation' THEN
        json_remove(json_set(json_extract(body, '$.content'), '$.event_count',
            json_array_length(body, '$.content.response.events')), '$.response.events')
        ELSE json_remove(body, '$.kind', '$.run_id', '$.record_id', '$.action_id', '$.recorded_at')
    END AS payload
FROM events
UNION ALL
SELECT e.rowid, 1 + item.key, e.run_id, e.id, 'remote',
       json_extract(item.value, '$.id'), json_extract(item.value, '$.type'), item.value
FROM events AS e, json_each(e.body, '$.content.response.events') AS item;

INSERT INTO timeline(run_id, record_id, origin, identity, kind, payload)
SELECT run_id, record_id, origin, identity, kind, redact_json(payload)
FROM timeline_source WHERE true ORDER BY source_order, ordinal
ON CONFLICT(run_id, origin, identity) DO NOTHING;

CREATE TRIGGER timeline_after_history AFTER INSERT ON events BEGIN
    INSERT INTO timeline(run_id, record_id, origin, identity, kind, payload)
    SELECT run_id, record_id, origin, identity, kind, payload
    FROM timeline_source WHERE record_id = NEW.id ORDER BY ordinal
    ON CONFLICT(run_id, origin, identity) DO NOTHING;
END;

CREATE TRIGGER timeline_no_update BEFORE UPDATE ON timeline BEGIN
    SELECT RAISE(ABORT, 'timeline is append-only');
END;
CREATE TRIGGER timeline_no_delete BEFORE DELETE ON timeline BEGIN
    SELECT RAISE(ABORT, 'timeline is append-only');
END;
CREATE TRIGGER history_no_update BEFORE UPDATE ON events BEGIN
    SELECT RAISE(ABORT, 'history is append-only');
END;

CREATE TRIGGER history_no_delete BEFORE DELETE ON events BEGIN
    SELECT RAISE(ABORT, 'history is append-only');
END;

CREATE TABLE raw_responses (
    attempt_id TEXT PRIMARY KEY NOT NULL REFERENCES attempts(id),
    body TEXT NOT NULL CHECK(json_valid(body))
);
