"""
clean_movie_genre.py

Cleans the movies, genres and movie_genres tables.

Run it after build_database.py and clean_snapshots.py (run it again after each new build,
since new movies arrive without titles in movie_genres):
    python build_database.py
    python clean_snapshots.py
    python clean_movie_genre.py
"""

import sqlite3
import pandas as pd

DB_PATH = "movies.db"

def add_column(conn, table, column, col_type):

    """Add a column to a table, but only if it doesn't already exist.

    SQLite raises an error if you try to add a column that is already
    there. Checking first means the script can be run again and again
    (for example every day after build_database.py) without crashing.

    Args:
        conn:     open sqlite3 connection to movies.db
        table:    table to change, e.g. "genres"
        column:   name of the new column, e.g. "movie_count"
        col_type: SQLite type, e.g. "TEXT" or "INTEGER"
    """

    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def clean_movie_genres(conn):
    """Delete rows in movie_genres that point to a missing movie or genre (or have a NULL id).
    
    A row is broken, and gets deleted, if any of these is true:
      - its tmdb_id is not in the movies table (the movie doesn't exist)
      - its genre_id is not in the genres table (the genre doesn't exist)
      - its tmdb_id or genre_id is empty (NULL)

    Args:
        conn: open sqlite3 connection to movies.db
    """

    before = conn.execute("SELECT COUNT(*) FROM movie_genres").fetchone()[0]
    conn.execute("""
        DELETE FROM movie_genres
        WHERE tmdb_id  NOT IN (SELECT tmdb_id  FROM movies)
           OR genre_id NOT IN (SELECT genre_id FROM genres)
           OR tmdb_id IS NULL
           OR genre_id IS NULL
    """)
    after = conn.execute("SELECT COUNT(*) FROM movie_genres").fetchone()[0]
    print(f"movie_genres: removed {before - after} broken rows ({after} left)")


def fill_movie_genres(conn):

    """Add movie names as title and genre names to movie_genres table."""

    add_column(conn, "movie_genres", "title", "TEXT")
    add_column(conn, "movie_genres", "genre_name", "TEXT")
    conn.execute("""
        UPDATE movie_genres
        SET title      = (SELECT m.title FROM movies m WHERE m.tmdb_id = movie_genres.tmdb_id),
            genre_name = (SELECT g.name  FROM genres g WHERE g.genre_id = movie_genres.genre_id)
    """)


def fill_movies(conn):
    
    """Add the genres of each movie to movies table.
    
    This will help to look at the movies and know all the genre it beloings to.
      """
    
    add_column(conn, "movies", "genres", "TEXT")
    conn.execute("""
        UPDATE movies
        SET genres = (
            SELECT GROUP_CONCAT(genre_name, ', ')
            FROM (SELECT genre_name FROM movie_genres
                  WHERE movie_genres.tmdb_id = movies.tmdb_id
                  ORDER BY genre_name)
        )
    """)

def fill_genres(conn):

    """Movie counts and trending counts for each genre.
    
    Movie counts is added as movie_countso that its easy to understand how many mvoies fall under each genre.
    Trending movie counts is added as trending_movie_count so that the numbe rof trending movie under 
     a genre can be calculated. 
     """
    
    add_column(conn, "genres", "movie_count", "INTEGER")
    add_column(conn, "genres", "trending_movie_count", "INTEGER")

    conn.execute("""
        UPDATE genres
        SET movie_count = (
                SELECT COUNT(*) FROM movie_genres mg
                WHERE mg.genre_id = genres.genre_id),

            -- trending data comes from daily_snapshots_clean (made by clean_snapshots.py)
            trending_movie_count = (
                SELECT COUNT(DISTINCT mg.tmdb_id)
                FROM movie_genres mg
                JOIN daily_snapshots_clean s ON s.tmdb_id = mg.tmdb_id
                WHERE mg.genre_id = genres.genre_id
                  AND s.trend_status IN ('trending_released', 'trending_unreleased'))
    """)


def main():
    conn = sqlite3.connect(DB_PATH)

    # fill_genres() reads daily_snapshots_clean, which clean_snapshots.py creates.
    # Stop early with if it's missing (sqlite_master lists all tables).
    has_clean = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'daily_snapshots_clean'"
    ).fetchone()
    if not has_clean:
        raise SystemExit("daily_snapshots_clean not found. Run clean_snapshots.py first.")

    clean_movie_genres(conn)   # Delete broken rows 
    fill_movie_genres(conn)    # Fill title and genre_name to move_genre
    fill_movies(conn)          # Add each movie's genres to movies
    fill_genres(conn)          # Add movie_count and trending_movie_count to genre
    conn.commit()

    # CHECK: first 5 rows of movie_genres with the new columns
    print("\nSample of movie_genres:")
    print(pd.read_sql(
        "SELECT tmdb_id, genre_id, title, genre_name FROM movie_genres LIMIT 5", conn
    ).to_string(index=False))

    # CHECK: first 5 movies with their genres text
    print("\nSample of movies:")
    print(pd.read_sql("SELECT tmdb_id, title, genres FROM movies LIMIT 5", conn).to_string(index=False))


    print("\nGenres ranked by trending movies:")
    print(pd.read_sql("""
        SELECT name, movie_count, trending_movie_count
        FROM genres
        WHERE movie_count > 0
        ORDER BY trending_movie_count DESC, movie_count DESC
    """, conn).to_string(index=False))

    conn.close()


# Run main()
if __name__ == "__main__":
    main()