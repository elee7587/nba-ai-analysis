# nba-ai-analysis

A story-driven dashboard for NBA games. Instead of a wall of box-score numbers, each game gets a storyline: how it unfolded, where it turned, who drove it, and why it mattered. ML models find the structure and the standout moments, and local LLM agents turn those findings into narrative.

For the full architecture, data model, current build status, and known gaps, see [CLAUDE.md](CLAUDE.md).

## What's here

- **Data pipeline** — scrapes `nba_api` into PostgreSQL: games, box scores, advanced stats, play-by-play, season stats, daily standings snapshots
- **Game chapters** — each game is split into four chapters that summarize the shape of its score-margin curve, with a short label per chapter (e.g. `MEM +11 (26-15)`). Descriptive, not a claim of statistical "momentum shifts" — analysis of 2,619 games found real games are, if anything, *less* streaky than chance (see `analysis/exploration/chapter_eda.py`)
- **Win-probability model** *(currently unavailable)* — code for a per-play win-probability model exists, but the trained model was **removed**: it was trained on features where the running score was zeroed on non-scoring plays, so its output couldn't be trusted. It will be fixed and retrained; it's intended to rank how much each chapter or moment mattered, not to predict winners
- **AI analysis agents** — local-LLM (Ollama) agents that surface scoring runs, momentum shifts, statistical outliers, and MVP candidates per game, refined through a human-correction loop in Streamlit
- **Story-driven dashboard** *(not yet built)* — the goal: a chaptered, interactive Streamlit view of each game, backed by further ML models (why each chapter happened, player and bench impact, game-shape archetypes) and an agentic writer/editor workflow

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
python analysis/exploration/chapter_eda.py   # rerun the chapter analysis (figures land in output/chapter_eda/)
streamlit run streamlit/app.py         # review/correct AI-generated findings
```

Segment games into chapters from Python (creates the `game_chapters` table if needed):

```python
from analysis.models import ChapterSegmenter
seg = ChapterSegmenter()                          # 4 chapters per game by default
chapters = seg.segment_game("0022500002")         # one game
seg.save_chapters("0022500002", chapters)
seg.segment_season(["22025"])                     # a whole season code
```
