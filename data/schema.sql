PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    task_type TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'REGISTERED'
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    test_id TEXT,
    harness TEXT NOT NULL,
    model_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_seconds REAL,
    exit_code INTEGER,
    human_intervention INTEGER NOT NULL DEFAULT 0,
    artifact_path TEXT,
    notes TEXT,
    FOREIGN KEY(test_id) REFERENCES tests(id)
);

CREATE TABLE IF NOT EXISTS scores (
    run_id TEXT PRIMARY KEY,
    correctness REAL,
    instruction_compliance REAL,
    scope_control REAL,
    code_quality REAL,
    test_discipline REAL,
    security_awareness REAL,
    overall_score REAL,
    verdict TEXT,
    reviewer_notes TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS qualifications (
    model_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UNQUALIFIED',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY(model_id, capability)
);

CREATE TABLE IF NOT EXISTS publication_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    audience TEXT NOT NULL,
    published_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
