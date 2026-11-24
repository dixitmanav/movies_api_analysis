"""
log_run.py

Records one pipeline run in the pipeline_runs table of movies.db: when it started
and finished, whether it worked, and how many rows each table has afterwards
(plus how many were added since the last run). This is how we measure the
pipeline from start to finish over time.

The Airflow DAGs call log_run() as their last task. You can also run it by hand:
    python log_run.py
"""

import sqlite3
from datetime import datetime, timezone

DB_PATH = "movies.db"

PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id               TEXT PRIMARY KEY,
    dag_id               TEXT,
    status               TEXT,      -- 'success' or 'failed'
    started_at           TEXT,      -- UTC, ISO format
    finished_at          TEXT,
    duration_sec         REAL,
    movies_rows          INTEGER,
    daily_snapshots_rows INTEGER,
    omdb_ratings_rows    INTEGER,
    new_movies           INTEGER,   -- added since the previous run
    new_snapshots        INTEGER,
    new_omdb_ratings     INTEGER,
    failed_tasks         TEXT       -- comma-separated task ids, if any failed
);
"""


def count(conn, table):
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if exists else 0


def log_run(run_id=None, dag_id="manual", started_at=None, status="success",
            failed_tasks="", db_path=DB_PATH):
    """Write one row to pipeline_runs and return it as a dict."""
    finished = datetime.now(timezone.utc)
    started = started_at or finished
    run_id = run_id or f"manual__{finished.isoformat(timespec='seconds')}"

    conn = sqlite3.connect(db_path)
    conn.execute(PIPELINE_RUNS)

    previous = conn.execute(
        """SELECT movies_rows, daily_snapshots_rows, omdb_ratings_rows
           FROM pipeline_runs ORDER BY finished_at DESC LIMIT 1"""
    ).fetchone() or (0, 0, 0)

    movies, snapshots, ratings = count(conn, "movies"), count(conn, "daily_snapshots"), count(conn, "omdb_ratings")
    row = {
        "run_id": run_id,
        "dag_id": dag_id,
        "status": status,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "duration_sec": round((finished - started).total_seconds(), 1),
        "movies_rows": movies,
        "daily_snapshots_rows": snapshots,
        "omdb_ratings_rows": ratings,
        "new_movies": movies - (previous[0] or 0),
        "new_snapshots": snapshots - (previous[1] or 0),
        "new_omdb_ratings": ratings - (previous[2] or 0),
        "failed_tasks": failed_tasks,
    }
    conn.execute(
        f"INSERT OR REPLACE INTO pipeline_runs ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
        list(row.values()),
    )
    conn.commit()
    conn.close()
    return row


if __name__ == "__main__":
    row = log_run()
    for key, value in row.items():
        print(f"{key:<22}{value}")
