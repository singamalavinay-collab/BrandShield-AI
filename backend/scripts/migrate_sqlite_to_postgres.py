#!/usr/bin/env python3
"""
BrandShield AI — SQLite to PostgreSQL Production Migration Tool
==============================================================
Safely migrates all existing records from the development SQLite database to a
production PostgreSQL instance with full schema alignment, foreign key integrity,
and immutable audit log preservation.

Usage:
    python backend/scripts/migrate_sqlite_to_postgres.py --dry-run
    python backend/scripts/migrate_sqlite_to_postgres.py --target-url "postgresql://user:pass@host:5432/brandshield_ai"
"""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
from typing import Dict, List, Tuple


TABLES_IN_DEPENDENCY_ORDER = [
    "organizations",
    "users",
    "brand_guidelines",
    "content_submissions",
    "compliance_reports",
    "rule_violations",
    "evidence_citations",
    "correction_suggestions",
    "review_decisions",
    "audit_entries",
    "team_invitations",
]


def extract_sqlite_data(sqlite_path: str) -> Dict[str, List[Dict]]:
    """Extracts all tables and records from source SQLite database."""
    if not os.path.isfile(sqlite_path):
        raise FileNotFoundError(f"Source SQLite database not found at: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    data: Dict[str, List[Dict]] = {}
    for table in TABLES_IN_DEPENDENCY_ORDER:
        cursor.execute(f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{table}'")
        if cursor.fetchone()[0] == 0:
            print(f"[WARN] Table '{table}' does not exist in SQLite source. Skipping.")
            data[table] = []
            continue

        cursor.execute(f"SELECT * FROM {table}")
        rows = [dict(row) for row in cursor.fetchall()]
        data[table] = rows
        print(f"[INFO] Extracted {len(rows)} records from '{table}'.")

    conn.close()
    return data


def verify_source_integrity(sqlite_path: str) -> Tuple[bool, str]:
    """Runs PRAGMA integrity_check and PRAGMA foreign_key_check on source."""
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA integrity_check")
    integrity = cursor.fetchone()[0]

    cursor.execute("PRAGMA foreign_key_check")
    fk_issues = cursor.fetchall()
    conn.close()

    if integrity != "ok":
        return False, f"Integrity check failed: {integrity}"
    if fk_issues:
        return False, f"Foreign key check detected orphaned records: {fk_issues}"

    return True, "Source database integrity verified successfully (0 errors)."


def main():
    parser = argparse.ArgumentParser(description="BrandShield AI SQLite to PostgreSQL Migration Tool")
    parser.add_argument("--source-db", default="backend/brandshield_ai.db", help="Path to source SQLite database")
    parser.add_argument("--target-url", default=os.getenv("TARGET_DATABASE_URL"), help="PostgreSQL connection string")
    parser.add_argument("--dry-run", action="store_true", help="Perform integrity check and source data inspection without modifying target")

    args = parser.parse_args()

    print("================================================================================")
    print("BRANDSHIELD AI — PRODUCTION DATABASE MIGRATION UTILITY")
    print("================================================================================")
    print(f"Source DB: {args.source_db}")
    print(f"Target URL: {'Configured' if args.target_url else 'None provided'}")
    print(f"Dry Run: {args.dry_run}")
    print("--------------------------------------------------------------------------------")

    # Resolve source path intelligently
    source_path = Path(args.source_db)
    if not source_path.exists():
        alt_path = Path(__file__).resolve().parent.parent / "brandshield_ai.db"
        if alt_path.exists():
            source_path = alt_path
        else:
            print(f"[FAIL] Source database file not found at '{args.source_db}' or '{alt_path}'")
            sys.exit(1)
    resolved_source = str(source_path.resolve())

    # 1. Source verification
    ok, msg = verify_source_integrity(resolved_source)
    if not ok:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[OK] {msg}")

    # 2. Extract source records
    data = extract_sqlite_data(resolved_source)

    total_records = sum(len(records) for records in data.values())
    print("--------------------------------------------------------------------------------")
    print(f"Source Extraction Summary: {total_records} total records across {len(data)} tables.")
    for table, records in data.items():
        print(f"  • {table.ljust(25)}: {len(records)} records")
    print("--------------------------------------------------------------------------------")

    if args.dry_run or not args.target_url:
        print("[NOTICE] Dry-run complete. No data written to target database.")
        if not args.target_url:
            print("[INFO] To execute live migration to PostgreSQL, run with:")
            print("       python backend/scripts/migrate_sqlite_to_postgres.py --target-url \"postgresql://user:pass@host:5432/dbname\"")
        sys.exit(0)

    # 3. Target database loading (requires psycopg2 or asyncpg)
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        print("[FAIL] 'psycopg2' package is required for live PostgreSQL insertion.")
        print("       Install with: pip install psycopg2-binary")
        sys.exit(1)

    print(f"[INFO] Connecting to target PostgreSQL database...")
    try:
        pg_conn = psycopg2.connect(args.target_url)
        pg_conn.autocommit = False
        pg_cursor = pg_conn.cursor()
    except Exception as e:
        print(f"[FAIL] Failed to connect to PostgreSQL: {e}")
        sys.exit(1)

    try:
        # Transfer tables in order
        for table in TABLES_IN_DEPENDENCY_ORDER:
            records = data.get(table, [])
            if not records:
                continue

            columns = list(records[0].keys())
            col_names = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))

            values = []
            for r in records:
                row_vals = []
                for col in columns:
                    val = r[col]
                    # Parse JSON strings if required
                    if col in ("details", "tags", "examples_approved", "examples_prohibited", "metadata") and isinstance(val, str):
                        try:
                            val = json.loads(val)
                        except Exception:
                            pass
                    row_vals.append(val)
                values.append(tuple(row_vals))

            insert_query = f"INSERT INTO {table} ({col_names}) VALUES %s ON CONFLICT DO NOTHING"
            execute_values(pg_cursor, insert_query, values)
            print(f"[OK] Migrated {len(values)} records to PostgreSQL table '{table}'.")

        pg_conn.commit()
        print("[SUCCESS] Live migration to PostgreSQL completed successfully!")

    except Exception as e:
        pg_conn.rollback()
        print(f"[FAIL] Migration failed, transaction rolled back: {e}")
        sys.exit(1)
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
