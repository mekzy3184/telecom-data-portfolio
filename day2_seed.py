"""
Day 2 – Database Seed Script
==============================
Populates the telecom schema with realistic synthetic data using Faker,
then runs JOIN queries that link Day 1's extract into the relational model.

Works with:  SQLite  (default, zero-config)
             PostgreSQL  (set USE_POSTGRES = True below)

Run:  python day2_seed.py
"""

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

# ── CONFIG ────────────────────────────────────────────────────────────────────
USE_POSTGRES = False   # flip to True + fill PG_DSN for real PostgreSQL
PG_DSN = "postgresql://user:password@localhost:5432/telecom_db"

SQLITE_PATH = Path("outputs/telecom_network.db")
SQLITE_PATH.parent.mkdir(exist_ok=True)

fake = Faker("en_CA")
random.seed(7)
Faker.seed(7)

# ── REFERENCE DATA (mirrors DDL lookups) ─────────────────────────────────────
PROVINCES = [
    ("AB","Alberta"),("BC","British Columbia"),("MB","Manitoba"),
    ("NB","New Brunswick"),("NL","Newfoundland and Labrador"),
    ("NS","Nova Scotia"),("ON","Ontario"),("PE","Prince Edward Island"),
    ("QC","Quebec"),("SK","Saskatchewan"),
]
OUTAGE_TYPES = [
    (1,"FIBRE_CUT"),(2,"POWER_FAIL"),(3,"HW_FAULT"),
    (4,"SW_BUG"),(5,"WEATHER"),(6,"PLANNED_MAINT"),
]
SEVERITY = [
    (1,"P1 – Critical",15,240),(2,"P2 – High",30,480),
    (3,"P3 – Medium",60,1440),(4,"P4 – Low",240,4320),
]
RESOLUTION_ACTIONS = [
    (1,"FIBRE_SPLICE"),(2,"UPS_REPLACE"),(3,"FW_ROLLBACK"),
    (4,"HW_SWAP"),(5,"CONFIG_REVERT"),(6,"CABINET_SEAL"),
    (7,"GENERATOR_START"),(8,"REMOTE_RESET"),
]
CARRIERS = [
    ("Rogers","RCI","ON"),("Bell","BCE","QC"),("Telus","T","BC"),
    ("Shaw","SJR","AB"),("Videotron","QBR","QC"),("SaskTel",None,"SK"),
]
SITE_TYPES = ["CELL_TOWER","EXCHANGE","DATA_CENTRE","FIBRE_NODE"]
SPECIALISATIONS = [
    "RF Optimisation","Fibre Splicing","Core Network",
    "Power Systems","Software/Firmware","Field Operations",
]

# ── SQLITE DDL (simplified, mirrors PostgreSQL schema) ────────────────────────
SQLITE_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS province (
    province_code TEXT PRIMARY KEY,
    province_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outage_type (
    outage_type_id INTEGER PRIMARY KEY,
    type_code TEXT NOT NULL UNIQUE,
    description TEXT
);
CREATE TABLE IF NOT EXISTS severity_level (
    severity_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    sla_response_min INTEGER NOT NULL,
    sla_resolve_min  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS resolution_action (
    action_id INTEGER PRIMARY KEY,
    action_code TEXT NOT NULL UNIQUE,
    description TEXT
);
CREATE TABLE IF NOT EXISTS carrier (
    carrier_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    carrier_name TEXT NOT NULL UNIQUE,
    ticker_symbol TEXT,
    hq_province  TEXT REFERENCES province(province_code),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tower (
    tower_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tower_code      TEXT NOT NULL UNIQUE,
    carrier_id      INTEGER NOT NULL REFERENCES carrier(carrier_id),
    site_type       TEXT NOT NULL,
    city            TEXT NOT NULL,
    province_code   TEXT NOT NULL REFERENCES province(province_code),
    latitude        REAL,
    longitude       REAL,
    commissioned_dt TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS engineer (
    engineer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_no    TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    phone          TEXT,
    specialisation TEXT,
    province_code  TEXT REFERENCES province(province_code),
    hire_date      TEXT,
    is_oncall      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS outage_incident (
    incident_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_ref        TEXT NOT NULL UNIQUE,
    tower_id            INTEGER NOT NULL REFERENCES tower(tower_id),
    outage_type_id      INTEGER NOT NULL REFERENCES outage_type(outage_type_id),
    severity_id         INTEGER NOT NULL REFERENCES severity_level(severity_id),
    reported_at         TEXT NOT NULL,
    resolved_at         TEXT,
    duration_min        INTEGER,
    customers_affected  INTEGER NOT NULL DEFAULT 0,
    is_escalated        INTEGER NOT NULL DEFAULT 0,
    root_cause_notes    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS incident_assignment (
    assignment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id    INTEGER NOT NULL REFERENCES outage_incident(incident_id),
    engineer_id    INTEGER NOT NULL REFERENCES engineer(engineer_id),
    role           TEXT NOT NULL CHECK(role IN ('LEAD','SUPPORT','ESCALATION')),
    assigned_at    TEXT NOT NULL DEFAULT (datetime('now')),
    released_at    TEXT,
    UNIQUE(incident_id, engineer_id)
);
CREATE TABLE IF NOT EXISTS resolution_log (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id    INTEGER NOT NULL REFERENCES outage_incident(incident_id),
    action_id      INTEGER NOT NULL REFERENCES resolution_action(action_id),
    performed_by   INTEGER NOT NULL REFERENCES engineer(engineer_id),
    performed_at   TEXT NOT NULL DEFAULT (datetime('now')),
    notes          TEXT,
    UNIQUE(incident_id, action_id)
);
CREATE TABLE IF NOT EXISTS extract_link (
    link_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    outage_id   TEXT NOT NULL UNIQUE,
    incident_id INTEGER REFERENCES outage_incident(incident_id),
    linked_at   TEXT NOT NULL DEFAULT (datetime('now')),
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_incident_tower    ON outage_incident(tower_id);
CREATE INDEX IF NOT EXISTS idx_incident_reported ON outage_incident(reported_at);
CREATE INDEX IF NOT EXISTS idx_assign_engineer   ON incident_assignment(engineer_id);
CREATE INDEX IF NOT EXISTS idx_tower_carrier     ON tower(carrier_id);
"""


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def rand_dt(start_year=2022, span_days=730) -> datetime:
    base = datetime(start_year, 1, 1)
    return base + timedelta(
        days=random.randint(0, span_days),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


# ── SEED FUNCTIONS ────────────────────────────────────────────────────────────

def seed_lookups(cur):
    cur.executemany("INSERT OR IGNORE INTO province VALUES (?,?)", PROVINCES)
    cur.executemany(
        "INSERT OR IGNORE INTO outage_type(outage_type_id,type_code) VALUES (?,?)",
        [(r[0], r[1]) for r in OUTAGE_TYPES],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO severity_level VALUES (?,?,?,?)", SEVERITY
    )
    cur.executemany(
        "INSERT OR IGNORE INTO resolution_action(action_id,action_code) VALUES (?,?)",
        RESOLUTION_ACTIONS,
    )
    print("  ✓ Lookup tables seeded")


def seed_carriers(cur) -> list[int]:
    ids = []
    for name, ticker, prov in CARRIERS:
        cur.execute(
            "INSERT OR IGNORE INTO carrier(carrier_name,ticker_symbol,hq_province) "
            "VALUES (?,?,?)", (name, ticker, prov)
        )
        cur.execute("SELECT carrier_id FROM carrier WHERE carrier_name=?", (name,))
        ids.append(cur.fetchone()[0])
    print(f"  ✓ {len(ids)} carriers seeded")
    return ids


def seed_towers(cur, carrier_ids: list[int], n: int = 60) -> list[int]:
    rows = []
    for i in range(n):
        prov_code, _ = random.choice(PROVINCES)
        carrier_id   = random.choice(carrier_ids)
        site_type    = random.choice(SITE_TYPES)
        code         = f"{prov_code}-{site_type[:3]}-{i+1:04d}"
        lat          = round(random.uniform(42.0, 60.0), 6)
        lon          = round(random.uniform(-140.0, -52.0), 6)
        comm         = fake.date_between(start_date="-15y", end_date="-1y")
        rows.append((code, carrier_id, site_type, fake.city(),
                     prov_code, lat, lon, str(comm)))

    cur.executemany(
        "INSERT OR IGNORE INTO tower"
        "(tower_code,carrier_id,site_type,city,province_code,"
        " latitude,longitude,commissioned_dt) "
        "VALUES (?,?,?,?,?,?,?,?)", rows
    )
    cur.execute("SELECT tower_id FROM tower")
    ids = [r[0] for r in cur.fetchall()]
    print(f"  ✓ {len(ids)} towers seeded")
    return ids


def seed_engineers(cur, n: int = 30) -> list[int]:
    rows = []
    for i in range(n):
        prov_code, _ = random.choice(PROVINCES)
        hire         = fake.date_between(start_date="-12y", end_date="-6m")
        rows.append((
            f"EMP-{i+1:04d}",
            fake.name(),
            fake.email(),
            fake.phone_number()[:20],
            random.choice(SPECIALISATIONS),
            prov_code,
            str(hire),
            int(random.random() < 0.25),   # 25% on-call
        ))
    cur.executemany(
        "INSERT OR IGNORE INTO engineer"
        "(employee_no,full_name,email,phone,specialisation,"
        " province_code,hire_date,is_oncall) "
        "VALUES (?,?,?,?,?,?,?,?)", rows
    )
    cur.execute("SELECT engineer_id FROM engineer")
    ids = [r[0] for r in cur.fetchall()]
    print(f"  ✓ {len(ids)} engineers seeded")
    return ids


def seed_incidents(cur, tower_ids, n: int = 120) -> list[int]:
    rows = []
    for i in range(n):
        reported    = rand_dt()
        duration    = max(15, int(random.lognormvariate(4.5, 1.2)))
        resolved    = reported + timedelta(minutes=duration)
        escalated   = int(random.random() < 0.28)
        outage_type = random.choice(OUTAGE_TYPES)[0]
        severity    = random.choices([1,2,3,4], weights=[5,20,50,25])[0]
        customers   = random.randint(50, 80_000)
        ref         = f"INC-{reported.year}-{i+1:04d}"
        notes       = (
            f"Root cause: {random.choice(['fibre cut on main trunk','power surge','firmware loop','water ingress'])}. "
            f"Affected area: {fake.city()} exchange."
        )
        rows.append((
            ref, random.choice(tower_ids), outage_type, severity,
            _ts(reported), _ts(resolved), duration,
            customers, escalated, notes,
        ))

    cur.executemany(
        "INSERT OR IGNORE INTO outage_incident"
        "(incident_ref,tower_id,outage_type_id,severity_id,"
        " reported_at,resolved_at,duration_min,"
        " customers_affected,is_escalated,root_cause_notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", rows
    )
    cur.execute("SELECT incident_id FROM outage_incident")
    ids = [r[0] for r in cur.fetchall()]
    print(f"  ✓ {len(ids)} incidents seeded")
    return ids


def seed_assignments(cur, incident_ids, engineer_ids):
    rows = []
    seen = set()
    for inc_id in incident_ids:
        # LEAD: always one
        lead = random.choice(engineer_ids)
        rows.append((inc_id, lead, "LEAD", _ts(rand_dt())))
        seen.add((inc_id, lead))

        # SUPPORT: 0–2 additional engineers
        for _ in range(random.randint(0, 2)):
            eng = random.choice(engineer_ids)
            if (inc_id, eng) not in seen:
                rows.append((inc_id, eng, "SUPPORT", _ts(rand_dt())))
                seen.add((inc_id, eng))

    cur.executemany(
        "INSERT OR IGNORE INTO incident_assignment"
        "(incident_id,engineer_id,role,assigned_at) VALUES (?,?,?,?)", rows
    )
    print(f"  ✓ {len(rows)} assignments seeded")


def seed_resolutions(cur, incident_ids, engineer_ids):
    rows = []
    seen = set()
    for inc_id in incident_ids:
        action = random.choice(RESOLUTION_ACTIONS)[0]
        if (inc_id, action) not in seen:
            rows.append((
                inc_id, action,
                random.choice(engineer_ids),
                _ts(rand_dt()),
                fake.sentence(nb_words=8),
            ))
            seen.add((inc_id, action))

    cur.executemany(
        "INSERT OR IGNORE INTO resolution_log"
        "(incident_id,action_id,performed_by,performed_at,notes) "
        "VALUES (?,?,?,?,?)", rows
    )
    print(f"  ✓ {len(rows)} resolution log entries seeded")


def seed_extract_links(cur, incident_ids):
    """Link Day 1 outage IDs (OUT-0001…) to relational incident rows."""
    rows = [
        (f"OUT-{i+1:04d}", incident_ids[i % len(incident_ids)],
         _ts(datetime.now()), "Linked from Day 1 Parquet extract")
        for i in range(300)
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO extract_link"
        "(outage_id,incident_id,linked_at,notes) VALUES (?,?,?,?)", rows
    )
    print(f"  ✓ {len(rows)} extract links created")


# ── ANALYTICAL QUERIES ────────────────────────────────────────────────────────

QUERIES = {
    "incidents_by_province": """
        SELECT t.province_code,
               COUNT(*)                          AS incidents,
               ROUND(AVG(oi.duration_min),1)     AS avg_duration_min,
               SUM(oi.customers_affected)        AS customers_hit
        FROM outage_incident oi
        JOIN tower t ON t.tower_id = oi.tower_id
        GROUP BY t.province_code
        ORDER BY incidents DESC
    """,

    "engineer_workload": """
        SELECT e.full_name, e.specialisation,
               COUNT(ia.incident_id)             AS incidents,
               SUM(oi.customers_affected)        AS customers_handled
        FROM engineer e
        JOIN incident_assignment ia ON ia.engineer_id = e.engineer_id
        JOIN outage_incident     oi ON oi.incident_id = ia.incident_id
        GROUP BY e.engineer_id
        ORDER BY incidents DESC
        LIMIT 10
    """,

    "sla_compliance": """
        SELECT sl.label,
               sl.sla_resolve_min,
               COUNT(*)                          AS total,
               SUM(CASE WHEN oi.duration_min <= sl.sla_resolve_min
                        THEN 1 ELSE 0 END)       AS within_sla,
               ROUND(100.0 *
                     SUM(CASE WHEN oi.duration_min <= sl.sla_resolve_min
                              THEN 1 ELSE 0 END)
                     / COUNT(*), 1)              AS sla_pct
        FROM outage_incident oi
        JOIN severity_level sl ON sl.severity_id = oi.severity_id
        GROUP BY sl.severity_id, sl.label, sl.sla_resolve_min
        ORDER BY sl.severity_id
    """,

    "day1_extract_join": """
        SELECT el.outage_id,
               oi.incident_ref,
               t.tower_code,
               t.city,
               ot.type_code   AS outage_type,
               oi.duration_min,
               oi.customers_affected
        FROM extract_link    el
        JOIN outage_incident oi ON oi.incident_id  = el.incident_id
        JOIN tower           t  ON t.tower_id      = oi.tower_id
        JOIN outage_type     ot ON ot.outage_type_id = oi.outage_type_id
        LIMIT 10
    """,
}


def run_queries(con):
    import pandas as pd
    print("\n── Analytical query results ────────────────────────────────")
    for name, sql in QUERIES.items():
        df = pd.read_sql_query(sql, con)
        print(f"\n▸ {name}")
        print(df.to_string(index=False))


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  Day 2 – Telecom Network Events Database Seed")
    print("═" * 60 + "\n")

    if USE_POSTGRES:
        import psycopg2
        con_raw = psycopg2.connect(PG_DSN)
        print("  Connected to PostgreSQL")
        print("  → Run day2_schema.sql first via psql, then re-run this script.")
    else:
        import sqlite3
        con_raw = sqlite3.connect(SQLITE_PATH)
        print(f"  Using SQLite at {SQLITE_PATH}")

    cur = con_raw.cursor()

    if not USE_POSTGRES:
        # Create tables from embedded SQLite DDL
        cur.executescript(SQLITE_DDL)

    print("→ Seeding reference data …")
    seed_lookups(cur)

    print("→ Seeding entities …")
    carrier_ids  = seed_carriers(cur)
    tower_ids    = seed_towers(cur, carrier_ids, n=60)
    engineer_ids = seed_engineers(cur, n=30)

    print("→ Seeding transactions …")
    incident_ids = seed_incidents(cur, tower_ids, n=120)
    seed_assignments(cur, incident_ids, engineer_ids)
    seed_resolutions(cur, incident_ids, engineer_ids)
    seed_extract_links(cur, incident_ids)

    con_raw.commit()

    # Run analytical queries
    import sqlite3 as _sq
    con_pd = _sq.connect(SQLITE_PATH)
    run_queries(con_pd)
    con_pd.close()

    con_raw.close()

    print(f"\n{'═'*60}")
    print(f"  Database ready at {SQLITE_PATH}")
    print("  Outputs for portfolio:")
    print("  • day2_schema.sql       ← DDL (submit this to employers)")
    print("  • outputs/telecom_network.db  ← populated SQLite DB")
    print("  • Import day2_dbdiagram.txt into dbdiagram.io for ERD")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
