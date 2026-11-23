"""
build_database.py

Pulls today's trending and now-playing movies from TMDb, adds ratings from OMDb,
and saves everything to a SQLite database (movies.db).

Run it from the repo folder:
    python build_database.py

Safe to run every day (or several times a day):
  - each run adds a new dated snapshot of the trending / now-playing lists
  - pulls several pages of each list (20 movies per page), not just the first
  - TMDb details are only looked up for movies not already in the database
  - OMDb is capped at OMDB_DAILY_BUDGET calls per day, counted across all runs that day
  - leftover OMDb calls are used to refresh old ratings (e.g. new releases that
    had no Rotten Tomatoes score yet when we first looked them up)
  - running twice on the same day does not create duplicates
"""

import os
import sqlite3
from datetime import date, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv


# ---------------------------------------------------------------- settings

load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

DB_PATH = "movies.db"
TMDB_URL = "https://api.themoviedb.org/3"
OMDB_URL = "https://www.omdbapi.com/"
TODAY = date.today().isoformat()

MAX_PAGES = 5               # pages per TMDb list; 20 movies per page, so top 100
OMDB_DAILY_BUDGET = 1000    # OMDb free key allows 1,000 a day
REFRESH_AFTER_DAYS = 7      # re-check a movie's OMDb ratings once they're this many days old


# ---------------------------------------------------------------- tables

SCHEMA = """
CREATE TABLE IF NOT EXISTS genres (
    genre_id INTEGER PRIMARY KEY,
    name     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS movies (
    tmdb_id           INTEGER PRIMARY KEY,
    imdb_id           TEXT UNIQUE,
    title             TEXT NOT NULL,
    release_date      DATE,
    runtime_min       INTEGER,
    budget_usd        INTEGER,      -- NULL when TMDb doesn't know it
    revenue_usd       INTEGER,      -- NULL when TMDb doesn't know it
    original_language TEXT,
    added_on          DATE          -- the day this movie first showed up
);

CREATE TABLE IF NOT EXISTS movie_genres (
    tmdb_id  INTEGER REFERENCES movies (tmdb_id),
    genre_id INTEGER REFERENCES genres (genre_id),
    PRIMARY KEY (tmdb_id, genre_id)
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    snapshot_date DATE,
    list_type     TEXT,             -- 'trending' or 'now_playing'
    rank          INTEGER,          -- position in that list, 1 = top
    tmdb_id       INTEGER REFERENCES movies (tmdb_id),
    popularity    REAL,
    vote_average  REAL,
    vote_count    INTEGER,
    PRIMARY KEY (snapshot_date, list_type, tmdb_id)
);

CREATE TABLE IF NOT EXISTS omdb_ratings (
    imdb_id             TEXT PRIMARY KEY REFERENCES movies (imdb_id),
    imdb_rating         REAL,
    imdb_votes          INTEGER,
    rotten_tomatoes_pct INTEGER,    -- Tomatometer: % of critics with a positive review
    metascore           INTEGER,
    box_office_usd      INTEGER,    -- US gross
    rated               TEXT,       -- PG-13, R, ...
    awards              TEXT,
    fetched_on          DATE        -- last day we asked OMDb about this movie
);
"""


# ---------------------------------------------------------------- API calls

def tmdb_get(path, **params):
    """GET a TMDb endpoint and return the JSON."""
    response = requests.get(TMDB_URL + path, params={"api_key": TMDB_API_KEY, **params}, timeout=30)
    response.raise_for_status()   # stops with a clear error if the key is wrong
    return response.json()


class OmdbLimitReached(Exception):
    """OMDb refused the call because this key used up its daily requests."""


def omdb_get(imdb_id):
    """GET one movie from OMDb. Returns None if OMDb doesn't have it."""
    response = requests.get(OMDB_URL, params={"apikey": OMDB_API_KEY, "i": imdb_id}, timeout=30)
    data = response.json()
    if data.get("Response") == "False":
        error = data.get("Error", "").lower()
        if "limit" in error:
            raise OmdbLimitReached("OMDb daily limit reached. Run again tomorrow.")
        if "invalid api key" in error:
            raise RuntimeError("OMDb says the API key is invalid. Check OMDB_API_KEY in .env.")
        return None
    return data


# ---------------------------------------------------------------- cleaning helpers

def to_number(text, kind=float):
    """Turn OMDb text like '544,815', '$625,595,435', '93%' or 'N/A' into a number (or None)."""
    if text is None or text == "N/A":
        return None
    cleaned = text.replace(",", "").replace("$", "").replace("%", "").split("/")[0]
    try:
        return kind(cleaned)
    except ValueError:
        return None


def blank_to_none(value):
    """TMDb uses 0 or '' for unknown values. Store those as NULL instead."""
    return None if value in (0, "", None) else value


# ---------------------------------------------------------------- main steps

def load_genres(cursor):
    genres = tmdb_get("/genre/movie/list")["genres"]
    cursor.executemany(
        "INSERT OR IGNORE INTO genres (genre_id, name) VALUES (?, ?)",
        [(g["id"], g["name"]) for g in genres],
    )
    print(f"genres: {len(genres)} from TMDb")


def get_list(path, **params):
    """Get up to MAX_PAGES pages of a TMDb list (20 movies per page), in rank order."""
    results = []
    for page in range(1, MAX_PAGES + 1):
        data = tmdb_get(path, page=page, **params)
        results.extend(data["results"])
        if page >= data.get("total_pages", 1):
            break
    return results


def get_todays_lists():
    """Today's trending and now-playing lists, one row per movie per list."""
    lists = {
        "trending": get_list("/trending/movie/day"),
        "now_playing": get_list("/movie/now_playing", region="US"),
    }
    rows = []
    for list_type, movies in lists.items():
        for rank, movie in enumerate(movies, start=1):
            rows.append({
                "snapshot_date": TODAY,
                "list_type": list_type,
                "rank": rank,
                "tmdb_id": movie["id"],
                "popularity": movie.get("popularity"),
                "vote_average": movie.get("vote_average"),
                "vote_count": movie.get("vote_count"),
            })
    snapshots = pd.DataFrame(rows)
    # A movie can show up on two pages if the list shifts while we page through it.
    snapshots = snapshots.drop_duplicates(subset=["list_type", "tmdb_id"], keep="first")
    print(f"snapshots: {len(snapshots)} rows ({snapshots['tmdb_id'].nunique()} unique movies) for {TODAY}")
    return snapshots


def load_new_movies(cursor, conn, snapshots):
    """Look up details only for movies not already in the movies table."""
    existing = set(pd.read_sql("SELECT tmdb_id FROM movies", conn)["tmdb_id"])
    new_ids = [i for i in snapshots["tmdb_id"].unique() if i not in existing]
    print(f"movies: {len(new_ids)} new, {len(existing)} already in the database")

    for tmdb_id in new_ids:
        d = tmdb_get(f"/movie/{tmdb_id}")
        cursor.execute(
            """INSERT OR IGNORE INTO movies
               (tmdb_id, imdb_id, title, release_date, runtime_min, budget_usd, revenue_usd, original_language, added_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d["id"],
                blank_to_none(d.get("imdb_id")),
                d["title"],
                blank_to_none(d.get("release_date")),
                blank_to_none(d.get("runtime")),
                blank_to_none(d.get("budget")),
                blank_to_none(d.get("revenue")),
                d.get("original_language"),
                TODAY,
            ),
        )
        cursor.executemany(
            "INSERT OR IGNORE INTO movie_genres (tmdb_id, genre_id) VALUES (?, ?)",
            [(d["id"], g["id"]) for g in d.get("genres", [])],
        )


def load_snapshots(cursor, snapshots):
    cursor.executemany(
        """INSERT OR IGNORE INTO daily_snapshots
           (snapshot_date, list_type, rank, tmdb_id, popularity, vote_average, vote_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        snapshots[["snapshot_date", "list_type", "rank", "tmdb_id", "popularity", "vote_average", "vote_count"]]
        .itertuples(index=False, name=None),
    )


def omdb_calls_used_today(conn):
    """Every OMDb call sets fetched_on = today on one row, so this counts today's calls across runs."""
    return conn.execute("SELECT COUNT(*) FROM omdb_ratings WHERE fetched_on = ?", (TODAY,)).fetchone()[0]


def omdb_todo(conn):
    """
    Movies to ask OMDb about, most important first:
      1. new movies that have never been looked up (best rank today first)
      2. old lookups worth refreshing: still missing a score, or still on today's lists
         (ratings and vote counts keep changing), oldest lookup first
    """
    refresh_cutoff = (date.fromisoformat(TODAY) - timedelta(days=REFRESH_AFTER_DAYS)).isoformat()
    return pd.read_sql(
        """
        WITH best_rank AS (
            SELECT tmdb_id, MIN(rank) AS best_rank
            FROM daily_snapshots
            WHERE snapshot_date = :today
            GROUP BY tmdb_id
        )
        SELECT m.imdb_id,
               CASE WHEN o.imdb_id IS NULL THEN 'new' ELSE 'refresh' END AS reason
        FROM movies m
        LEFT JOIN omdb_ratings o ON m.imdb_id = o.imdb_id
        LEFT JOIN best_rank b    ON m.tmdb_id = b.tmdb_id
        WHERE m.imdb_id IS NOT NULL
          AND (
                o.imdb_id IS NULL
             OR (o.fetched_on <= :cutoff
                 AND (o.imdb_rating IS NULL
                      OR o.rotten_tomatoes_pct IS NULL
                      OR b.tmdb_id IS NOT NULL))
          )
        ORDER BY
            CASE WHEN o.imdb_id IS NULL THEN 0 ELSE 1 END,   -- new movies first
            COALESCE(b.best_rank, 9999),                     -- then by today's rank
            o.fetched_on                                     -- then oldest lookups
        """,
        conn,
        params={"today": TODAY, "cutoff": refresh_cutoff},
    )


def save_omdb_row(cursor, imdb_id, o):
    """
    Insert or update one movie's ratings.
    COALESCE keeps an old value when OMDb now returns nothing for it,
    so a refresh can fill in blanks but never erase data we already had.
    """
    ratings = {r["Source"]: r["Value"] for r in o.get("Ratings", [])}
    cursor.execute(
        """INSERT INTO omdb_ratings
           (imdb_id, imdb_rating, imdb_votes, rotten_tomatoes_pct, metascore, box_office_usd, rated, awards, fetched_on)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (imdb_id) DO UPDATE SET
               imdb_rating         = COALESCE(excluded.imdb_rating,         omdb_ratings.imdb_rating),
               imdb_votes          = COALESCE(excluded.imdb_votes,          omdb_ratings.imdb_votes),
               rotten_tomatoes_pct = COALESCE(excluded.rotten_tomatoes_pct, omdb_ratings.rotten_tomatoes_pct),
               metascore           = COALESCE(excluded.metascore,           omdb_ratings.metascore),
               box_office_usd      = COALESCE(excluded.box_office_usd,      omdb_ratings.box_office_usd),
               rated               = COALESCE(excluded.rated,               omdb_ratings.rated),
               awards              = COALESCE(excluded.awards,              omdb_ratings.awards),
               fetched_on          = excluded.fetched_on""",
        (
            imdb_id,
            to_number(o.get("imdbRating")),
            to_number(o.get("imdbVotes"), int),
            to_number(ratings.get("Rotten Tomatoes"), int),
            to_number(o.get("Metascore"), int),
            to_number(o.get("BoxOffice"), int),
            None if o.get("Rated") in (None, "N/A") else o.get("Rated"),
            None if o.get("Awards") in (None, "N/A") else o.get("Awards"),
            TODAY,
        ),
    )


def load_omdb_ratings(cursor, conn):
    """Use up to OMDB_DAILY_BUDGET OMDb calls today: new movies first, then refreshes."""
    used = omdb_calls_used_today(conn)
    remaining = max(OMDB_DAILY_BUDGET - used, 0)
    todo = omdb_todo(conn)
    batch = todo.head(remaining)

    n_new = (todo["reason"] == "new").sum()
    n_refresh = (todo["reason"] == "refresh").sum()
    print(f"omdb_ratings: {used} calls already used today, {remaining} left of {OMDB_DAILY_BUDGET}")
    print(f"omdb_ratings: {n_new} new + {n_refresh} to refresh waiting, doing {len(batch)} now")

    done = 0
    try:
        for imdb_id in batch["imdb_id"]:
            o = omdb_get(imdb_id) or {}   # {} = OMDb doesn't have it; we still save a row so we don't ask again today
            save_omdb_row(cursor, imdb_id, o)
            done += 1
            if done % 50 == 0:
                conn.commit()             # save progress in case something stops the run
    except OmdbLimitReached as e:
        print(f"omdb_ratings: stopped after {done} calls. {e}")
    conn.commit()

    left_over = len(todo) - done
    if left_over:
        print(f"omdb_ratings: {left_over} left for tomorrow")


def print_summary(conn):
    print("\nRows per table:")
    for table in ["genres", "movies", "movie_genres", "daily_snapshots", "omdb_ratings"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<16}{count:>6}")
    print(f"\nOMDb calls used today: {omdb_calls_used_today(conn)} of {OMDB_DAILY_BUDGET}")

    print("\nToday's top 5 trending:")
    print(pd.read_sql(
        """SELECT s.rank, m.title, s.popularity, o.imdb_rating, o.rotten_tomatoes_pct
           FROM daily_snapshots s
           JOIN movies m ON s.tmdb_id = m.tmdb_id
           LEFT JOIN omdb_ratings o ON m.imdb_id = o.imdb_id
           WHERE s.snapshot_date = ? AND s.list_type = 'trending'
           ORDER BY s.rank
           LIMIT 5""",
        conn, params=(TODAY,),
    ).to_string(index=False))


def main():
    if not TMDB_API_KEY or not OMDB_API_KEY:
        raise SystemExit("Missing API keys. Copy .env.example to .env and paste in both keys.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.executescript(SCHEMA)

    load_genres(cursor)
    snapshots = get_todays_lists()
    load_new_movies(cursor, conn, snapshots)   # movies must exist before snapshots point to them
    load_snapshots(cursor, snapshots)
    conn.commit()

    load_omdb_ratings(cursor, conn)

    print_summary(conn)
    conn.close()
    print(f"\nSaved to {DB_PATH}")


if __name__ == "__main__":
    main()
