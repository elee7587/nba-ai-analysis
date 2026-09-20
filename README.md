# nba-ai-analysis

A story-driven dashboard for NBA games. Instead of a wall of box-score numbers, each game gets a storyline: how it unfolded, where it turned, who drove it, and why it mattered. ML models find the structure and the standout moments, and local LLM agents turn those findings into narrative.

For the full architecture, data model, current build status, and known gaps, see [CLAUDE.md](CLAUDE.md).

## What's here

- **Data pipeline** — scrapes `nba_api` into PostgreSQL: games, box scores, advanced stats, play-by-play, season stats, daily standings snapshots
- **Win-probability model** — a per-play win-probability model (logistic regression, calibrated). Used as an instrument for measuring how much each moment mattered, not to predict winners
- **AI analysis agents** — local-LLM (Ollama) agents that surface scoring runs, momentum shifts, statistical outliers, and MVP candidates per game, refined through a human-correction loop in Streamlit
- **Story-driven dashboard** *(not yet built)* — the goal: a chaptered, interactive Streamlit view of each game, backed by additional ML models (game-chapter segmentation, game-shape archetypes, per-player win probability added) and an agentic writer/editor workflow

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
python analysis/models/train.py        # train and save the win-probability model
streamlit run streamlit/app.py         # review/correct AI-generated findings
```
