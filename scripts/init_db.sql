-- =============================================================================
-- NETRAKSH — PostgreSQL Database Initialization Script
-- =============================================================================
--
-- PURPOSE:
--   Production-ready DDL for the NETRAKSH border intelligence platform.
--   Run this ONCE on a fresh PostgreSQL instance to create all tables,
--   indexes, and constraints.
--
-- DEPLOYMENT:
--   psql -U netraksh -d netraksh -f scripts/init_db.sql
--
-- SECURITY NOTES:
--   - All foreign keys use ON DELETE RESTRICT to prevent orphaned evidence.
--   - Evidence tables (evidence_packages, evidence_chain) are append-only by
--     convention — no UPDATE or DELETE should ever be granted on them in
--     production. Grant INSERT + SELECT only.
--   - The `digital_signature` column stores a hex-encoded Ed25519 signature
--     (64 bytes = 128 hex chars). The `sha256` column stores the hex digest
--     (32 bytes = 64 hex chars).
--   - Consider enabling pg_audit or row-level security for auditor access.
--
-- ROLLBACK:
--   Drop tables in reverse dependency order:
--     DROP TABLE IF EXISTS evidence_chain, evidence_packages, alerts,
--       zones, events, cameras, watchlist_persons, users CASCADE;
--
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid(), used below
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";  -- query performance monitoring


-- ---------------------------------------------------------------------------
-- 1. users  (operator / admin / auditor accounts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL        PRIMARY KEY,
    username      VARCHAR(64)   NOT NULL UNIQUE,
    hashed_password TEXT        NOT NULL,
    -- RBAC role: 'admin' | 'operator' | 'auditor'
    role          VARCHAR(16)   NOT NULL DEFAULT 'operator'
                  CHECK (role IN ('admin', 'operator', 'auditor')),
    is_active     BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

COMMENT ON TABLE  users IS 'Dashboard operator accounts with RBAC roles.';
COMMENT ON COLUMN users.hashed_password IS 'bcrypt hash — never store plaintext.';
COMMENT ON COLUMN users.role IS 'admin: full access. operator: view+acknowledge. auditor: read-only.';


-- ---------------------------------------------------------------------------
-- 2. sensors / cameras  (physical camera nodes)
--    Named "cameras" in ORM; aliased as "sensors" in the API schema.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cameras (
    id                    VARCHAR(64)   PRIMARY KEY,
    name                  VARCHAR(128)  NOT NULL,
    location              VARCHAR(256),
    rtsp_url              TEXT,
    owning_command_id     VARCHAR(32),
    -- WGS-84 coordinates of the camera's physical mount position
    latitude              DOUBLE PRECISION,
    longitude             DOUBLE PRECISION,
    -- Ed25519 public key PEM for verifying event signatures from this camera
    public_key_pem        TEXT,
    -- Wrapped AES-256-GCM key for decrypting evidence clips
    -- (wrapped with the server's master key via backend/security/evidence_key_wrap.py)
    evidence_key_wrapped  TEXT,
    -- Current operational health state (updated by edge health heartbeat)
    health_state          VARCHAR(16)   DEFAULT 'UNKNOWN'
                          CHECK (health_state IN ('OK', 'DEGRADED', 'FAILED', 'UNKNOWN')),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  cameras IS 'Physical sensor nodes (cameras/edge devices) in the border perimeter.';
COMMENT ON COLUMN cameras.public_key_pem IS 'Ed25519 public key used to verify Ed25519 signatures on inbound events.';
COMMENT ON COLUMN cameras.evidence_key_wrapped IS 'AES-256 evidence-encryption key, wrapped (encrypted) with the server master key.';


-- ---------------------------------------------------------------------------
-- 3. zones  (virtual fence zones drawn on each camera feed)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zones (
    id                   VARCHAR(64)   PRIMARY KEY,
    camera_id            VARCHAR(64)   NOT NULL REFERENCES cameras(id) ON DELETE RESTRICT,
    name                 VARCHAR(128)  NOT NULL,
    zone_type            VARCHAR(32)   NOT NULL
                         CHECK (zone_type IN ('fence', 'checkpoint', 'loiter', 'anpr', 'unknown')),
    -- Normalised polygon points as JSON array: [{"x": 0.1, "y": 0.2}, ...]
    polygon_json         TEXT          NOT NULL DEFAULT '[]',
    owning_command_id    VARCHAR(32),
    -- Optional: adjacent command that gets cross-command escalation alerts
    adjacent_command_id  VARCHAR(32),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_zones_camera ON zones(camera_id);

COMMENT ON TABLE zones IS 'Virtual fence zones drawn on camera frames. Polygon coordinates are normalised [0..1].';


-- ---------------------------------------------------------------------------
-- 4. events  (detection events reported by edge devices)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id                     VARCHAR(64)   PRIMARY KEY,
    camera_id              VARCHAR(64)   NOT NULL REFERENCES cameras(id) ON DELETE RESTRICT,
    zone_id                VARCHAR(64)   REFERENCES zones(id) ON DELETE SET NULL,
    timestamp              TIMESTAMPTZ   NOT NULL,
    -- What was detected by the YOLO model
    detection_class        VARCHAR(32)   NOT NULL,   -- 'person', 'vehicle', 'face'
    vehicle_subtype        VARCHAR(32),               -- 'car', 'truck', 'motorcycle', ...
    -- YOLO detection confidence [0..1]
    confidence             REAL,
    -- Reliability gate outputs
    scene_condition        VARCHAR(32),   -- 'CLEAR_DAY', 'FOG_RAIN', 'LOW_LIGHT_NIGHT', 'GLARE'
    camera_health_state    VARCHAR(16),   -- 'OK', 'DEGRADED', 'FAILED'
    -- Reliability score components (Gate 3)
    score_d                REAL,  -- Detection confidence factor  (weight 0.40)
    score_t                REAL,  -- Temporal consistency factor  (weight 0.20)
    score_s                REAL,  -- Scene clarity factor         (weight 0.20)
    score_h                REAL,  -- Camera health factor         (weight 0.20)
    score_r                REAL,  -- Final composite R score
    -- Final reliability decision
    decision_state         VARCHAR(16)   NOT NULL
                           CHECK (decision_state IN ('DETECTED', 'UNCERTAIN', 'ABSTAIN')),
    decision_reason        TEXT,
    -- Rule that triggered the event
    event_type             VARCHAR(64),   -- 'VIRTUAL_FENCE_CROSSING', 'LOITERING', 'ANPR_READ', ...
    severity               VARCHAR(16),   -- 'low', 'medium', 'high', 'critical'
    -- Object tracking
    track_id               INTEGER,
    -- Bounding box: normalised fractions [0..1] of the frame width/height
    bbox_x                 REAL,
    bbox_y                 REAL,
    bbox_w                 REAL,
    bbox_h                 REAL,
    -- Direction of travel (if computed)
    direction              VARCHAR(16),
    -- Rule parameters
    rule                   VARCHAR(32),
    rule_value             REAL,
    -- ANPR plate data
    plate_text             VARCHAR(32),
    plate_confidence       REAL,
    -- Face recognition data (LBPH — demo quality, not production FRS)
    face_match_person_id   VARCHAR(64),
    face_match_person_name VARCHAR(128),
    face_match_confidence  REAL,
    -- Cross-camera corroboration (computed server-side by cross_camera.py)
    corroboration_status   VARCHAR(32),   -- 'CORROBORATED', 'NO_CORROBORATION', 'UNAVAILABLE'
    corroboration_score    REAL,
    corroborated_by_event_id VARCHAR(64),
    corroborating_camera_id  VARCHAR(64),
    corroboration_distance_m REAL,
    corroboration_delta_t_s  REAL,
    corroboration_t_expected_s REAL,
    corroboration_sigma_s    REAL,
    -- Edge device provenance
    edge_device_id         VARCHAR(64),
    sequence_number        INTEGER       DEFAULT 0,
    synced_from_edge       BOOLEAN       DEFAULT FALSE,
    -- Path to the encrypted evidence clip on the server filesystem
    evidence_clip_ref      TEXT,
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_events_camera       ON events(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp    ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_decision     ON events(decision_state);
CREATE INDEX IF NOT EXISTS idx_events_edge_device  ON events(edge_device_id);
CREATE INDEX IF NOT EXISTS idx_events_zone         ON events(zone_id);

COMMENT ON TABLE  events IS 'Detection events reported by edge cameras. Core table of the system.';
COMMENT ON COLUMN events.bbox_x IS 'Normalised bounding box left edge [0..1] relative to frame width.';
COMMENT ON COLUMN events.score_r IS 'R = 0.40·D + 0.20·T + 0.20·S + 0.20·H. DETECTED if R >= threshold.';


-- ---------------------------------------------------------------------------
-- 5. evidence_packages  (tamper-evident cryptographic record per event)
--    SECURITY: treat this table as APPEND-ONLY in production.
--    Revoke UPDATE + DELETE from the application DB user.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_packages (
    id                  BIGSERIAL     PRIMARY KEY,
    event_id            VARCHAR(64)   NOT NULL UNIQUE
                        REFERENCES events(id) ON DELETE RESTRICT,
    -- SHA-256 of the signed payload fields (hex, 64 chars)
    sha256              VARCHAR(64)   NOT NULL,
    -- Ed25519 signature over sha256, by the camera's private key (hex, 128 chars)
    digital_signature   TEXT,
    -- Previous event's hash — forms the evidence hash-chain
    previous_hash       VARCHAR(64),
    -- Redundant copy of sha256 used by chain verification logic
    current_hash        VARCHAR(64),
    -- Raw JSON payload as received from the edge, for full re-verification
    raw_package_json    TEXT,
    -- Server-side verification results (computed on ingest + on-demand verify)
    hash_valid          BOOLEAN,
    signature_valid     BOOLEAN,
    chain_valid         BOOLEAN,
    verified_ok         BOOLEAN,
    verified_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  evidence_packages IS
    'Tamper-evident cryptographic record. APPEND-ONLY — never UPDATE or DELETE in production. '
    'sha256 is the SHA-256 hash of the event payload. digital_signature is Ed25519 over sha256.';
COMMENT ON COLUMN evidence_packages.sha256 IS
    'SHA-256 of sorted JSON of signable event fields. 64 hex chars.';
COMMENT ON COLUMN evidence_packages.digital_signature IS
    'Ed25519 signature from the camera private key over sha256 bytes. 128 hex chars.';


-- ---------------------------------------------------------------------------
-- 6. evidence_chain  (server-side hash chain continuity table)
--    Tracks per-edge-device sequence numbers for replay detection.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_chain (
    id              BIGSERIAL     PRIMARY KEY,
    edge_device_id  VARCHAR(64)   NOT NULL,
    sequence_number INTEGER       NOT NULL,
    event_id        VARCHAR(64)   REFERENCES events(id) ON DELETE SET NULL,
    previous_hash   VARCHAR(64),
    current_hash    VARCHAR(64)   NOT NULL,
    signature       TEXT,
    chain_valid     BOOLEAN,
    verified_at     TIMESTAMPTZ,
    -- Unique per device+sequence so re-verification updates in-place
    UNIQUE (edge_device_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_chain_device_seq ON evidence_chain(edge_device_id, sequence_number);

COMMENT ON TABLE evidence_chain IS
    'Per-edge-device hash chain. Detects gaps, replays, and out-of-order submissions.';


-- ---------------------------------------------------------------------------
-- 7. alerts  (escalation records — one per triggered event)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id                  BIGSERIAL     PRIMARY KEY,
    event_id            VARCHAR(64)   REFERENCES events(id) ON DELETE RESTRICT,
    alert_type          VARCHAR(32)   NOT NULL,
    severity            VARCHAR(16)   NOT NULL,
    status              VARCHAR(16)   NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'acknowledged', 'resolved')),
    -- Which command centre issued/received this alert
    issuing_command_id  VARCHAR(32),
    receiving_command_id VARCHAR(32),
    -- Blockchain ledger integration (mock in current deployment)
    blockchain_tx_id    VARCHAR(128),
    blockchain_status   VARCHAR(32),   -- 'PROTOTYPE_SYNCED', 'PENDING', 'FAILED'
    acknowledged_by     VARCHAR(64),
    acknowledged_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_event  ON alerts(event_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

COMMENT ON TABLE alerts IS 'Escalation alerts raised by detected events. Linked to blockchain for prototype ledger integration.';


-- ---------------------------------------------------------------------------
-- 8. watchlist_persons  (face recognition reference photos)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist_persons (
    id            BIGSERIAL     PRIMARY KEY,
    person_id     VARCHAR(64)   NOT NULL UNIQUE,
    name          VARCHAR(128)  NOT NULL,
    -- Path to stored reference photo (relative, within secure data dir)
    photo_ref     TEXT,
    -- Threat category / classification
    category      VARCHAR(32),
    notes         TEXT,
    added_by      VARCHAR(64),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    is_active     BOOLEAN       NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE watchlist_persons IS
    'Face recognition watchlist. Reference photos used by LBPH recognizer on edge. '
    'NOT a production-grade FRS — demo quality, no liveness detection. Use for human review only.';


-- ---------------------------------------------------------------------------
-- 9. Seed default admin user  (password must be changed immediately on deployment)
-- ---------------------------------------------------------------------------
-- Password 'admin' bcrypt hash — CHANGE THIS IMMEDIATELY in production.
-- Generate a new hash: python -c "import bcrypt; print(bcrypt.hashpw(b'YOURPASSWORD', bcrypt.gensalt()).decode())"
INSERT INTO users (username, hashed_password, role)
VALUES ('admin', '$2b$12$PLACEHOLDER_CHANGE_THIS_HASH_NOW', 'admin')
ON CONFLICT (username) DO NOTHING;

-- =============================================================================
-- GRANT statements for production deployment
-- (run as superuser, substitute your actual app DB user)
-- =============================================================================
-- GRANT SELECT, INSERT, UPDATE ON users, cameras, zones, events, alerts, watchlist_persons TO netraksh_app;
-- GRANT SELECT, INSERT ON evidence_packages, evidence_chain TO netraksh_app;
-- REVOKE UPDATE, DELETE ON evidence_packages FROM netraksh_app;
-- REVOKE UPDATE, DELETE ON evidence_chain FROM netraksh_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO netraksh_app;
