# Movie Trends Pipeline

MLDS 400 (Topics in Data Engineering) final project, Northwestern University, Fall 2026.

A pipeline that pulls trending and now-playing movies from **TMDb** every day, adds critic and audience ratings from **OMDb**, and stores the history in a database so we can find out what makes a movie trend.

> Current status: exploring the two APIs. `explore_apis.ipynb` pulls a sample from each one so we can see what the data looks like.

## Data sources

| API | What we use it for | Limits |
| --- | --- | --- |
| [TMDb](https://www.themoviedb.org/) | Trending and now-playing movies, movie details (genres, budget, revenue, popularity, IMDb ID) | Free for non-commercial use |
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
pip install pandas requests python-dotenv jupyter
```

### 5. Look at the data

```bash
jupyter notebook explore_apis.ipynb
```

Run all cells. The first cell checks that both keys loaded. The rest show today's trending movies, now-playing movies, one movie's full details from each API, and a combined table.

## Repo layout

```
movies_api_analysis/
├── explore_apis.ipynb   # first look at both APIs
├── .env.example         # template for your API keys
├── .env                 # your real keys (not committed)
├── .gitignore
└── README.md
```

## Team

- Manav Dixit
- _(add teammates)_
