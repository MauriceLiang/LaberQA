CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL CHECK (file_type IN ('pdf', 'doc', 'docx', 'txt')),
    file_path VARCHAR(500) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PROCESSING'
        CHECK (status IN ('PROCESSING', 'SUCCESS', 'FAILED')),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error_message VARCHAR(500),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    chunk_no INTEGER NOT NULL CHECK (chunk_no >= 1),
    content TEXT NOT NULL,
    vector_key VARCHAR(100) NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (document_id, chunk_no)
);

CREATE TABLE IF NOT EXISTS session (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(100),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR(36) NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    rewritten_question TEXT,
    answer_style VARCHAR(20) CHECK (answer_style IN ('plain', 'legal')),
    refused INTEGER CHECK (refused IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS citation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
    chunk_id INTEGER NOT NULL REFERENCES chunk(id),
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    retrieval_score REAL NOT NULL CHECK (retrieval_score >= 0 AND retrieval_score <= 1),
    rerank_score REAL CHECK (rerank_score IS NULL OR (rerank_score >= 0 AND rerank_score <= 1)),
    rank_no INTEGER NOT NULL CHECK (rank_no >= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_execution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER REFERENCES message(id) ON DELETE SET NULL,
    tool_name VARCHAR(100) NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluation_case (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic VARCHAR(50) NOT NULL,
    expected_type VARCHAR(20) NOT NULL CHECK (expected_type IN ('ANSWER', 'REJECT')),
    turns_json TEXT NOT NULL DEFAULT '[]',
    expected_points_json TEXT NOT NULL DEFAULT '[]',
    expected_sources_json TEXT NOT NULL DEFAULT '[]',
    should_show_compliance INTEGER NOT NULL DEFAULT 0 CHECK (should_show_compliance IN (0, 1)),
    origin VARCHAR(20) NOT NULL DEFAULT 'BUILTIN'
        CHECK (origin IN ('BUILTIN', 'CUSTOM')),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    builtin_key VARCHAR(100),
    created_by VARCHAR(100),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    case_count INTEGER NOT NULL DEFAULT 0 CHECK (case_count >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    progress_current INTEGER NOT NULL DEFAULT 0 CHECK (progress_current >= 0),
    progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total >= 0),
    error_message TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    accuracy REAL CHECK (accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1)),
    reject_rate REAL CHECK (reject_rate IS NULL OR (reject_rate >= 0 AND reject_rate <= 1)),
    citation_hit_rate REAL CHECK (citation_hit_rate IS NULL OR (citation_hit_rate >= 0 AND citation_hit_rate <= 1)),
    multi_turn_pass_rate REAL CHECK (multi_turn_pass_rate IS NULL OR (multi_turn_pass_rate >= 0 AND multi_turn_pass_rate <= 1)),
    compliance_hit_rate REAL CHECK (compliance_hit_rate IS NULL OR (compliance_hit_rate >= 0 AND compliance_hit_rate <= 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluation_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES evaluation_run(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES evaluation_case(id),
    status VARCHAR(20) NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    answer TEXT,
    refused INTEGER CHECK (refused IN (0, 1)),
    correct INTEGER CHECK (correct IN (0, 1)),
    source_hit INTEGER CHECK (source_hit IN (0, 1)),
    multi_turn_correct INTEGER CHECK (multi_turn_correct IN (0, 1)),
    compliance_hit INTEGER CHECK (compliance_hit IN (0, 1)),
    citations_json TEXT NOT NULL DEFAULT '[]',
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, case_id)
);

CREATE TABLE IF NOT EXISTS evaluation_run_case (
    run_id INTEGER NOT NULL REFERENCES evaluation_run(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES evaluation_case(id),
    position INTEGER NOT NULL CHECK (position >= 0),
    case_version INTEGER NOT NULL DEFAULT 1 CHECK (case_version >= 1),
    case_snapshot_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, case_id),
    UNIQUE (run_id, position)
);

CREATE TABLE IF NOT EXISTS missing_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_key VARCHAR(100) NOT NULL UNIQUE,
    sample_question TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1 CHECK (count >= 1),
    missing_area VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RESOLVED', 'IGNORED')),
    note TEXT,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS retrieval_experiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    progress_current INTEGER NOT NULL DEFAULT 0 CHECK (progress_current >= 0),
    progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total >= 0),
    error_message TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    case_count INTEGER NOT NULL DEFAULT 0 CHECK (case_count >= 0),
    best_config_index INTEGER CHECK (best_config_index IS NULL OR best_config_index >= 0),
    accuracy REAL CHECK (accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1)),
    reject_rate REAL CHECK (reject_rate IS NULL OR (reject_rate >= 0 AND reject_rate <= 1)),
    citation_hit_rate REAL CHECK (citation_hit_rate IS NULL OR (citation_hit_rate >= 0 AND citation_hit_rate <= 1)),
    avg_retrieval_ms REAL CHECK (avg_retrieval_ms IS NULL OR avg_retrieval_ms >= 0),
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS retrieval_experiment_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES retrieval_experiment(id) ON DELETE CASCADE,
    config_index INTEGER NOT NULL CHECK (config_index >= 0),
    case_id INTEGER NOT NULL REFERENCES evaluation_case(id),
    status VARCHAR(20) NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    retrieved_sources_json TEXT NOT NULL DEFAULT '[]',
    source_hit INTEGER CHECK (source_hit IN (0, 1)),
    correct INTEGER CHECK (correct IN (0, 1)),
    refused INTEGER CHECK (refused IN (0, 1)),
    retrieval_ms INTEGER CHECK (retrieval_ms IS NULL OR retrieval_ms >= 0),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (experiment_id, config_index, case_id)
);

CREATE TABLE IF NOT EXISTS retrieval_strategy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    builtin_key VARCHAR(100),
    config_json TEXT NOT NULL,
    is_builtin INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS retrieval_strategy_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL REFERENCES retrieval_strategy(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (strategy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_document_status_created_at ON document(status, created_at);
CREATE INDEX IF NOT EXISTS idx_chunk_document_id ON chunk(document_id);
CREATE INDEX IF NOT EXISTS idx_message_session_created_at ON message(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_case_topic ON evaluation_case(topic);
CREATE INDEX IF NOT EXISTS idx_evaluation_run_status_created_at ON evaluation_run(status, created_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_result_run_id ON evaluation_result(run_id);
CREATE INDEX IF NOT EXISTS idx_missing_knowledge_status_count ON missing_knowledge(status, count DESC);
CREATE INDEX IF NOT EXISTS idx_missing_knowledge_last_seen_at ON missing_knowledge(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_retrieval_experiment_status_created_at ON retrieval_experiment(status, created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_experiment_result_experiment_id
    ON retrieval_experiment_result(experiment_id, config_index);
CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_strategy_builtin_key
    ON retrieval_strategy(builtin_key) WHERE builtin_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_retrieval_strategy_updated_at
    ON retrieval_strategy(updated_at DESC, id DESC);
