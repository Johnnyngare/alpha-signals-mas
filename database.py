#database.py
"""
Database persistence layer for Alpha Signals MAS.

ARCHITECTURE NOTE:
------------------
This module owns ALL database interactions. No agent or graph
module touches the database directly — they call functions
defined here. This keeps the database schema decoupled from
the agent logic so either can change independently.

The database file lives at data/alpha_signals.db.
It is excluded from git via .gitignore.
"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

DB_PATH: str = "data/alpha_signals.db"
SCHEMA_VERSION: str = "1.0.0"

"""
MIGRATION POLICY (until Alembic is introduced):
------------------------------------------------
When a schema change is required:
1. Increment SCHEMA_VERSION following semver (e.g., 1.0.1)
2. Add the migration SQL as a separate function named migrate_X_Y_Z()
3. Call the migration function inside initialize_database() after the CREATE TABLE blocks.
"""


def _ensure_data_dir() -> None:
    Path("data").mkdir(exist_ok=True)


@contextmanager
def _get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields a database connection and guarantees
    the connection is closed even if an exception occurs mid-operation.
    Uses WAL (Write-Ahead Logging) journal mode for better concurrent
    read performance — critical when the dashboard reads while the pipeline writes.
    """
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("Database transaction rolled back. Error: %s", str(e))
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    """
    Creates all tables if they don't already exist.
    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS.
    """
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT NOT NULL,
                phone             TEXT NOT NULL UNIQUE,
                email             TEXT,
                tier              TEXT NOT NULL DEFAULT 'free',
                token_hash        TEXT NOT NULL UNIQUE,
                active            INTEGER NOT NULL DEFAULT 0,
                subscription_start TEXT,
                subscription_end   TEXT,
                mpesa_ref         TEXT,
                created_at        TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id     INTEGER NOT NULL,
                amount_kes        REAL NOT NULL,
                currency          TEXT NOT NULL DEFAULT 'KES',
                gateway           TEXT NOT NULL,
                gateway_ref       TEXT NOT NULL UNIQUE,
                status            TEXT NOT NULL DEFAULT 'pending',
                created_at        TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (subscriber_id) REFERENCES subscribers(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            TEXT NOT NULL,
                executed_at       TEXT NOT NULL,
                sport_key         TEXT NOT NULL DEFAULT 'soccer_fifa_world_cup',
                data_source       TEXT NOT NULL DEFAULT 'live',
                fixtures_scanned  INTEGER NOT NULL DEFAULT 0,
                records_ingested  INTEGER NOT NULL DEFAULT 0,
                markets_analysed  INTEGER NOT NULL DEFAULT 0,
                anomalies_found   INTEGER NOT NULL DEFAULT 0,
                arb_opportunities INTEGER NOT NULL DEFAULT 0,
                kelly_suggestions INTEGER NOT NULL DEFAULT 0,
                confidence_score  REAL NOT NULL DEFAULT 0.0,
                retry_count       INTEGER NOT NULL DEFAULT 0,
                audit_passed      INTEGER NOT NULL DEFAULT 0,
                broadcast_result  TEXT,
                execution_secs    REAL,
                analysis_mode     TEXT NOT NULL DEFAULT 'value_sheet',
                created_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_anomalies (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            TEXT NOT NULL,
                executed_at       TEXT NOT NULL,
                fixture           TEXT NOT NULL,
                outcome           TEXT NOT NULL,
                bookmaker_high    TEXT NOT NULL,
                odds_high         REAL NOT NULL,
                bookmaker_low     TEXT NOT NULL,
                odds_low          REAL NOT NULL,
                discrepancy_pct   REAL NOT NULL,
                has_kelly         INTEGER NOT NULL DEFAULT 0,
                kelly_fraction    REAL,
                kelly_ev          REAL,
                created_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Performance Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_run_id ON pipeline_runs(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_fixture ON market_anomalies(fixture)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_run_id ON market_anomalies(run_id)")

    logger.info("Database initialized. Path: %s", DB_PATH)
    logger.info("Schema version: %s", SCHEMA_VERSION)


def save_pipeline_run(
    run_id:           str,
    executed_at:      str,
    fixtures_scanned:  int,
    records_ingested:  int,
    markets_analysed:  int,
    anomalies_found:   int,
    arb_opportunities: int,
    kelly_suggestions: int,
    confidence_score:  float,
    retry_count:       int,
    audit_passed:      bool,
    broadcast_result:  str,
    execution_secs:    float,
    analysis_mode:     str,
    data_source:       str = "live",
    sport_key:         str = "soccer_fifa_world_cup",
) -> int:
    """Inserts one row into pipeline_runs and returns its database ID."""
    with _get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO pipeline_runs (
                run_id, executed_at, sport_key, data_source,
                fixtures_scanned, records_ingested, markets_analysed,
                anomalies_found, arb_opportunities, kelly_suggestions,
                confidence_score, retry_count, audit_passed,
                broadcast_result, execution_secs, analysis_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, executed_at, sport_key, data_source,
            fixtures_scanned, records_ingested, markets_analysed,
            anomalies_found, arb_opportunities, kelly_suggestions,
            confidence_score, retry_count, int(audit_passed),
            broadcast_result, execution_secs, analysis_mode,
        ))
        row_id = cursor.lastrowid
        logger.info(
            "Pipeline run saved. run_id=%s db_id=%d anomalies=%d broadcast=%s",
            run_id, row_id, anomalies_found, broadcast_result
        )
        return row_id


def save_market_anomalies(
    run_id:       str,
    executed_at:  str,
    findings:     list[str],
    kelly_map:    dict[str, tuple[float, float]],
) -> int:
    """
    Parses the analyst's findings list and inserts one row per
    ANOMALY finding into market_anomalies safely.
    """
    rows_inserted = 0

    with _get_connection() as conn:
        for finding in findings:
            if not finding.startswith("ANOMALY"):
                continue

            try:
                # Target: "ANOMALY [fixture -- outcome]: BkA=x, BkB=y, Discrepancy=z%"
                bracket_content = finding.split("[")[1].split("]")[0]
                parts           = bracket_content.split(" -- ", 1)
                fixture          = parts[0].strip()
                outcome          = parts[1].strip() if len(parts) > 1 else "Unknown"

                after_bracket    = finding.split("]: ")[1]
                segments         = after_bracket.split(", ")

                bk_high_raw      = segments[0].split("=")
                bk_low_raw       = segments[1].split("=")
                disc_raw         = segments[2].split("=")[1].replace("%", "").split(" ")[0]

                bookmaker_high   = bk_high_raw[0].strip()
                odds_high        = float(bk_high_raw[1].strip())
                bookmaker_low    = bk_low_raw[0].strip()
                odds_low         = float(bk_low_raw[1].strip())
                discrepancy_pct  = float(disc_raw.strip())

                market_key       = f"{fixture} -- {outcome}"
                kelly_data       = kelly_map.get(market_key)
                has_kelly        = 1 if kelly_data else 0
                kelly_fraction   = kelly_data[0] if kelly_data else None
                kelly_ev         = kelly_data[1] if kelly_data else None

                conn.execute("""
                    INSERT INTO market_anomalies (
                        run_id, executed_at, fixture, outcome,
                        bookmaker_high, odds_high,
                        bookmaker_low, odds_low,
                        discrepancy_pct, has_kelly,
                        kelly_fraction, kelly_ev
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id, executed_at, fixture, outcome,
                    bookmaker_high, odds_high,
                    bookmaker_low, odds_low,
                    discrepancy_pct, has_kelly,
                    kelly_fraction, kelly_ev,
                ))
                rows_inserted += 1

            except Exception as e:
                logger.warning(
                    "Failed to parse anomaly finding for DB insert. "
                    "finding='%s' error=%s", finding[:80], str(e)
                )
                continue

    logger.info("Anomalies saved. run_id=%s rows_inserted=%d", run_id, rows_inserted)
    return rows_inserted


def get_recent_runs(limit: int = 10) -> list[dict]:
    """Returns the most recent pipeline runs sorted by pipeline execution time."""
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM pipeline_runs
            ORDER BY executed_at DESC -- Fixed: Synchronized with dashboard.py sorting index
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]


def get_most_flagged_fixtures(limit: int = 10) -> list[dict]:
    """Returns fixtures ranked by how many times they've been flagged."""
    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT
                fixture,
                COUNT(*)          AS times_flagged,
                AVG(discrepancy_pct) AS avg_discrepancy,
                MAX(discrepancy_pct) AS max_discrepancy,
                SUM(has_kelly)    AS kelly_opportunities
            FROM market_anomalies
            GROUP BY fixture
            ORDER BY times_flagged DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]