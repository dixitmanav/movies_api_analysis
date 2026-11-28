"""
clean_movies.py

Builds a cleaned, analysis-ready table called movies_clean (one row per movie) from
movies, omdb_ratings and the genre tables. The raw tables are not changed.

Run it from the repo folder, after build_database.py:
    python build_database.py
    python clean_movies.py

Safe to rerun: movies_clean is rebuilt from scratch every time.

Cleaning decisions (from the data quality pass, Week 7 steps):

  Completeness
    - rotten_tomatoes_pct is dropped: OMDb stopped returning it, so 99% is blank.
    - Missing ratings and money stay blank (no imputation). They're missing for
      less-known and non-English films, so filling them in would invent data.
    - A blank awards field means OMDb lists no awards, so award counts are 0.

  Validity / accuracy (invalid values become blank)
    - budget under $1,000: placeholders like $6 or $150 (real micro-budgets start ~$6,000)
    - revenue under $1,000: placeholders like $7
    - revenue under 0.1% of budget: streaming / TV films whose box office was never tracked

  Consistency
    - US box office more than 1.1x worldwide revenue is impossible, so revenue becomes blank.
    - revenue_is_us_only flags films whose "worldwide" revenue is really the US total
      (US box office is at least 99% of it). Common before 2000. us_share is left blank for them.
    - MPAA ratings are grouped into G, PG, PG-13, R, NC-17 (X was renamed NC-17),
      Not Rated (incl. Unrated) and Other (TV / streaming ratings).

  Flags (rows are kept; the EDA filters on them)
    - in_history: released 1980-2025, the even 125-movies-per-year sample.
      Leaves out 2026 releases and older films that only appeared on the daily lists.
    - is_short: runtime under 40 minutes (the Academy / AFI line for a feature film).

  Outliers are real films (micro-budget hits, notorious flops) and are kept.
  Chart budget, revenue and roi on log scales and use medians instead of means.
"""

import sqlite3

import numpy as np
import pandas as pd

DB_PATH = "movies.db"
TABLE = "movies_clean"

MIN_MONEY_USD = 1_000          # budgets / revenues below this are placeholders
MIN_REVENUE_SHARE = 0.001      # revenue below 0.1% of budget = box office not tracked
MAX_US_OVER_WORLD = 1.1        # US box office above 1.1x worldwide revenue = revenue is wrong
US_ONLY_SHARE = 0.99           # US box office >= 99% of worldwide = revenue is US-only
MIN_FEATURE_MINUTES = 40       # shorter = short film
HISTORY_YEARS = (1980, 2025)   # years covered by the historical sample

RATING_GROUPS = {
    "G": "G", "PG": "PG", "PG-13": "PG-13", "R": "R",
    "NC-17": "NC-17", "X": "NC-17",
    "Not Rated": "Not Rated", "Unrated": "Not Rated",
}   # anything else that isn't blank (TV-MA, TV-14, E10+, Passed, ...) becomes "Other"

LOAD_QUERY = """
SELECT
    m.tmdb_id, m.imdb_id, m.title, m.release_date, m.runtime_min, m.original_language,
    m.budget_usd, m.revenue_usd, o.box_office_usd,
    o.imdb_rating, o.imdb_votes, o.metascore,
    o.rated, o.awards,
    (SELECT GROUP_CONCAT(g.name, ', ')
       FROM movie_genres mg JOIN genres g ON mg.genre_id = g.genre_id
      WHERE mg.tmdb_id = m.tmdb_id) AS genres,
    m.tmdb_id IN (SELECT tmdb_id FROM daily_snapshots) AS on_daily_lists
FROM movies m
LEFT JOIN omdb_ratings o ON m.imdb_id = o.imdb_id
"""


def load_movies(conn):
    """One row per movie: TMDb details + OMDb ratings + genres as one text column."""
    df = pd.read_sql_query(LOAD_QUERY, conn, parse_dates=["release_date"])
    df["year"] = df["release_date"].dt.year.astype("Int64")
    df["decade"] = (df["year"] // 10 * 10).astype("Int64")
    return df


def blank_invalid_money(df):
    """Set impossible budget / revenue values to blank. Returns how many each rule changed."""
    changes = {}

    bad_budget = df["budget_usd"] < MIN_MONEY_USD
    df.loc[bad_budget, "budget_usd"] = np.nan
    changes["budget under $1,000"] = int(bad_budget.sum())

    rules = {
        "revenue under $1,000": df["revenue_usd"] < MIN_MONEY_USD,
        "revenue under 0.1% of budget": df["revenue_usd"] < MIN_REVENUE_SHARE * df["budget_usd"],
        "US box office > 1.1x worldwide revenue": df["box_office_usd"] > MAX_US_OVER_WORLD * df["revenue_usd"],
    }
    already = pd.Series(False, index=df.index)
    for name, bad in rules.items():
        changes[name] = int((bad & ~already).sum())   # count each movie once, under the first rule it breaks
        already |= bad
    df.loc[already, "revenue_usd"] = np.nan
    return changes


def add_flags(df):
    """True / False columns the EDA filters on. No rows are removed."""
    df["in_history"] = df["year"].between(*HISTORY_YEARS).fillna(False).astype(bool)
    df["is_short"] = (df["runtime_min"] < MIN_FEATURE_MINUTES).fillna(False)
    df["revenue_is_us_only"] = (df["box_office_usd"] >= US_ONLY_SHARE * df["revenue_usd"]).fillna(False)
    df["on_daily_lists"] = df["on_daily_lists"].astype(bool)


def add_derived_columns(df):
    """Columns the EDA needs that aren't in the raw tables."""
    df["roi"] = df["revenue_usd"] / df["budget_usd"]   # 2.0 = earned twice its budget

    real_world = df["revenue_usd"].where(~df["revenue_is_us_only"])
    df["us_share"] = df["box_office_usd"] / real_world  # share of worldwide revenue from the US

    df["rating_group"] = df["rated"].map(RATING_GROUPS)
    df.loc[df["rated"].notna() & df["rating_group"].isna(), "rating_group"] = "Other"   # blank stays blank

    # OMDb awards text, e.g. "Won 2 Oscars. 126 wins & 375 nominations total". Blank = no awards.
    awards = df["awards"].fillna("")
    df["oscar_wins"] = awards.str.extract(r"Won (\d+) Oscars?", expand=False).fillna(0).astype(int)
    df["award_wins"] = awards.str.extract(r"(\d+) wins?\b", expand=False).fillna(0).astype(int)
    df["award_nominations"] = awards.str.extract(r"(\d+) nominations?\b", expand=False).fillna(0).astype(int)


def write_table(df, conn):
    """Replace movies_clean with the cleaned rows (dates stored as YYYY-MM-DD text)."""
    columns = [
        "tmdb_id", "imdb_id", "title", "release_date", "year", "decade", "runtime_min",
        "original_language", "genres", "rating_group", "rated",
        "budget_usd", "revenue_usd", "box_office_usd", "roi", "us_share",
        "imdb_rating", "imdb_votes", "metascore",
        "oscar_wins", "award_wins", "award_nominations", "awards",
        "in_history", "is_short", "revenue_is_us_only", "on_daily_lists",
    ]
    out = df[columns].copy()
    out["release_date"] = out["release_date"].dt.strftime("%Y-%m-%d")
    out.to_sql(TABLE, conn, if_exists="replace", index=False)


def print_summary(df, changes):
    print(f"{TABLE}: {len(df)} movies")
    print("\nValues set to blank:")
    for rule, n in changes.items():
        print(f"  {rule:<42}{n:>6}")
    print("\nFlags:")
    for flag in ["in_history", "is_short", "revenue_is_us_only", "on_daily_lists"]:
        print(f"  {flag:<42}{int(df[flag].sum()):>6}")
    sample = df[df["in_history"] & ~df["is_short"]]
    print(f"\nMain EDA sample (in_history, not short): {len(sample)} movies")
    print(f"  with Metascore + IMDb rating:  {int(sample[['metascore', 'imdb_rating']].notna().all(axis=1).sum())}")
    print(f"  with budget + revenue (roi):   {int(sample['roi'].notna().sum())}")
    print(f"  with us_share:                 {int(sample['us_share'].notna().sum())}")


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        df = load_movies(conn)
        changes = blank_invalid_money(df)
        add_flags(df)
        add_derived_columns(df)
        write_table(df, conn)
        print_summary(df, changes)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
