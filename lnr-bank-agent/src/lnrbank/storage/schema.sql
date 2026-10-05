-- Схема хранилища срезов. Таблицы данных — длинный формат с snapshot_date и run_id.
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    blocks TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    key_rate REAL,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS banks (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    bank TEXT NOT NULL, in_lnr TEXT CHECK (in_lnr IN ('yes', 'no', 'unknown')),
    presence_format TEXT, scope TEXT CHECK (scope IN ('main', 'watchlist')), source_url TEXT,
    UNIQUE (snapshot_date, bank)
);

CREATE TABLE IF NOT EXISTS infrastructure (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    bank TEXT NOT NULL, city TEXT NOT NULL, offices_full INTEGER, offices_mfc INTEGER,
    offices_mobile INTEGER, atms INTEGER, source_url TEXT,
    UNIQUE (snapshot_date, bank, city)
);

CREATE TABLE IF NOT EXISTS products (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    bank TEXT NOT NULL, product_id TEXT NOT NULL, block TEXT NOT NULL, product_type TEXT,
    product_name TEXT, segment TEXT,
    available_in_lnr TEXT CHECK (available_in_lnr IN ('yes', 'no', 'unknown')),
    channels TEXT, region_method TEXT, source_url TEXT, notes TEXT,
    UNIQUE (snapshot_date, product_id)
);

CREATE TABLE IF NOT EXISTS conditions (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    bank TEXT NOT NULL, product_id TEXT NOT NULL, parameter TEXT NOT NULL, value TEXT,
    unit TEXT, condition TEXT, better TEXT, region_method TEXT NOT NULL, source_type TEXT,
    source_url TEXT NOT NULL, evidence TEXT, confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    collected_at TEXT NOT NULL,
    UNIQUE (snapshot_date, product_id, parameter)
);

CREATE TABLE IF NOT EXISTS scenarios (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    scenario_id TEXT NOT NULL, bank TEXT NOT NULL, product_id TEXT, program TEXT,
    metric TEXT NOT NULL, value TEXT, unit TEXT, calc_method TEXT, assumptions TEXT,
    region_method TEXT, source_url TEXT,
    UNIQUE (snapshot_date, scenario_id, bank, program, metric)
);

CREATE TABLE IF NOT EXISTS changes (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    prev_snapshot_date TEXT, bank TEXT NOT NULL, product_id TEXT, parameter TEXT,
    old_value TEXT, new_value TEXT, delta REAL, alert TEXT CHECK (alert IN ('yes', 'no'))
);

CREATE TABLE IF NOT EXISTS gaps (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    block TEXT, scenario_or_parameter TEXT, metric TEXT, sber_value TEXT, best_bank TEXT,
    best_value TEXT, others_median REAL, delta_vs_best REAL, delta_vs_median REAL,
    status TEXT, comment TEXT
);

CREATE TABLE IF NOT EXISTS data_quality (
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    bank TEXT NOT NULL, block TEXT NOT NULL, params_planned INTEGER, params_collected INTEGER,
    not_confirmed INTEGER, coverage_pct REAL, issues TEXT
);

CREATE TABLE IF NOT EXISTS raw_documents (
    doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id), snapshot_date TEXT NOT NULL,
    bank TEXT NOT NULL, url TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('html', 'pdf', 'screenshot', 'text')),
    path TEXT NOT NULL, sha256 TEXT NOT NULL, fetched_at TEXT NOT NULL, region_method TEXT,
    pruned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS llm_cache (
    content_sha256 TEXT NOT NULL, prompt_version TEXT NOT NULL, model TEXT NOT NULL,
    response_json TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (content_sha256, prompt_version, model)
);
