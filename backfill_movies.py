"""
backfill_movies.py

One-off (but safe to repeat) historical pull that adds a wide range of well-known
movies to movies.db, so the EDA isn't limited to today's trending / now-playing lists.

For each year from START_YEAR to END_YEAR:
  1. TMDb /discover/movie: the top MOVIES_PER_YEAR movies by vote count (at least MIN_VOTES votes)
  2. TMDb /movie/{id}: details (IMDb ID, budget, revenue, runtime, genres) for movies not already saved
Then:
  3. OMDb: IMDb rating/votes, Rotten Tomatoes, Metascore, box office, using one or more keys

Run it from the repo folder, after build_database.py has created movies.db at least once:
    python build_database.py
    python backfill_movies.py

Safe to run every day:
  - movies already in movies.db are skipped (no repeat TMDb or OMDb calls)
  - progress is saved after every year (TMDb) and every 50 movies (OMDb),
    so if a run stops, the next run picks up where it left off
  - OMDb keys are used one after another: when OMDb says a key hit its daily
    limit (or the key is invalid), the next key in OMDB_API_KEYS is used

.env needs TMDB_API_KEY plus either:
    OMDB_API_KEYS=key1,key2,key3     (several keys, comma-separated, no spaces)
    OMDB_API_KEY=key1                (a single key, same as build_database.py)
"""

import os
import sqlite3

import pandas as pd
import requests
from dotenv import load_dotenv

import build_database as bd   # reuse the daily script's API helpers, loaders and table schema


# ---------------------------------------------------------------- settings

load_dotenv()
OMDB_API_KEYS = [
    k.strip()
    for k in (os.getenv("OMDB_API_KEYS") or os.getenv("OMDB_API_KEY") or "").split(",")
    if k.strip()
]

DB_PATH = bd.DB_PATH
START_YEAR = 1980
END_YEAR = 2025
MOVIES_PER_YEAR = 125   # top N per year by vote count; 46 years x 125 = up to 5,750 movies
MIN_VOTES = 100         # skip obscure movies (unlikely to have ratings, budget or box office)


# ---------------------------------------------------------------- TMDb

def discover_year(year, per_year=MOVIES_PER_YEAR, min_votes=MIN_VOTES):
    """TMDb IDs of the top `per_year` movies released in `year`, most-voted first."""
    ids = []
    page = 1
    while len(ids) < per_year:
        data = bd.tmdb_get(
            "/discover/movie",
            primary_release_year=year,
            sort_by="vote_count.desc",
            include_adult=False,
            page=page,
            **{"vote_count.gte": min_votes},   # dotted parameter name, so it's passed via a dict
        )
        ids.extend(m["id"] for m in data["results"])
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return ids[:per_year]


def backfill_tmdb(conn, years, per_year=MOVIES_PER_YEAR, min_votes=MIN_VOTES):
    """Find movies year by year and save details for the ones not already in the database."""
    cursor = conn.cursor()
    bd.load_genres(cursor)   # makes sure the genres table is filled
    for year in years:
        ids = discover_year(year, per_year, min_votes)
        print(f"{year}: {len(ids)} found -> ", end="")
        bd.load_new_movies(cursor, conn, pd.DataFrame({"tmdb_id": ids}))
        conn.commit()        # save each finished year


# ---------------------------------------------------------------- OMDb

def omdb_get_with_key(imdb_id, key):
    """Like bd.omdb_get, but with the key passed in. Returns None if OMDb doesn't have the movie."""
    response = requests.get(bd.OMDB_URL, params={"apikey": key, "i": imdb_id}, timeout=30)
    data = response.json()
    if data.get("Response") == "False":
        error = data.get("Error", "").lower()
        if "limit" in error or "invalid api key" in error:
            raise bd.OmdbLimitReached(data.get("Error"))   # either way: move on to the next key
        return None
    return data


def omdb_todo(conn):
    """IMDb IDs that have never been looked up in OMDb, in random order
    (if we run out of calls, the gaps are spread across all years)."""
    return pd.read_sql(
        """SELECT m.imdb_id
           FROM movies m
           LEFT JOIN omdb_ratings o ON m.imdb_id = o.imdb_id
           WHERE m.imdb_id IS NOT NULL AND o.imdb_id IS NULL
           ORDER BY RANDOM()""",
        conn,
    )["imdb_id"].tolist()


def backfill_omdb(conn, keys, max_calls=None):
    """Look up OMDb ratings, switching to the next key whenever one is used up."""
    todo = omdb_todo(conn)
    if max_calls is not None:
        todo = todo[:max_calls]
    print(f"OMDb: {len(todo)} movies to look up with {len(keys)} key(s)")

    cursor = conn.cursor()
    key_i = 0
    calls = [0] * len(keys)
    done = 0
    for imdb_id in todo:
        o = None
        while key_i < len(keys):
            try:
                o = omdb_get_with_key(imdb_id, keys[key_i]) or {}   # {} = OMDb doesn't have it
                calls[key_i] += 1
                break
            except bd.OmdbLimitReached as e:
                print(f"  key {key_i + 1} stopped after {calls[key_i]} calls ({e}); switching")
                key_i += 1
        if o is None:        # every key is used up for today
            print("  all keys are used up for today")
            break
        bd.save_omdb_row(cursor, imdb_id, o)
        done += 1
        if done % 50 == 0:
            conn.commit()    # save progress in case the run stops
            print(f"  {done} done")
    conn.commit()
    print(f"OMDb: {done} looked up, {len(omdb_todo(conn))} still waiting. Calls per key: {calls}")


# ---------------------------------------------------------------- report

def coverage_report(conn):
    """Movies per decade and the % that have each rating / money column."""
    return pd.read_sql(
        """SELECT (CAST(substr(m.release_date, 1, 4) AS INTEGER) / 10) * 10 AS decade,
                  COUNT(*)                                              AS movies,
                  ROUND(100.0 * AVG(o.imdb_id IS NOT NULL))             AS pct_omdb_checked,
                  ROUND(100.0 * AVG(o.imdb_rating IS NOT NULL))         AS pct_imdb,
                  ROUND(100.0 * AVG(o.rotten_tomatoes_pct IS NOT NULL)) AS pct_rt,
                  ROUND(100.0 * AVG(o.metascore IS NOT NULL))           AS pct_metascore,
                  ROUND(100.0 * AVG(m.budget_usd IS NOT NULL))          AS pct_budget,
                  ROUND(100.0 * AVG(m.revenue_usd IS NOT NULL))         AS pct_revenue
           FROM movies m
           LEFT JOIN omdb_ratings o ON m.imdb_id = o.imdb_id
           GROUP BY decade
           ORDER BY decade""",
        conn,
    )


# ---------------------------------------------------------------- main

def run(start_year=START_YEAR, end_year=END_YEAR, per_year=MOVIES_PER_YEAR,
        min_votes=MIN_VOTES, max_omdb_calls=None):
    """The whole backfill. Arguments make small test runs easy, e.g. run(2000, 2000, per_year=3, max_omdb_calls=3)."""
    if not bd.TMDB_API_KEY:
        raise SystemExit("Missing TMDB_API_KEY. Copy .env.example to .env and paste in your keys.")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(bd.SCHEMA)   # creates any missing tables; existing data is untouched

        backfill_tmdb(conn, range(start_year, end_year + 1), per_year, min_votes)

        if OMDB_API_KEYS:
            backfill_omdb(conn, OMDB_API_KEYS, max_omdb_calls)
        else:
            print("No OMDb keys in .env (OMDB_API_KEYS or OMDB_API_KEY), so skipping ratings.")

        total = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        print(f"\nMovies in {DB_PATH}: {total}")
        print(coverage_report(conn).to_string(index=False))
    finally:
        conn.close()


if __name__ == "__main__":
    run()
