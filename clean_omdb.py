"""
clean_omdb.py

Makes a clean version of omdb_ratings called omdb_ratings_clean.
The raw omdb_ratings table is not changed.

Run it after build_database.py:
    python build_database.py
    python clean_omdb.py
"""

import sqlite3
import pandas as pd

DB_PATH = "movies.db"

CLEAN_OMDB = """
DROP TABLE IF EXISTS omdb_ratings_clean;

CREATE TABLE omdb_ratings_clean AS
SELECT
    o.imdb_id,
    m.title,                                   -- movie title from the movies table
    o.imdb_rating,                             -- audience score, out of 10
    o.imdb_votes,
    o.metascore,                               -- critic score, out of 100

    -- age rating, cleaned: ~20 messy values collapsed into a few groups
    CASE
        WHEN o.rated IS NULL THEN 'Unknown'
        WHEN o.rated IN ('G', 'PG', 'PG-13', 'R', 'NC-17') THEN o.rated
        WHEN o.rated IN ('Not Rated', 'Unrated') THEN 'Not Rated'
        WHEN o.rated LIKE 'TV-%' THEN 'TV'
        ELSE 'Other'                           -- rare ones like X, Passed, 16+, E10+
    END AS rated,

    -- awards text -> simple yes/no columns (the text itself stays in the raw table)
    CASE WHEN o.awards LIKE 'Won %Oscar%' THEN 'yes' ELSE 'no' END AS won_oscar,
    CASE WHEN o.awards LIKE '%Oscar%' THEN 'yes' ELSE 'no' END AS oscar_nominated,  -- won or nominated

    o.box_office_usd,
    o.fetched_on

    -- rotten_tomatoes_pct is dropped: OMDb stopped returning it, almost all blank

FROM omdb_ratings o
LEFT JOIN movies m ON o.imdb_id = m.imdb_id;
"""


def run_checks(conn):
    """Quick checks that the cleaning worked (Week 7: validate + uniqueness)."""
    raw = conn.execute("SELECT COUNT(*) FROM omdb_ratings").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM omdb_ratings_clean").fetchone()[0]
    dupes = conn.execute("""
        SELECT COUNT(*) - COUNT(DISTINCT imdb_id) FROM omdb_ratings_clean
    """).fetchone()[0]

    print("\nChecks:")
    print(f"  raw rows = {raw}, clean rows = {clean}  ->", "OK" if raw == clean else "PROBLEM")
    print(f"  duplicate imdb_ids: {dupes}  ->", "OK" if dupes == 0 else "PROBLEM")


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.executescript(CLEAN_OMDB)
    conn.commit()
    print("made omdb_ratings_clean")

    run_checks(conn)

    print("\nrated counts:")
    print(pd.read_sql("""
        SELECT rated, COUNT(*) AS movies
        FROM omdb_ratings_clean
        GROUP BY rated
        ORDER BY movies DESC
    """, conn).to_string(index=False))

    print("\noscar flags:")
    print(pd.read_sql("""
        SELECT SUM(won_oscar = 'yes') AS won_oscar, SUM(oscar_nominated = 'yes') AS oscar_nominated
        FROM omdb_ratings_clean
    """, conn).to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()