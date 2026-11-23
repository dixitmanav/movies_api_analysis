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

CLEAN_SNAPSHOTS = """
DROP TABLE IF EXISTS daily_snapshots_clean;

CREATE TABLE daily_snapshots_clean AS
SELECT
    s.snapshot_date,
    s.list_type,
    s.rank,
    s.tmdb_id,
    m.title,                                   -- movie title from the movies table
    s.popularity,

    -- cleaning: 0 votes means the 0.0 rating is fake, so make it blank
    CASE WHEN s.vote_count = 0 THEN NULL ELSE s.vote_average END AS vote_average,
    s.vote_count,

    -- trending + released / trending + unreleased / not trending
    CASE
        WHEN s.tmdb_id IN (SELECT tmdb_id FROM daily_snapshots t
                           WHERE t.list_type = 'trending' AND t.snapshot_date = s.snapshot_date)
             AND m.release_date > s.snapshot_date THEN 'trending_unreleased'
        WHEN s.tmdb_id IN (SELECT tmdb_id FROM daily_snapshots t
                           WHERE t.list_type = 'trending' AND t.snapshot_date = s.snapshot_date)
             THEN 'trending_released'
        ELSE 'not_trending_released'
    END AS trend_status,

    -- where the movie would rank if the list was sorted by popularity
    RANK() OVER (PARTITION BY s.snapshot_date, s.list_type
                 ORDER BY s.popularity DESC) AS popularity_rank,

    -- trending rank minus popularity rank
    s.rank - RANK() OVER (PARTITION BY s.snapshot_date, s.list_type
                          ORDER BY s.popularity DESC) AS rank_gap

FROM daily_snapshots s
JOIN movies m ON s.tmdb_id = m.tmdb_id;
"""


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.executescript(CLEAN_SNAPSHOTS)
    conn.commit()
    print("made daily_snapshots_clean")

    count = conn.execute("SELECT COUNT(*) FROM daily_snapshots_clean").fetchone()[0]
    print(f"rows: {count}")

    print("\nTrending list (latest day):")
    print(pd.read_sql("""
        SELECT rank, title, popularity_rank, rank_gap, vote_average, trend_status
        FROM daily_snapshots_clean
        WHERE list_type = 'trending'
          AND snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots_clean)
        ORDER BY rank
    """, conn).to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()