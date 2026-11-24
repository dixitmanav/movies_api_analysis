# Movie Trends Pipeline

MLDS 400 (Topics in Data Engineering) final project, Northwestern University, Fall 2026.

A pipeline that pulls trending and now-playing movies from **TMDb** every day, adds critic and audience ratings from **OMDb**, and stores the history in a database so we can find out what makes a movie trend.

> Current status: `build_database.py` loads both APIs into a SQLite database every day, and `backfill_movies.py` adds about 5,750 well-known movies from 1980–2025 for historical analysis. The Airflow DAG comes next.

## Data sources

| API | What we use it for | Limits |
| --- | --- | --- |
| [TMDb](https://www.themoviedb.org/) | Trending and now-playing movies, the most-voted movies of each year (for the backfill), movie details (genres, budget, revenue, popularity, IMDb ID) | Free for non-commercial use |
| [OMDb](https://www.omdbapi.com/) | IMDb, Rotten Tomatoes and Metacritic ratings | Free key, 1,000 requests a day |

The two join on the IMDb ID.

*This product uses the TMDB API but is not endorsed or certified by TMDB.*

## Setup

### 1. Get your API keys (free)

- **TMDb:** make an account at [themoviedb.org](https://www.themoviedb.org/), then go to **Settings → API → Request an API key → Developer**. Copy the **API Key** (the 32-character one).
- **OMDb:** go to [omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx), choose **FREE**, and submit the form. The key arrives by email. Click the activation link in that email, or the key won't work.

### 2. Clone the repo

```bash
git clone https://github.com/dixitmanav/movies_api_analysis.git
cd movies_api_analysis
```

### 3. Add your keys

Copy the example file and paste your keys into the copy:

```bash
cp .env.example .env
```

`.env` should look like this (no quotes, no spaces):

```
TMDB_API_KEY=your_tmdb_key
OMDB_API_KEY=your_omdb_key
```

To run the backfill with several OMDb keys (for example, one per teammate), add them on one line, comma-separated, no spaces:

```
OMDB_API_KEYS=key1,key2,key3
```

`build_database.py` still uses `OMDB_API_KEY`, so keep that line too.

`.env` is listed in `.gitignore`, so your keys never get pushed to GitHub.

### 4. Install the packages

```bash
pip install pandas requests python-dotenv jupyter
```

### 5. Build the database

```bash
python build_database.py
```

This creates `movies.db` (SQLite) in the repo folder with five tables:

| Table | One row per | What's in it |
| --- | --- | --- |
| `movies` | movie | title, release date, runtime, budget, revenue, IMDb ID |
| `genres` | genre | genre name |
| `movie_genres` | movie + genre | links movies to their genres |
| `daily_snapshots` | movie + list + day | rank, popularity and votes on that day's trending / now-playing list |
| `omdb_ratings` | movie | IMDb rating and votes, Rotten Tomatoes, Metascore, US box office |

Run it once a day to build up history. Each run adds a new dated snapshot, only looks up movies it hasn't seen before, and doesn't duplicate anything if run twice in one day. `movies.db` is in `.gitignore`, so each user builds their own.

### 6. Backfill historical movies

The daily lists only cover about 160 current movies. To analyze movies across years, run the backfill after `build_database.py` has created `movies.db`:

```bash
python backfill_movies.py
```

For each year from 1980 to 2025, it asks TMDb for the 125 most-voted movies (with at least 100 votes), saves their details, then gets their OMDb ratings. That's up to about 5,750 movies. The settings (`START_YEAR`, `END_YEAR`, `MOVIES_PER_YEAR`, `MIN_VOTES`) are at the top of the script.

- **TMDb part:** about 6,000 calls, no daily limit, roughly half an hour.
- **OMDb part:** one call per movie. Each key allows 1,000 a day. The script uses the keys in `OMDB_API_KEYS` one after another and switches when OMDb says a key is used up.
- **Safe to rerun:** movies already in `movies.db` are skipped, and progress is saved after every year and every 50 OMDb lookups. If it stops or the keys run out, run it again (the next day, for OMDb) and it picks up where it left off.

When it finishes, it prints the movie count and the share of movies with each rating, budget and revenue by decade.

### 7. Look at the raw API data (optional)

```bash
jupyter notebook explore_apis.ipynb
```

Run all cells. The first cell checks that both keys loaded. The rest show today's trending movies, now-playing movies, one movie's full details from each API, and a combined table.

## Known issues

- **Rotten Tomatoes scores:** since 2026-11-23, OMDb no longer returns Rotten Tomatoes scores, even for well-known movies (confirmed on two keys on 2026-11-23 and 2026-11-24, including one that returned them on 2026-11-22; `tomatoes=true` returns `N/A` too). IMDb and Metacritic still come through. Movies looked up earlier keep their scores. For critic vs. audience comparisons, use Metascore vs. IMDb rating.

## Repo layout

```
movies_api_analysis/
├── build_database.py    # pulls both APIs into movies.db
├── backfill_movies.py   # adds well-known movies from 1980-2025 to movies.db
├── explore_apis.ipynb   # first look at both APIs
├── .env.example         # template for your API keys
├── .env                 # your real keys (not committed)
├── movies.db            # created by build_database.py (not committed)
├── .gitignore
└── README.md
```

## Team

- Manav Dixit
- Shivani Kedila
- Ayush Tharval
- Mehwish Ahmed
- Reeja Kurian
