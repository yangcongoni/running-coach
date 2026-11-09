CREATE TABLE metadata(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);

CREATE TABLE sources(id INTEGER PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, reference TEXT, note TEXT);

CREATE TABLE strength_baselines(id INTEGER PRIMARY KEY, exercise TEXT UNIQUE NOT NULL, load_kg REAL, load_basis TEXT, sets INTEGER, reps_min INTEGER, reps_max INTEGER, effort TEXT, source_id INTEGER REFERENCES sources(id));

CREATE TABLE planned_sessions(id INTEGER PRIMARY KEY, plan_version TEXT NOT NULL, date TEXT NOT NULL, sport TEXT NOT NULL, prescription_json TEXT NOT NULL, UNIQUE(plan_version,date,sport));

CREATE TABLE sessions(id INTEGER PRIMARY KEY, external_key TEXT UNIQUE, date TEXT NOT NULL, sport TEXT NOT NULL, duration_minutes REAL, session_rpe REAL CHECK(session_rpe BETWEEN 0 AND 10), sequence_note TEXT, source_id INTEGER REFERENCES sources(id), raw_json TEXT, notes TEXT);

CREATE TABLE strength_sets(id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id), exercise TEXT NOT NULL, set_number INTEGER NOT NULL, set_kind TEXT NOT NULL DEFAULT 'working', load_kg REAL, load_basis TEXT, reps INTEGER, side TEXT, rir REAL, rest_seconds REAL, notes TEXT, UNIQUE(session_id,exercise,set_number,side));

CREATE TABLE running_details(session_id INTEGER PRIMARY KEY REFERENCES sessions(id), distance_km REAL, timer_seconds REAL, elapsed_seconds REAL, average_hr REAL, maximum_hr REAL, device TEXT, sensor TEXT, details_json TEXT);

CREATE TABLE running_laps(id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id), lap_number INTEGER, details_json TEXT, UNIQUE(session_id,lap_number));

CREATE TABLE daily_recovery(date TEXT PRIMARY KEY, sleep_minutes REAL, hrv_ms REAL, resting_hr REAL, fatigue_0_10 REAL, soreness_0_10 REAL, pain_note TEXT, details_json TEXT, source_id INTEGER REFERENCES sources(id));

CREATE TABLE analyses(id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, session_id INTEGER REFERENCES sessions(id), evidence_json TEXT, assessment TEXT, confidence TEXT, recommendation TEXT, plan_version TEXT);

CREATE TABLE revisions(id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, entity TEXT NOT NULL, entity_key TEXT, previous_json TEXT, replacement_json TEXT, reason TEXT);

CREATE TABLE stretching_records(id INTEGER PRIMARY KEY,external_key TEXT UNIQUE NOT NULL,date TEXT NOT NULL,duration_minutes REAL CHECK(duration_minutes>=0),body_parts_json TEXT NOT NULL,method TEXT,timing TEXT,intensity_0_10 REAL CHECK(intensity_0_10 BETWEEN 0 AND 10),before_feeling TEXT,after_feeling TEXT,pain_note TEXT,status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('completed','explicitly_not_done')),source TEXT NOT NULL,notes TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE periodic_reviews(id INTEGER PRIMARY KEY,period_type TEXT NOT NULL CHECK(period_type IN ('weekly','monthly')),period_start TEXT NOT NULL,period_end TEXT NOT NULL,data_through TEXT NOT NULL,status TEXT NOT NULL,goals_json TEXT NOT NULL,metrics_json TEXT NOT NULL,assessment_json TEXT NOT NULL,next_actions_json TEXT NOT NULL,limitations_json TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(period_type,period_start));

CREATE TABLE daily_submissions(date TEXT PRIMARY KEY,payload_json TEXT NOT NULL,revision INTEGER NOT NULL,submission_id TEXT NOT NULL,request_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL DEFAULT '待分析',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);

CREATE TABLE daily_submission_history(id INTEGER PRIMARY KEY,date TEXT NOT NULL,revision INTEGER NOT NULL,payload_json TEXT NOT NULL,request_id TEXT UNIQUE NOT NULL,submitted_at TEXT NOT NULL,UNIQUE(date,revision));
