# nba-ai-analysis

Turning NBA box scores and play-by-play data into statistical analysis people actually want to watch — dynamic visualizations and short-form content, not spreadsheets.

For the full architecture, data model, current build status, and known gaps, see [CLAUDE.md](CLAUDE.md).

## What's here

- **Data pipeline** — scrapes `nba_api` into PostgreSQL: games, box scores, advanced stats, play-by-play, season stats
- **AI analysis layer** — local-LLM (Ollama) agents that surface scoring runs, momentum shifts, statistical outliers, and MVP candidates per game, refined through a human-correction loop
- **Win-probability model** *(in progress)* — a per-play win-probability model meant to algorithmically flag the moments worth turning into content
- **Content/visualization layer** *(not yet built)* — the actual goal: dynamic charts and short-form clips built from the above

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Copy your Postgres credentials into a `.env` file (see `config/settings.py` for the expected variables: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).

LLM analysis requires [Ollama](https://ollama.com) running locally with `qwen2.5:32b` and `qwen2.5:14b` pulled.

## Running it

```bash
python pipeline.py [YYYY-MM-DD]        # collect one day's games (defaults to today)
python bulk_pipeline.py <season> <start_date> <end_date>   # backfill a date range
streamlit run streamlit/app.py         # review/correct AI-generated findings
```
