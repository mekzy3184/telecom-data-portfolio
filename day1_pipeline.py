"""
Day 1 – Data Extract Pipeline
Telecom Network Outage Analysis
================================
Combines structured CSV data + unstructured incident logs
into a single linked extract, then queries it with DuckDB.

Covers:
  - Fetching real open data (CRTC / open.canada.ca)
  - Cleaning & merging structured + unstructured data
  - Persisting to SQLite via SQLAlchemy
  - Analytical SQL queries with DuckDB
  - A simple visualisation dashboard

Run:  python day1_pipeline.py
      (or open in Jupyter: jupyter notebook day1_pipeline.ipynb)
"""

# ── 0. IMPORTS ────────────────────────────────────────────────────────────────
import io
import random
import re
import sqlite3
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import pandas as pd
import requests
from faker import Faker
from sqlalchemy import create_engine, text

fake = Faker("en_CA")
random.seed(42)
Faker.seed(42)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

DB_PATH = OUTPUT_DIR / "telecom_pipeline.db"
EXTRACT_PATH = OUTPUT_DIR / "merged_extract.parquet"
DASHBOARD_PATH = OUTPUT_DIR / "dashboard.png"


# ── 1. FETCH STRUCTURED DATA ─────────────────────────────────────────────────
#
# Real source: CRTC Communications Monitoring Report data
# URL: https://open.canada.ca/data/en/dataset/...
# (network may be restricted in your environment – fallback synthetic data
#  is generated below so the pipeline always runs end-to-end)

CRTC_CSV_URL = (
    "https://open.canada.ca/data/en/datastore/dump/"
    "2b5f7d3b-48db-40d0-a033-2e74f7b5ccc7"
    "?bom=True"
)

PROVINCES = ["MB", "ON", "BC", "AB", "QC", "SK", "NS", "NB", "NL", "PE"]
OUTAGE_TYPES = ["Fibre cut", "Power failure", "Hardware fault",
                "Software bug", "Weather", "Planned maintenance"]

def _synthetic_structured(n: int = 300) -> pd.DataFrame:
    """Generate realistic telecom outage records as a structured DataFrame."""
    start = datetime(2022, 1, 1)
    rows = []
    for i in range(n):
        province = random.choice(PROVINCES)
        otype = random.choice(OUTAGE_TYPES)
        onset = start + timedelta(
            days=random.randint(0, 730),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        duration_min = max(15, int(random.lognormvariate(4.5, 1.2)))
        customers = random.randint(50, 80_000)
        rows.append({
            "outage_id":      f"OUT-{i+1:04d}",
            "province":       province,
            "city":           fake.city(),
            "outage_type":    otype,
            "onset_dt":       onset,
            "duration_min":   duration_min,
            "customers_affected": customers,
            "carrier":        random.choice(["Rogers", "Bell", "Telus",
                                             "Shaw", "Videotron", "SaskTel"]),
        })
    return pd.DataFrame(rows)


def fetch_structured() -> pd.DataFrame:
    """Try the real CRTC open dataset; fall back to synthetic data."""
    print("→ Fetching structured outage data …")
    try:
        resp = requests.get(CRTC_CSV_URL, timeout=10)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        print(f"  ✓ Downloaded real CRTC data  ({len(df):,} rows)")
        return df
    except Exception as exc:
        print(f"  ⚠ Could not reach open.canada.ca ({exc})")
        print("  ✓ Falling back to synthetic outage records (300 rows)")
        return _synthetic_structured(300)


# ── 2. GENERATE UNSTRUCTURED INCIDENT LOGS ───────────────────────────────────
#
# In a real project these would be:
#   - engineer field notes (plain text)
#   - email threads exported as .txt
#   - ticket descriptions from a CRM
#
# We generate them here so you can see exactly what parsing logic is needed.

LOG_TEMPLATES = [
    "Technician {name} attended site at {time}. Issue: {issue}. "
    "Resolution: {fix}. Customers restored after {mins} minutes.",
    "ESCALATION – {name} – outage ref {ref}. Root cause identified as "
    "{issue}. Crew dispatched. Full service restored at {time}.",
    "Automated alert triggered at {time}. {issue} detected on node "
    "{node}. On-call engineer {name} paged. Resolved in {mins} min.",
    "Field report by {name}: attended {city} exchange. {issue}. "
    "Temporary fix applied at {time}; permanent repair scheduled.",
]

ISSUES = ["fibre cut on main trunk", "battery backup exhausted",
          "firmware update loop", "water ingress in cabinet",
          "power surge from lightning strike", "misconfigured routing table"]
FIXES  = ["spliced and re-buried fibre", "replaced UPS unit",
          "rolled back firmware", "sealed cabinet, replaced cards",
          "reset circuit breakers", "reverted routing config"]


def generate_logs(outage_ids: list[str]) -> pd.DataFrame:
    """Return one free-text incident log per outage."""
    print("→ Generating unstructured incident logs …")
    logs = []
    for oid in outage_ids:
        template = random.choice(LOG_TEMPLATES)
        text_body = template.format(
            name=fake.name(),
            time=fake.time(),
            issue=random.choice(ISSUES),
            fix=random.choice(FIXES),
            mins=random.randint(30, 480),
            ref=oid,
            node=f"NODE-{random.randint(100,999)}",
            city=fake.city(),
        )
        logs.append({"outage_id": oid, "log_text": text_body})
    df = pd.DataFrame(logs)
    print(f"  ✓ {len(df):,} incident logs created")
    return df


# ── 3. PARSE UNSTRUCTURED LOGS ────────────────────────────────────────────────
#
# Extract structured fields from raw text using regex.
# This is the "unstructured → structured" step that interviewers care about.

def parse_logs(logs_df: pd.DataFrame) -> pd.DataFrame:
    """Pull key entities out of free-text logs."""
    print("→ Parsing unstructured logs …")

    def extract_engineer(txt: str) -> str:
        # Matches "Technician <Name>" or "by <Name>:" or "engineer <Name>"
        for pat in [
            r"(?:Technician|engineer)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)",
            r"by\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s*[:\-–]",
            r"–\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s+–",
        ]:
            m = re.search(pat, txt)
            if m:
                return m.group(1)
        return "Unknown"

    def extract_duration(txt: str) -> int | None:
        m = re.search(r"(\d+)\s*min(?:utes?)?", txt)
        return int(m.group(1)) if m else None

    def flag_escalation(txt: str) -> bool:
        return bool(re.search(r"ESCALATION|escalat", txt, re.I))

    parsed = logs_df.copy()
    parsed["engineer_name"]  = parsed["log_text"].apply(extract_engineer)
    parsed["log_duration_min"] = parsed["log_text"].apply(extract_duration)
    parsed["is_escalation"]  = parsed["log_text"].apply(flag_escalation)

    print(f"  ✓ Parsed: {parsed['is_escalation'].sum()} escalations flagged")
    return parsed


# ── 4. CLEAN STRUCTURED DATA ──────────────────────────────────────────────────

def clean_structured(df: pd.DataFrame) -> pd.DataFrame:
    print("→ Cleaning structured data …")
    df = df.copy()

    # Ensure datetime type
    if "onset_dt" in df.columns:
        df["onset_dt"] = pd.to_datetime(df["onset_dt"], errors="coerce")

    # Drop rows with no outage_id or province
    before = len(df)
    df = df.dropna(subset=["outage_id", "province"])
    print(f"  ✓ Dropped {before - len(df)} rows with missing keys")

    # Normalise province codes to uppercase
    if "province" in df.columns:
        df["province"] = df["province"].str.upper().str.strip()

    # Cap implausible durations (> 10 days = data error)
    if "duration_min" in df.columns:
        df["duration_min"] = df["duration_min"].clip(upper=14_400)

    # Derive useful columns
    if "onset_dt" in df.columns:
        df["year"]    = df["onset_dt"].dt.year
        df["month"]   = df["onset_dt"].dt.month
        df["weekday"] = df["onset_dt"].dt.day_name()

    return df


# ── 5. MERGE STRUCTURED + PARSED LOGS ────────────────────────────────────────

def build_extract(structured: pd.DataFrame,
                  parsed_logs: pd.DataFrame) -> pd.DataFrame:
    print("→ Merging structured data with parsed log fields …")
    extract = structured.merge(
        parsed_logs[["outage_id", "log_text",
                     "engineer_name", "log_duration_min", "is_escalation"]],
        on="outage_id",
        how="left",
    )
    print(f"  ✓ Extract shape: {extract.shape[0]:,} rows × {extract.shape[1]} columns")
    return extract


# ── 6. PERSIST TO SQLITE VIA SQLALCHEMY ──────────────────────────────────────

def persist_to_db(extract: pd.DataFrame,
                  logs_df: pd.DataFrame) -> None:
    print("→ Writing to SQLite via SQLAlchemy …")
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
    with engine.begin() as conn:
        extract.to_sql("outage_events",  conn, if_exists="replace", index=False)
        logs_df.to_sql("incident_logs",  conn, if_exists="replace", index=False)
    print(f"  ✓ Saved to {DB_PATH}")

    # Also export a Parquet file for sharing / downstream use
    extract.to_parquet(EXTRACT_PATH, index=False)
    print(f"  ✓ Parquet extract saved to {EXTRACT_PATH}")


# ── 7. ANALYTICAL QUERIES WITH DUCKDB ────────────────────────────────────────
#
# DuckDB can query Parquet files directly — no server needed.
# These queries mirror what you would run in a real analytics context.

QUERIES = {
    "outages_by_province": """
        SELECT province,
               COUNT(*)                                AS total_outages,
               ROUND(AVG(duration_min), 1)             AS avg_duration_min,
               SUM(customers_affected)                 AS total_customers_hit
        FROM read_parquet('{path}')
        GROUP BY province
        ORDER BY total_outages DESC
    """,

    "worst_outage_types": """
        SELECT outage_type,
               COUNT(*)                                AS incidents,
               ROUND(AVG(duration_min), 1)             AS avg_duration_min,
               ROUND(AVG(customers_affected), 0)       AS avg_customers
        FROM read_parquet('{path}')
        GROUP BY outage_type
        ORDER BY avg_duration_min DESC
    """,

    "escalation_rate_by_carrier": """
        SELECT carrier,
               COUNT(*)                                AS total,
               SUM(CAST(is_escalation AS INTEGER))     AS escalations,
               ROUND(100.0 * SUM(CAST(is_escalation AS INTEGER))
                     / COUNT(*), 1)                    AS escalation_pct
        FROM read_parquet('{path}')
        GROUP BY carrier
        ORDER BY escalation_pct DESC
    """,

    "monthly_trend": """
        SELECT year, month,
               COUNT(*)                                AS outages,
               SUM(customers_affected)                 AS customers_affected
        FROM read_parquet('{path}')
        GROUP BY year, month
        ORDER BY year, month
    """,

    "top10_longest_outages": """
        SELECT outage_id, province, carrier, outage_type,
               duration_min, customers_affected, engineer_name
        FROM read_parquet('{path}')
        ORDER BY duration_min DESC
        LIMIT 10
    """,
}


def run_queries(parquet_path: Path) -> dict[str, pd.DataFrame]:
    print("→ Running DuckDB analytical queries …")
    con = duckdb.connect()
    results = {}
    for name, sql in QUERIES.items():
        formatted = textwrap.dedent(sql).format(path=str(parquet_path))
        results[name] = con.execute(formatted).df()
        print(f"  ✓ {name}  ({len(results[name])} rows)")
    con.close()
    return results


# ── 8. DASHBOARD ──────────────────────────────────────────────────────────────

def build_dashboard(results: dict[str, pd.DataFrame]) -> None:
    print("→ Building dashboard …")

    prov   = results["outages_by_province"]
    types  = results["worst_outage_types"]
    carr   = results["escalation_rate_by_carrier"]
    trend  = results["monthly_trend"]

    fig = plt.figure(figsize=(16, 10), facecolor="#f8f8f6")
    fig.suptitle(
        "Telecom Outage Analysis Dashboard  —  Data Extract Pipeline (Day 1)",
        fontsize=14, fontweight="bold", y=0.98, color="#1a1a1a",
    )

    gs = gridspec.GridSpec(2, 3, figure=fig,
                           hspace=0.45, wspace=0.35,
                           left=0.07, right=0.97,
                           top=0.92, bottom=0.08)

    PURPLE = "#7F77DD"
    TEAL   = "#1D9E75"
    CORAL  = "#D85A30"
    AMBER  = "#EF9F27"

    # ── Panel 1: Outages by province (bar) ───────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.barh(prov["province"][::-1], prov["total_outages"][::-1],
             color=PURPLE, edgecolor="white", linewidth=0.5)
    ax1.set_title("Outages by province", fontsize=11, fontweight="bold", pad=8)
    ax1.set_xlabel("Total outages", fontsize=9)
    ax1.tick_params(labelsize=9)
    ax1.set_facecolor("#f8f8f6")
    for spine in ax1.spines.values():
        spine.set_visible(False)
    ax1.axvline(0, color="#ccc", linewidth=0.5)

    # ── Panel 2: Avg outage duration by type ─────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    colors = [CORAL if v == types["avg_duration_min"].max() else TEAL
              for v in types["avg_duration_min"]]
    bars = ax2.barh(types["outage_type"][::-1],
                    types["avg_duration_min"][::-1],
                    color=colors[::-1], edgecolor="white", linewidth=0.5)
    ax2.set_title("Avg duration by outage type (min)", fontsize=11,
                  fontweight="bold", pad=8)
    ax2.set_xlabel("Minutes", fontsize=9)
    ax2.tick_params(labelsize=8)
    ax2.set_facecolor("#f8f8f6")
    for spine in ax2.spines.values():
        spine.set_visible(False)

    # ── Panel 3: Escalation rate by carrier (horizontal bar) ─────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.barh(carr["carrier"][::-1], carr["escalation_pct"][::-1],
             color=AMBER, edgecolor="white", linewidth=0.5)
    ax3.set_title("Escalation rate by carrier (%)", fontsize=11,
                  fontweight="bold", pad=8)
    ax3.set_xlabel("% escalated", fontsize=9)
    ax3.tick_params(labelsize=9)
    ax3.set_facecolor("#f8f8f6")
    for spine in ax3.spines.values():
        spine.set_visible(False)

    # ── Panel 4: Monthly trend (line) ─────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, :2])
    trend["period"] = (trend["year"].astype(str) + "-"
                       + trend["month"].astype(str).str.zfill(2))
    ax4.plot(trend["period"], trend["outages"],
             color=PURPLE, linewidth=2, marker="o", markersize=4)
    ax4.fill_between(trend["period"], trend["outages"],
                     alpha=0.12, color=PURPLE)
    ax4.set_title("Monthly outage count", fontsize=11,
                  fontweight="bold", pad=8)
    ax4.set_xlabel("Month", fontsize=9)
    ax4.set_ylabel("Outages", fontsize=9)
    ax4.tick_params(axis="x", labelsize=7, rotation=45)
    ax4.tick_params(axis="y", labelsize=9)
    ax4.set_facecolor("#f8f8f6")
    for spine in ax4.spines.values():
        spine.set_visible(False)
    ax4.grid(axis="y", color="#ddd", linewidth=0.5, linestyle="--")

    # ── Panel 5: Summary metrics ───────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 2])
    ax5.axis("off")
    total_outages   = prov["total_outages"].sum()
    total_customers = prov["total_customers_hit"].sum()
    avg_dur         = results["worst_outage_types"]["avg_duration_min"].mean()
    worst_province  = prov.iloc[0]["province"]

    metrics = [
        ("Total outages", f"{total_outages:,}"),
        ("Customers affected", f"{total_customers:,.0f}"),
        ("Avg duration", f"{avg_dur:.0f} min"),
        ("Most affected province", worst_province),
    ]
    y = 0.85
    for label, value in metrics:
        ax5.text(0.05, y, label, fontsize=9, color="#666",
                 transform=ax5.transAxes)
        ax5.text(0.05, y - 0.1, value, fontsize=14, fontweight="bold",
                 color="#1a1a1a", transform=ax5.transAxes)
        y -= 0.25
    ax5.set_title("Key metrics", fontsize=11, fontweight="bold", pad=8)
    ax5.set_facecolor("#f8f8f6")

    fig.savefig(DASHBOARD_PATH, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  ✓ Dashboard saved to {DASHBOARD_PATH}")


# ── 9. MAIN ───────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  Day 1 – Telecom Outage Data Extract Pipeline")
    print("═" * 60 + "\n")

    # Step 1 – Ingest
    structured  = fetch_structured()
    structured  = clean_structured(structured)

    # Step 2 – Unstructured
    logs_raw    = generate_logs(structured["outage_id"].tolist())
    logs_parsed = parse_logs(logs_raw)

    # Step 3 – Merge
    extract     = build_extract(structured, logs_parsed)

    # Step 4 – Persist
    persist_to_db(extract, logs_raw)

    # Step 5 – Query
    results     = run_queries(EXTRACT_PATH)

    # Step 6 – Visualise
    build_dashboard(results)

    # Print sample query output for inspection
    print("\n── Sample: worst outage types ──────────────────────────")
    print(results["worst_outage_types"].to_string(index=False))
    print("\n── Sample: escalation rate by carrier ──────────────────")
    print(results["escalation_rate_by_carrier"].to_string(index=False))

    print("\n" + "═" * 60)
    print("  Pipeline complete. Outputs written to ./outputs/")
    print(f"  • {EXTRACT_PATH.name}     ← shareable data extract")
    print(f"  • {DB_PATH.name}  ← SQLite database (SQLAlchemy)")
    print(f"  • {DASHBOARD_PATH.name}      ← visualisation dashboard")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
