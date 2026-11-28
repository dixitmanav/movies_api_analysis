"""
clean_snapshots.py

Makes a clean version of daily_snapshots called daily_snapshots_clean.
The raw daily_snapshots table is not changed.

Run it after build_database.py:
    python build_database.py
    python clean_snapshots.py
"""

import sqlite3
import pandas as pd

DB_PATH = "movies.db"

# ratings from fewer votes than this are not reliable
LOW_VOTES = 10

CLEAN_SNAPSHOTS = f"""
DROP TABLE IF EXISTS daily_snapshots_clean;

CREATE TABLE daily_snapshots_clean AS
WITH trending_today AS (
    -- every movie that was on the trending list, and on which day,
    -- plus which day of trending that is for the movie (1 = first day we saw it trending)
    SELECT
        snapshot_date,
        tmdb_id,
        ROW_NUMBER() OVER (PARTITION BY tmdb_id ORDER BY snapshot_date) AS trending_day_number
    FROM (SELECT DISTINCT snapshot_date, tmdb_id
          FROM daily_snapshots
          WHERE list_type = 'trending')
)
SELECT
    s.snapshot_date,
    s.list_type,
    s.rank,
    s.tmdb_id,
    m.title,                                   -- movie title from the movies table
    m.release_date,
    s.popularity,

    -- cleaning: 0 votes means the 0.0 rating is fake, so make it blank
    CASE WHEN s.vote_count = 0 THEN NULL ELSE s.vote_average END AS vote_average,
    s.vote_count,

    -- is the rating reliable? a rating from only a few people isn't
    CASE WHEN s.vote_count < {LOW_VOTES} THEN 'no' ELSE 'yes' END AS reliable_vote_average,

    -- was the movie trending that day, and was it out yet that day?
    CASE
        WHEN m.release_date IS NULL THEN 'unknown'
        WHEN t.tmdb_id IS NOT NULL AND m.release_date > s.snapshot_date THEN 'trending_unreleased'
        WHEN t.tmdb_id IS NOT NULL THEN 'trending_released'
        WHEN m.release_date > s.snapshot_date THEN 'not_trending_unreleased'
        ELSE 'not_trending_released'
    END AS trend_status,

    -- like "weeks on chart": how many days the movie has been trending so far
    -- (blank if it wasn't trending that day)
    t.trending_day_number

FROM daily_snapshots s
JOIN movies m ON s.tmdb_id = m.tmdb_id
LEFT JOIN trending_today t
       ON s.tmdb_id = t.tmdb_id AND s.snapshot_date = t.snapshot_date;

-- note: when a movie is on both lists on the same day, its rating and vote count
-- can be slightly different on each list (the lists are pulled at slightly different
-- times and TMDb updates live). We keep both rows as they are.
"""


def run_checks(conn):
    """Quick checks that the cleaning worked (Week 7: validate + uniqueness)."""
    raw = conn.execute("SELECT COUNT(*) FROM daily_snapshots").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM daily_snapshots_clean").fetchone()[0]
    dupes = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT snapshot_date, list_type, tmdb_id, COUNT(*) AS n
            FROM daily_snapshots_clean
            GROUP BY snapshot_date, list_type, tmdb_id
            HAVING n > 1)
    """).fetchone()[0]
    bad_ratings = conn.execute("""
        SELECT COUNT(*) FROM daily_snapshots_clean
        WHERE vote_average < 0 OR vote_average > 10
    """).fetchone()[0]

    print("\nChecks:")
    print(f"  raw rows = {raw}, clean rows = {clean}  ->", "OK" if raw == clean else "PROBLEM")
    print(f"  duplicate rows: {dupes}  ->", "OK" if dupes == 0 else "PROBLEM")
    print(f"  ratings outside 0-10: {bad_ratings}  ->", "OK" if bad_ratings == 0 else "PROBLEM")


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.executescript(CLEAN_SNAPSHOTS)
    conn.commit()
    print("made daily_snapshots_clean")

    run_checks(conn)

    print("\ntrend_status counts:")
    print(pd.read_sql("""
        SELECT trend_status, COUNT(*) AS rows
        FROM daily_snapshots_clean
        GROUP BY trend_status
    """, conn).to_string(index=False))

    unreliable = conn.execute(
        "SELECT COUNT(*) FROM daily_snapshots_clean WHERE reliable_vote_average = 'no'"
    ).fetchone()[0]
    print(f"\nrows with reliable_vote_average = no: {unreliable}")

    print("\nnew movies on the trending list each day (trending_day_number = 1):")
    print(pd.read_sql("""
        SELECT snapshot_date, COUNT(*) AS new_on_trending
        FROM daily_snapshots_clean
        WHERE list_type = 'trending' AND trending_day_number = 1
        GROUP BY snapshot_date
    """, conn).to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()
