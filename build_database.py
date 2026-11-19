"""
build_database.py

Pulls today's trending and now-playing movies from TMDb, adds ratings from OMDb,
and saves everything to a SQLite database (movies.db).

Run it from the repo folder:
    python build_database.py

Safe to run every day:
  - each run adds a new dated snapshot of the trending / now-playing lists
  - movies already in the database are not looked up again (saves API calls)
  - running twice on the same day does not create duplicates
"""

import os
import sqlite3
from datetime import date

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
    rotten_tomatoes_pct INTEGER,
    metascore           INTEGER,
    box_office_usd      INTEGER,    -- US gross
    rated               TEXT,       -- PG-13, R, ...
    awards              TEXT,
    fetched_on          DATE
);
"""


# ---------------------------------------------------------------- API calls

def tmdb_get(path, **params):
    """GET a TMDb endpoint and return the JSON."""
    response = requests.get(TMDB_URL + path, params={"api_key": TMDB_API_KEY, **params}, timeout=30)
    response.raise_for_status()   # stops with a clear error if the key is wrong
    return response.json()


def omdb_get(imdb_id):
    """GET one movie from OMDb. Returns None if OMDb doesn't have it."""
    response = requests.get(OMDB_URL, params={"apikey": OMDB_API_KEY, "i": imdb_id}, timeout=30)
    data = response.json()
    if data.get("Response") == "False":
        if "limit" in data.get("Error", "").lower():
            raise RuntimeError("OMDb daily limit reached (1,000 calls). Run again tomorrow.")
        if "invalid api key" in data.get("Error", "").lower():
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


def get_todays_lists():
    """Today's trending and now-playing lists, one row per movie per list."""
    lists = {
        "trending": tmdb_get("/trending/movie/day")["results"],
        "now_playing": tmdb_get("/movie/now_playing", region="US")["results"],
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


def load_omdb_ratings(cursor, conn):
    """Get OMDb ratings for every movie that has an IMDb ID but no ratings row yet."""
    todo = pd.read_sql(
        """SELECT imdb_id FROM movies
           WHERE imdb_id IS NOT NULL
             AND imdb_id NOT IN (SELECT imdb_id FROM omdb_ratings)""",
        conn,
    )["imdb_id"]
    print(f"omdb_ratings: looking up {len(todo)} movies")

    for imdb_id in todo:
        o = omdb_get(imdb_id) or {}   # {} = OMDb doesn't have it; we still save a row so we don't ask again
        ratings = {r["Source"]: r["Value"] for r in o.get("Ratings", [])}
        cursor.execute(
            """INSERT OR IGNORE INTO omdb_ratings
               (imdb_id, imdb_rating, imdb_votes, rotten_tomatoes_pct, metascore, box_office_usd, rated, awards, fetched_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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


def print_summary(conn):
    print("\nRows per table:")
    for table in ["genres", "movies", "movie_genres", "daily_snapshots", "omdb_ratings"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<16}{count:>6}")

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
    conn.commit()

    print_summary(conn)
    conn.close()
    print(f"\nSaved to {DB_PATH}")


if __name__ == "__main__":
    main()
