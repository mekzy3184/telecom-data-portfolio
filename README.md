# Telecom Network Outage – Data Portfolio

A two-day end-to-end data project demonstrating data analysis, extract pipeline engineering, relational database design, and systems analysis — applied to a Canadian telecom network outage domain.

---

## Day 1 – Data Extract Pipeline

**Skills demonstrated:**
- Ingesting structured data (CSV) from open government sources (open.canada.ca)
- Generating and parsing unstructured free-text incident logs using regex
- Cleaning, merging, and linking large multi-source data extracts with pandas
- Persisting data to a relational database via SQLAlchemy
- Exporting a columnar Parquet extract for downstream use
- Running analytical SQL queries on Parquet files using DuckDB (no server required)
- Building a multi-panel visualisation dashboard with matplotlib

**Output files:**
| File | Description |
|------|-------------|
| `day1_pipeline.py` | Full extract pipeline — ingest, clean, merge, persist, query, visualise |
| `outputs/merged_extract.parquet` | Linked structured + unstructured data extract |
| `outputs/telecom_pipeline.db` | SQLite database (SQLAlchemy) |
| `outputs/dashboard.png` | Visualisation dashboard |

**Dashboard preview:**

![Dashboard](outputs/dashboard.png)

---

## Day 2 – Database Design, Modeling & Systems Analysis

**Skills demonstrated:**
- Designing a normalised (3NF) relational schema from a real-world domain
- Writing production-grade DDL with constraints, indexes, computed columns, and partial indexes
- Entity relationship modeling (ERD) using dbdiagram.io
- Populating a database with realistic synthetic data using Faker
- Writing multi-table JOIN queries linking the Day 1 extract into the relational model
- Building analytical views for incident summaries, engineer workload, and SLA compliance

**Schema overview:**

| Table | Description |
|-------|-------------|
| `province` | Reference — Canadian province codes |
| `carrier` | Telecom carriers (Rogers, Bell, Telus, etc.) |
| `tower` | Physical network sites (cell towers, exchanges, fibre nodes) |
| `engineer` | Field and network engineers |
| `outage_incident` | Core fact table — one row per outage event |
| `outage_type` | Reference — outage categories |
| `severity_level` | Reference — P1–P4 with SLA thresholds |
| `incident_assignment` | Many-to-many: engineers assigned to incidents |
| `resolution_action` | Reference — remediation action types |
| `resolution_log` | Actions taken to resolve each incident |
| `extract_link` | Links Day 1 Parquet extract rows into the relational model |

**Output files:**
| File | Description |
|------|-------------|
| `day2_schema.sql` | Full PostgreSQL DDL script |
| `day2_seed.py` | Seeds schema with synthetic data via Faker |
| `outputs/telecom_network.db` | Populated SQLite database |
| `day2_erd.png` | Entity relationship diagram |

**ERD:**

![ERD](day2_erd.png)

---

## How to run

**Install dependencies:**
```bash
pip install pandas duckdb sqlalchemy faker requests pyarrow matplotlib
```

**Day 1 — run the extract pipeline:**
```bash
python day1_pipeline.py
```

**Day 2 — seed the relational database:**
```bash
python day2_seed.py
```

---

## Tech stack

`Python` `pandas` `DuckDB` `SQLAlchemy` `SQLite` `PostgreSQL` `Faker` `matplotlib` `pyarrow`

---

## Author

Emeka — Engineer-in-Training (EIT) | CompTIA A+ | AWS Cloud Practitioner  
Winnipeg, Manitoba, Canada
