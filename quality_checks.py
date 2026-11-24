"""
quality_checks.py

Checks movies.db after the pipeline runs. Prints a pass/fail line for each check
and exits with an error if any check fails, so the Airflow task (and the DAG run)
turns red instead of quietly keeping bad data.

Run it from the repo folder:
    python quality_checks.py              # after build_database.py (expects today's snapshot)
    python quality_checks.py --no-today   # after backfill_movies.py (no snapshot needed)
"""

import sqlite3
import sys
from datetime import date

DB_PATH = "movies.db"
TODAY = date.today().isoformat()

REQUIRED_TABLES = ["movies", "genres", "movie_genres", "daily_snapshots", "omdb_ratings"]


def run_checks(conn, check_today=True):
    """Return a list of (check name, passed?, detail)."""
    results = []

    def check(name, passed, detail=""):
        results.append((name, bool(passed), detail))

    # 1. every table exists
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    check("all tables exist", not missing, f"missing: {missing}" if missing else "")
    if missing:
        return results   # the rest of the checks need these tables

    # 2. the file itself is not corrupted
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    check("database integrity", integrity == "ok", integrity)

    # 3. every ID points to a row that exists (no broken links between tables)
    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    check("no broken foreign keys", not broken, f"{len(broken)} broken rows" if broken else "")

    # 4. movies table has data and every movie has a title
    n_movies = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    check("movies table not empty", n_movies > 0, f"{n_movies} movies")
    no_title = conn.execute("SELECT COUNT(*) FROM movies WHERE title IS NULL OR title = ''").fetchone()[0]
    check("every movie has a title", no_title == 0, f"{no_title} without a title" if no_title else "")

    # 5. values are in a sensible range
    bad_votes = conn.execute(
        "SELECT COUNT(*) FROM daily_snapshots WHERE vote_average < 0 OR vote_average > 10"
    ).fetchone()[0]
    check("vote_average between 0 and 10", bad_votes == 0, f"{bad_votes} out of range" if bad_votes else "")
    bad_imdb = conn.execute(
        "SELECT COUNT(*) FROM omdb_ratings WHERE imdb_rating < 0 OR imdb_rating > 10"
    ).fetchone()[0]
    check("imdb_rating between 0 and 10", bad_imdb == 0, f"{bad_imdb} out of range" if bad_imdb else "")
    bad_money = conn.execute(
        "SELECT COUNT(*) FROM movies WHERE budget_usd < 0 OR revenue_usd < 0"
    ).fetchone()[0]
    check("no negative budget or revenue", bad_money == 0, f"{bad_money} negative" if bad_money else "")

    # 6. today's snapshot is there for both lists (only after the daily pull)
    if check_today:
        for list_type in ["trending", "now_playing"]:
            n = conn.execute(
                "SELECT COUNT(*) FROM daily_snapshots WHERE snapshot_date = ? AND list_type = ?",
                (TODAY, list_type),
            ).fetchone()[0]
            check(f"today's {list_type} snapshot exists", n > 0, f"{n} rows for {TODAY}")

    # 7. the movies table never shrinks between runs (compares with the last logged run)
    if "pipeline_runs" in tables:
        last = conn.execute(
            "SELECT movies_rows FROM pipeline_runs WHERE status = 'success' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        if last and last[0] is not None:
            check("movies count did not drop", n_movies >= last[0], f"{last[0]} -> {n_movies}")

    return results


def main():
    check_today = "--no-today" not in sys.argv
    conn = sqlite3.connect(DB_PATH)
    results = run_checks(conn, check_today)
    conn.close()

    print("Data quality checks")
    for name, passed, detail in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))

    failed = [name for name, passed, _ in results if not passed]
    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        sys.exit(1)
    print(f"\nAll {len(results)} checks passed.")


if __name__ == "__main__":
    main()
