# Movie Trends Pipeline

MLDS 400 (Topics in Data Engineering) final project, Northwestern University, Fall 2026.

A pipeline that pulls trending and now-playing movies from **TMDb** every day, adds critic and audience ratings from **OMDb**, and stores the history in a database so we can find out what makes a movie trend.

> Current status: `build_database.py` loads both APIs into a SQLite database: today's trending and now-playing lists plus about 5,750 well-known movies from 1980–2025. Airflow runs it, checks the data and logs every run.

## Data sources

| API | What we use it for | Limits |
| --- | --- | --- |
| [TMDb](https://www.themoviedb.org/) | Trending and now-playing movies, the most-voted movies of each year (1980–2025), movie details (genres, budget, revenue, popularity, IMDb ID) | Free for non-commercial use |
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

`.env` is listed in `.gitignore`, so your keys never get pushed to GitHub.

### 4. Install the packages

```bash
pip install -r requirements.txt jupyter
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

Each run does four things:

1. **Today's lists:** the top 100 trending and top 100 now-playing movies go into `daily_snapshots`.
2. **History:** the 125 most-voted movies of each year from 1980 to 2025 (at least 100 votes), about 5,750 movies. The settings (`START_YEAR`, `END_YEAR`, `MOVIES_PER_YEAR`, `MIN_VOTES`) are at the top of the script.
3. **Movie details** from TMDb for any movie not saved yet.
4. **OMDb ratings,** up to 1,000 calls a day (the free limit): today's list movies first, then the rest in random order so gaps are spread across all years. Leftover calls refresh old ratings.

Then run `clean_snapshots.py` to rebuild the `daily_snapshots_clean` table:

```bash
python clean_snapshots.py
```

Run both once a day. Each run only looks up movies it hasn't seen before, saves progress as it goes, and doesn't duplicate anything if run twice in one day. `movies.db` is in `.gitignore`, so each user builds their own. For a quick run that skips the history step, use `python build_database.py --skip-history`.

### 6. How long it takes to fill the database

With one TMDb key and one OMDb key:

| Run | What happens | Time |
| --- | --- | --- |
| Day 1 | Saves today's lists and all ~5,900 movies from TMDb (no daily limit), then rates ~1,000 on OMDb | ~30 min |
| Days 2–6 | Today's lists, a quick check for new movies, ~1,000 more OMDb ratings | ~5 min |

After about 6 daily runs, every movie has been checked on OMDb. Two things won't match our database exactly: trending and now-playing lists can only be pulled for the day you run the script, so your snapshots start on your first run, and counts drift a little because TMDb votes and IMDb ratings keep changing.

## Known issues

- **Rotten Tomatoes scores:** since 2026-11-23, OMDb no longer returns Rotten Tomatoes scores, even for well-known movies (confirmed on two keys on 2026-11-23 and 2026-11-24, including one that returned them on 2026-11-22; `tomatoes=true` returns `N/A` too). IMDb and Metacritic still come through. Movies looked up earlier keep their scores. For critic vs. audience comparisons, use Metascore vs. IMDb rating.

## Repo layout

```
movies_api_analysis/
├── build_database.py    # pulls both APIs into movies.db (today's lists + 1980-2025 history)
├── clean_snapshots.py   # builds daily_snapshots_clean from daily_snapshots
├── quality_checks.py    # data checks, run after build_database.py
├── log_run.py           # logs each run to the pipeline_runs table
├── eda.ipynb            # exploratory analysis
├── airflow/             # Dockerfile, requirements and the DAG
├── docker-compose.yml   # runs Airflow (see below)
├── requirements.txt     # pinned Python packages
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

## Run the pipeline with Airflow

Airflow runs the same scripts in order, checks the data, and logs every run. The DAG runs **only when you trigger it**, so nothing calls the APIs unless you click the button. You can still run the scripts by hand like before.

| DAG | What it does |
|---|---|
| `movies_pipeline` | check_keys → build_database → clean_snapshots → quality_checks → log_run |

**Setup (once):** install Docker Desktop and make sure your `.env` has your keys (see `.env.example`).

```bash
docker compose up --build      # first time takes a few minutes
```

Open http://localhost:8080 (user `admin`, password `admin`), click `movies_pipeline`, and press the ▶ (Trigger) button. Stop Airflow with `docker compose down`.

Wait for a run to finish before triggering another, and don't run the scripts by hand while it's running. SQLite only allows one writer at a time. The first run takes about 30 minutes (see step 6).

**What each step does**
- `check_keys` fails right away if an API key is missing from `.env`.
- `quality_checks.py` checks the tables exist, nothing is corrupted, IDs link up, ratings are between 0 and 10, today's snapshot exists, and the movie count never drops. Any failure turns the run red.
- `log_run.py` writes one row per run to the `pipeline_runs` table (start and end time, duration, row counts, what was added, which tasks failed). It runs even when an earlier step fails.

```sql
SELECT dag_id, status, duration_sec, new_movies, new_snapshots, new_omdb_ratings
FROM pipeline_runs ORDER BY finished_at DESC;
```

To run the daily pull automatically, set `SCHEDULE = "0 9 * * *"` in `airflow/dags/movies_pipeline.py`.
