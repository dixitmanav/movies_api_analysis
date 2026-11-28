"""
clean_movie_genre.py

Cleans the movies and movie_genres tables.

Run it after build_database.py (run it again after each new build,
since new movies arrive without titles in movie_genres):
    python build_database.py
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


def main():
    conn = sqlite3.connect(DB_PATH)

    clean_movie_genres(conn)  
    fill_movie_genres(conn)   
    fill_movies(conn)         
    conn.commit()

    # Check: first 5 rows of movie_genres with the new columns
    print("\nSample of movie_genres:")
    print(pd.read_sql(
        "SELECT tmdb_id, genre_id, title, genre_name FROM movie_genres LIMIT 5", conn
    ).to_string(index=False))

    # Check: first 5 movies with their genres text
    print("\nSample of movies:")
    print(pd.read_sql("SELECT tmdb_id, title, genres FROM movies LIMIT 5", conn).to_string(index=False))

    conn.close()


# Run main()
if __name__ == "__main__":
    main()