-- ============================================================
--  Day 2 – Telecom Network Events Database
--  DDL Script  |  PostgreSQL 14+
-- ============================================================
--  Schema: telecom
--  Domain: towers → incidents → engineers → resolutions
--  Normal form: Third Normal Form (3NF)
--
--  Run order:
--    1. CREATE SCHEMA
--    2. Lookup / reference tables
--    3. Core entity tables
--    4. Relationship / transaction tables
--    5. Indexes
--    6. Views
-- ============================================================

-- ── 0. SCHEMA ─────────────────────────────────────────────
DROP SCHEMA IF EXISTS telecom CASCADE;
CREATE SCHEMA telecom;
SET search_path = telecom;


-- ── 1. LOOKUP TABLES ──────────────────────────────────────
--  Small, stable reference tables that enforce domain values
--  without hard-coding them in application code.

CREATE TABLE province (
    province_code   CHAR(2)       PRIMARY KEY,
    province_name   VARCHAR(60)   NOT NULL
);

INSERT INTO province VALUES
    ('AB', 'Alberta'),
    ('BC', 'British Columbia'),
    ('MB', 'Manitoba'),
    ('NB', 'New Brunswick'),
    ('NL', 'Newfoundland and Labrador'),
    ('NS', 'Nova Scotia'),
    ('NT', 'Northwest Territories'),
    ('NU', 'Nunavut'),
    ('ON', 'Ontario'),
    ('PE', 'Prince Edward Island'),
    ('QC', 'Quebec'),
    ('SK', 'Saskatchewan'),
    ('YT', 'Yukon');


CREATE TABLE outage_type (
    outage_type_id  SERIAL        PRIMARY KEY,
    type_code       VARCHAR(30)   NOT NULL UNIQUE,
    description     TEXT
);

INSERT INTO outage_type (type_code, description) VALUES
    ('FIBRE_CUT',     'Physical severance of fibre optic cable'),
    ('POWER_FAIL',    'Loss of commercial power / generator failure'),
    ('HW_FAULT',      'Hardware component failure at site or node'),
    ('SW_BUG',        'Software defect or failed firmware update'),
    ('WEATHER',       'Storm, flood, ice, or lightning damage'),
    ('PLANNED_MAINT', 'Scheduled maintenance window');


CREATE TABLE severity_level (
    severity_id     SMALLINT      PRIMARY KEY,
    label           VARCHAR(20)   NOT NULL UNIQUE,  -- P1 / P2 / P3 / P4
    sla_response_min INT          NOT NULL,          -- contractual response SLA
    sla_resolve_min  INT          NOT NULL
);

INSERT INTO severity_level VALUES
    (1, 'P1 – Critical',  15,  240),
    (2, 'P2 – High',      30,  480),
    (3, 'P3 – Medium',    60, 1440),
    (4, 'P4 – Low',      240, 4320);


CREATE TABLE resolution_action (
    action_id       SERIAL        PRIMARY KEY,
    action_code     VARCHAR(40)   NOT NULL UNIQUE,
    description     TEXT
);

INSERT INTO resolution_action (action_code, description) VALUES
    ('FIBRE_SPLICE',     'Spliced and re-buried severed fibre'),
    ('UPS_REPLACE',      'Replaced uninterruptible power supply unit'),
    ('FW_ROLLBACK',      'Rolled back to previous stable firmware'),
    ('HW_SWAP',          'Swapped failed hardware component'),
    ('CONFIG_REVERT',    'Reverted misconfigured routing or switch config'),
    ('CABINET_SEAL',     'Sealed cabinet and replaced water-damaged cards'),
    ('GENERATOR_START',  'Started backup generator, restored commercial power'),
    ('REMOTE_RESET',     'Performed remote equipment reset');


-- ── 2. CARRIER ────────────────────────────────────────────

CREATE TABLE carrier (
    carrier_id      SERIAL        PRIMARY KEY,
    carrier_name    VARCHAR(100)  NOT NULL UNIQUE,
    ticker_symbol   CHAR(6),
    hq_province     CHAR(2)       REFERENCES province(province_code),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);


-- ── 3. TOWER / SITE ───────────────────────────────────────
--  Represents a physical network site: cell tower, exchange,
--  data centre, or fibre node.

CREATE TABLE tower (
    tower_id        SERIAL        PRIMARY KEY,
    tower_code      VARCHAR(20)   NOT NULL UNIQUE,   -- e.g. MB-WPG-0042
    carrier_id      INT           NOT NULL REFERENCES carrier(carrier_id),
    site_type       VARCHAR(30)   NOT NULL
                    CHECK (site_type IN ('CELL_TOWER','EXCHANGE',
                                        'DATA_CENTRE','FIBRE_NODE')),
    city            VARCHAR(100)  NOT NULL,
    province_code   CHAR(2)       NOT NULL REFERENCES province(province_code),
    latitude        NUMERIC(9,6),
    longitude       NUMERIC(9,6),
    commissioned_dt DATE,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);


-- ── 4. ENGINEER ───────────────────────────────────────────

CREATE TABLE engineer (
    engineer_id     SERIAL        PRIMARY KEY,
    employee_no     VARCHAR(20)   NOT NULL UNIQUE,
    full_name       VARCHAR(120)  NOT NULL,
    email           VARCHAR(150)  NOT NULL UNIQUE,
    phone           VARCHAR(20),
    specialisation  VARCHAR(60),  -- e.g. 'RF Optimisation', 'Fibre', 'Core'
    province_code   CHAR(2)       REFERENCES province(province_code),
    hire_date       DATE,
    is_oncall       BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);


-- ── 5. OUTAGE INCIDENT ────────────────────────────────────
--  Core fact table.  One row per reported outage event.

CREATE TABLE outage_incident (
    incident_id         SERIAL        PRIMARY KEY,
    incident_ref        VARCHAR(20)   NOT NULL UNIQUE,   -- e.g. INC-2024-0001
    tower_id            INT           NOT NULL REFERENCES tower(tower_id),
    outage_type_id      INT           NOT NULL REFERENCES outage_type(outage_type_id),
    severity_id         SMALLINT      NOT NULL REFERENCES severity_level(severity_id),
    reported_at         TIMESTAMPTZ   NOT NULL,
    resolved_at         TIMESTAMPTZ,
    duration_min        INT
        GENERATED ALWAYS AS (
            EXTRACT(EPOCH FROM (resolved_at - reported_at)) / 60
        ) STORED,                                        -- auto-computed
    customers_affected  INT           NOT NULL DEFAULT 0
                        CHECK (customers_affected >= 0),
    is_escalated        BOOLEAN       NOT NULL DEFAULT FALSE,
    root_cause_notes    TEXT,                            -- unstructured field
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    -- A resolved incident must have a resolved_at timestamp
    CONSTRAINT chk_resolution CHECK (
        (resolved_at IS NULL) OR (resolved_at > reported_at)
    )
);


-- ── 6. INCIDENT ASSIGNMENT ────────────────────────────────
--  Many-to-many: multiple engineers can work one incident.
--  Tracks who was the lead vs. supporting role.

CREATE TABLE incident_assignment (
    assignment_id   SERIAL        PRIMARY KEY,
    incident_id     INT           NOT NULL REFERENCES outage_incident(incident_id),
    engineer_id     INT           NOT NULL REFERENCES engineer(engineer_id),
    role            VARCHAR(20)   NOT NULL
                    CHECK (role IN ('LEAD','SUPPORT','ESCALATION')),
    assigned_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    released_at     TIMESTAMPTZ,

    UNIQUE (incident_id, engineer_id)   -- one engineer, one role per incident
);


-- ── 7. RESOLUTION LOG ─────────────────────────────────────
--  Records which action(s) resolved each incident.
--  One incident can require multiple actions.

CREATE TABLE resolution_log (
    log_id          SERIAL        PRIMARY KEY,
    incident_id     INT           NOT NULL REFERENCES outage_incident(incident_id),
    action_id       INT           NOT NULL REFERENCES resolution_action(action_id),
    performed_by    INT           NOT NULL REFERENCES engineer(engineer_id),
    performed_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    notes           TEXT,

    UNIQUE (incident_id, action_id)
);


-- ── 8. OUTAGE EXTRACT LINK ────────────────────────────────
--  Links Day 1 Parquet extract rows into the relational model.
--  Allows JOIN between the pipeline output and this schema.

CREATE TABLE extract_link (
    link_id         SERIAL        PRIMARY KEY,
    outage_id       VARCHAR(20)   NOT NULL UNIQUE,  -- "OUT-0001" from Day 1
    incident_id     INT           REFERENCES outage_incident(incident_id),
    linked_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    notes           TEXT
);


-- ── 9. INDEXES ────────────────────────────────────────────
--  Cover the most common query patterns.

-- Incident lookups by tower and time range
CREATE INDEX idx_incident_tower     ON outage_incident(tower_id);
CREATE INDEX idx_incident_reported  ON outage_incident(reported_at DESC);
CREATE INDEX idx_incident_severity  ON outage_incident(severity_id);
CREATE INDEX idx_incident_escalated ON outage_incident(is_escalated)
    WHERE is_escalated = TRUE;   -- partial index – only escalated rows

-- Assignment lookups by engineer
CREATE INDEX idx_assign_engineer    ON incident_assignment(engineer_id);
CREATE INDEX idx_assign_incident    ON incident_assignment(incident_id);

-- Tower lookups by carrier and province
CREATE INDEX idx_tower_carrier      ON tower(carrier_id);
CREATE INDEX idx_tower_province     ON tower(province_code);

-- Resolution lookups
CREATE INDEX idx_reslog_incident    ON resolution_log(incident_id);
CREATE INDEX idx_reslog_engineer    ON resolution_log(performed_by);

-- Geo index (useful if connecting to PostGIS later)
CREATE INDEX idx_tower_geo          ON tower(province_code, city);


-- ── 10. ANALYTICAL VIEWS ──────────────────────────────────
--  Pre-built queries that the Day 1 analysis mapped to.

CREATE VIEW v_incident_summary AS
SELECT
    oi.incident_ref,
    t.tower_code,
    t.city,
    t.province_code,
    c.carrier_name,
    ot.type_code                        AS outage_type,
    sl.label                            AS severity,
    oi.reported_at,
    oi.resolved_at,
    oi.duration_min,
    oi.customers_affected,
    oi.is_escalated,
    oi.root_cause_notes
FROM outage_incident  oi
JOIN tower            t   ON t.tower_id        = oi.tower_id
JOIN carrier          c   ON c.carrier_id      = t.carrier_id
JOIN outage_type      ot  ON ot.outage_type_id = oi.outage_type_id
JOIN severity_level   sl  ON sl.severity_id    = oi.severity_id;


CREATE VIEW v_engineer_workload AS
SELECT
    e.employee_no,
    e.full_name,
    e.specialisation,
    COUNT(ia.incident_id)                   AS total_incidents,
    SUM(CASE WHEN ia.role = 'LEAD'
             THEN 1 ELSE 0 END)             AS led_incidents,
    SUM(oi.customers_affected)              AS total_customers_handled,
    ROUND(AVG(oi.duration_min)::NUMERIC, 1) AS avg_resolution_min
FROM engineer          e
JOIN incident_assignment ia ON ia.engineer_id  = e.engineer_id
JOIN outage_incident    oi  ON oi.incident_id  = ia.incident_id
GROUP BY e.engineer_id, e.employee_no, e.full_name, e.specialisation;


CREATE VIEW v_sla_compliance AS
SELECT
    sl.label                                        AS severity,
    sl.sla_resolve_min,
    COUNT(*)                                        AS total_incidents,
    SUM(CASE WHEN oi.duration_min <= sl.sla_resolve_min
             THEN 1 ELSE 0 END)                     AS within_sla,
    ROUND(100.0 *
          SUM(CASE WHEN oi.duration_min <= sl.sla_resolve_min
                   THEN 1 ELSE 0 END) / COUNT(*),1) AS sla_pct
FROM outage_incident oi
JOIN severity_level  sl ON sl.severity_id = oi.severity_id
WHERE oi.resolved_at IS NOT NULL
GROUP BY sl.severity_id, sl.label, sl.sla_resolve_min
ORDER BY sl.severity_id;


-- ============================================================
--  SCHEMA COMPLETE
--  Next steps:
--    1. Run day2_seed.py to populate with synthetic data
--    2. Run day2_queries.sql for analytical query examples
--    3. Export ERD from dbdiagram.io using day2_dbdiagram.txt
-- ============================================================
