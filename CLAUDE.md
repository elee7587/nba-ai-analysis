# nba-ai-analysis

## Project mission

This is a **content-creation project first, data/ML project second**. The owner is a content creator and data scientist; the goal is to make statistical analysis of basketball *enjoyable* by turning it into dynamic visualizations and short-form content (clips, social posts). The data pipeline, the LLM analysis agents, and the win-probability model all exist to serve that end: they surface genuinely interesting moments and stats from a game so they can be visualized and published — they are not the end product themselves.

When making design decisions, prefer whatever gets closer to "interesting moment → clear visual → shareable clip" over building out more analytical depth for its own sake.

## Architecture overview

Two stages:

1. **Data pipeline** — scrapes NBA.com stats via `nba_api` and persists structured game data to PostgreSQL. Entry points: [bulk_pipeline.py](bulk_pipeline.py) (historical backfill over a date range), [pipeline.py](pipeline.py) (daily single-date run). Collectors in [data/collectors/](data/collectors/) wrap raw `nba_api` endpoints; processors in [data/processors/](data/processors/) transform and store via [data/storage/db.py](data/storage/db.py) / [data/storage/models.py](data/storage/models.py). This layer is functional and actively used.

2. **AI analysis layer** ([analysis/](analysis/)) — two parallel efforts, both mid-build:
   - An **LLM multi-agent pipeline** ([analysis/agent.py](analysis/agent.py)) that reads Postgres data and produces structured JSON findings per game (scoring runs/momentum, team stat outliers, player stat outliers, MVP candidates), reviewed and corrected by a human via [streamlit/app.py](streamlit/app.py), with corrections persisted in ChromaDB ([analysis/vector_store.py](analysis/vector_store.py)) and fed back in on re-runs.
   - A **win-probability ML model** ([analysis/models/](analysis/models/)) — the newest direction, meant to replace manually scanning every play for "significant moments" with a model that scores win probability at each moment and algorithmically flags the interesting ones.

## Directory map

```
bulk_pipeline.py        # entry point: historical backfill (season/date-range/batch args)
pipeline.py              # entry point: daily pipeline for one date
query.py                 # ad-hoc SQL runner against Postgres (currently hardcoded to one query)

config/settings.py       # loads .env, builds DB_CONFIG/DATABASE_URL, nba_api rate-limit constants

data/
  collectors/            # thin wrappers around nba_api endpoints (boxscore, game, play-by-play, season stats, win-prob)
  processors/             # transform collector output into DB rows (game_processor.py, season_stats_processor.py)
  storage/
    db.py                 # SQLAlchemy engine/session, init_db()
    models.py              # ORM models — see Data model below

analysis/
  agent.py                # NBAAnalysisAgent — orchestrates local Ollama calls for the 4 analyst tasks; writer/editor stages stubbed
  queries.py                # SQLAlchemy queries feeding formatted data into the agent
  vector_store.py            # ChromaDB wrapper — game_analyses / corrected_analyses / narratives collections
  prompts/                   # markdown prompt templates (game/quarter/team_stats/player_stats/mvp analyst + writer/editor prompts)
  models/
    feature_engineering.py    # FeatureEngineer — implemented: play-level + momentum features, plus game-context features for a planned XGBoost model
    win_probability.py         # WinProbabilityModel — fully designed (LogisticRegression + StandardScaler + CalibratedClassifierCV) but every method is a docstring-only stub
    train.py, evaluate.py, game_context.py   # empty (0 bytes) — not started
    saved/                      # referenced by MODEL_PATH but doesn't exist yet — no trained model artifacts anywhere in the repo

streamlit/
  app.py                  # entry point (`streamlit run`) — human review/correction UI for agent findings, NOT an end-user dashboard
  components/               # mvp.py, scoring.py, stats.py — empty stubs, UI logic currently lives inline in app.py

output/raw-findings/      # gitignored — JSON dump per analyst run: {agent}_analyst_{game_id}.json
chroma_db/                 # gitignored — persisted ChromaDB vector store
test/                       # lightweight pytest-style smoke tests for collectors/db
```

No `docs/` folder. README.md is a placeholder (title only) — this file is the real reference.

## Data model (PostgreSQL, [data/storage/models.py](data/storage/models.py))

- `games` — game_id, game_date, home_team, away_team, home_score, away_score, season
- `box_scores_players` / `box_scores_teams` — traditional boxscore stats (shooting splits, reb, ast, stl, blk, tov, pf, pts, plus_minus)
- `advanced_boxscore_players` / `advanced_boxscore_teams` — advanced metrics (off/def/net rating, usage%, true shooting%, pace, PIE, possessions)
- `play_by_play` — one row per action: period, clock, home_score, away_score, score_margin, event_type, description, player, team
- `quarter_scores` — per-team per-quarter point totals
- `season_team_stats` / `season_player_stats` — season aggregates with league ranks, cached with `last_updated`
- `game_outcomes` — game_id, home_won (1/0) — the ML label table

This schema is the shared vocabulary for the feature engineering, the LLM queries, and (eventually) the visualization layer.

## AI/LLM layer

All LLM calls run **locally through Ollama** — `qwen2.5:32b` for reasoning/analysis, `qwen2.5:14b` for converting free-form output into strict JSON ([analysis/agent.py](analysis/agent.py) `_call_with_reasoning()`). **No cloud LLM APIs (OpenAI, Anthropic) are used anywhere in this repo.**

Four analyst agents run per game — scoring, team stats, player stats, MVP — each pulling data via [analysis/queries.py](analysis/queries.py) and a prompt template from [analysis/prompts/](analysis/prompts/). Downstream "writer"/"editor" agents that would turn findings into polished narrative prose are stubbed (`pass`) — prompt files exist (`scoring_writer.md`, `stats_writer.md`, `mvp_writer.md`, `editor.md`) but aren't wired up.

**Correction loop**: [streamlit/app.py](streamlit/app.py) lets a reviewer hand-edit both the structured JSON and the narrative text for a game's findings. "Save & Re-run" pushes edits into ChromaDB via `store_correction()`, and `run_analyst()` pulls prior corrections back in as prompt context on the next run — a human-in-the-loop feedback mechanism, not a one-shot pipeline.

## Win probability model (in progress)

[analysis/models/win_probability.py](analysis/models/win_probability.py) is a complete design — every method has a full docstring but no implementation (`pass`). Design decisions already locked in:
- Logistic regression (not a black-box model) chosen for interpretability and reliable calibration
- Pipeline: `StandardScaler → LogisticRegression → CalibratedClassifierCV`, `StratifiedKFold` for CV
- Target: `home_won`, predicted per-play (not just pre-game)
- Key feature: `margin_x_pct` (score margin × time remaining) — the same lead means different things at different points in the game
- Intended output: `get_significant_moments()` / `detect_scoring_runs()` — algorithmically flagged high-WP-shift moments meant to feed the analyst agents (and, per the mission above, the visualization/content layer) instead of scanning all ~500 plays by hand

[analysis/models/feature_engineering.py](analysis/models/feature_engineering.py) (`FeatureEngineer`) is fully implemented and already builds the play-level + momentum feature set this model needs, plus a separate game-context feature track (win streak, rest days, season win%, previous-season bootstrap) intended for a second, not-yet-started XGBoost pre-game model.

**Not yet built**: `train.py`, `evaluate.py`, `game_context.py` are empty files; no training data has been assembled; no model has been trained or saved.

## Known gaps / bugs

- `feature_engineering.py` imports `TeamGameContext` from `data.storage.models` — that class doesn't exist there. Would raise `ImportError` if the module were actually exercised end-to-end.
- Streamlit correction save/re-run only works for the Scoring & Momentum tab. The Statistical Outliers and MVP tabs render editable fields but never persist them.
- Even where corrections exist, `run_team_stats_analyst` / `run_player_stats_analyst` / `run_mvp_analyst` all check `corrections.get("scoring_runs")` instead of their own keys — cross-analyst correction context isn't actually applied.
- `requirements.txt` is stale — missing `streamlit`, `chromadb`, `ollama`, `scikit-learn`, `numpy`, `pyarrow`, `altair`, `json_repair`, and pins outdated versions of what it does list. What's actually installed in `venv` is the source of truth.
- `streamlit/components/{mvp,scoring,stats}.py` are empty — no component extraction from `app.py` has happened.

## Direction / not yet built

**No visualization or content-generation code exists anywhere in this repo today** — zero matplotlib/plotly/altair usage in actual code (altair is installed but unused), and no video/image export tooling (no moviepy, no ffmpeg calls). This is the gap between the current codebase and the stated mission above.

The natural build path once the win-probability model is trained: `get_significant_moments()` / `detect_scoring_runs()` output → dynamic chart of win probability / momentum over the course of a game → short-form video/image export for social content. The existing JSON findings schema (`scoring_runs`, `momentum_shifts`, `team_outliers`, `player_outliers`, `mvp_candidates`) is the other natural input source for what to visualize.

## Tech stack

- **Data**: PostgreSQL via SQLAlchemy, `nba_api` for scraping, `.env` (gitignored) holds Postgres credentials — read via [config/settings.py](config/settings.py)
- **LLM**: Ollama running `qwen2.5:32b` / `qwen2.5:14b` locally, `json_repair` for malformed JSON recovery — no cloud LLM APIs
- **Vector store**: ChromaDB, local/embedded (`./chroma_db`)
- **Review UI**: Streamlit
- **ML**: scikit-learn (logistic regression track); XGBoost referenced in docstrings as a planned second model but not yet a dependency
- **Not yet installed for the content-creation goal**: any charting library actually wired into code, any video/image rendering tooling
