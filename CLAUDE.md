# nba-ai-analysis

## Project mission

The goal is a **story-driven Streamlit dashboard**: for any NBA game, the user gets a complete storyline — how the game unfolded, when and why it turned, who drove it, and what it meant — told through interactive visuals and narrative written by an agentic LLM workflow. It is aimed at someone exploring a game on their own, not at short-form clips (an earlier direction that has been dropped).

The owner is a data scientist and wants this to be a showcase of **interesting ML models plus a real agentic workflow**, not just a wrapper around box scores. The intended division of labor:

- **ML models compute the structure and the facts** — where a game's chapters start and end, what shape the game had, who moved win probability, whose performance was statistically surprising.
- **LLM agents narrate and connect** those computed facts into a storyline. They should be handed ranked, computed findings, not asked to eyeball raw data for what is interesting.
- **The dashboard presents the story** — a chaptered, scrubbable timeline with visuals and narration per chapter.

When making design decisions, prefer whatever makes the storyline more coherent, more grounded in computed numbers, and more explorable. Predicting who wins a game is explicitly **not** a goal — the win-probability model is an *instrument* for measuring how much each moment mattered, not a product.

## Architecture overview

Three stages:

1. **Data pipeline** — scrapes NBA.com stats via `nba_api` and persists structured game data to PostgreSQL. Entry points: [bulk_pipeline.py](bulk_pipeline.py) (historical backfill over a date range), [pipeline.py](pipeline.py) (daily single-date run, which also captures a league standings snapshot). Collectors in [data/collectors/](data/collectors/) wrap raw `nba_api` endpoints; processors in [data/processors/](data/processors/) transform and store via [data/storage/db.py](data/storage/db.py) / [data/storage/models.py](data/storage/models.py). Functional and actively used.

2. **ML layer** ([analysis/models/](analysis/models/)) — models that turn play-by-play and box-score data into story signals. One model exists (win probability); the rest are proposed (see Direction).

3. **Agentic analysis layer** ([analysis/](analysis/)) — local-LLM agents ([analysis/agent.py](analysis/agent.py)) that read Postgres data and produce structured JSON findings per game (scoring runs/momentum, team stat outliers, player stat outliers, MVP candidates). A human reviews and corrects findings via [streamlit/app.py](streamlit/app.py); corrections persist in ChromaDB ([analysis/vector_store.py](analysis/vector_store.py)) and are fed back in on re-runs. Writer/editor stages that would turn findings into a storyline are stubbed.

The end-user dashboard (stage 4) is **not built yet** and is distinct from the current [streamlit/app.py](streamlit/app.py), which is a reviewer/correction tool.

## Directory map

```
bulk_pipeline.py        # entry point: historical backfill (season/date-range/batch args); does NOT capture standings snapshots
pipeline.py              # entry point: daily pipeline for one date (+ standings snapshot)
query.py                 # ad-hoc SQL runner against Postgres (hardcoded to one query)

config/settings.py       # loads .env, builds DB_CONFIG/DATABASE_URL, nba_api rate-limit constants

data/
  collectors/            # thin wrappers around nba_api endpoints (boxscore, game, play-by-play, season stats, standings, win-prob)
  processors/             # transform collector output into DB rows (game_processor, season_stats_processor, standings_processor)
  storage/
    db.py                 # SQLAlchemy engine/session, init_db()
    models.py              # ORM models — see Data model below
  team_colors.py           # per-team primary hex colors (holdover from the visualization work; still useful for dashboard theming)
  team_lookup.py            # team id/abbr lookups via nba_api static data; court/logo asset paths (assets/ dir doesn't exist yet)

analysis/
  agent.py                # NBAAnalysisAgent — orchestrates local Ollama calls for the 4 analyst tasks; writer/editor stages are `pass` stubs
  queries.py                # SQLAlchemy queries feeding formatted data into the agent
  vector_store.py            # ChromaDB wrapper — game_analyses / corrected_analyses / narratives collections
  prompts/                   # markdown prompt templates (analysts + writers + editor); writer/editor prompts are worded for dashboard text, not video narration
  models/
    feature_engineering.py    # FeatureEngineer — play-level + momentum features, plus game-context features for a possible pre-game model
    win_probability.py         # WinProbabilityModel — implemented and trained (LogisticRegression + StandardScaler + CalibratedClassifierCV, StratifiedGroupKFold CV)
    train.py                    # trains on DEFAULT_SEASONS (2024, 2025 regular season + playoffs) and saves to saved/
    chapter_segmentation.py      # ChapterSegmenter — SKELETON: design + docstrings only, every method raises NotImplementedError
    evaluate.py, game_context.py   # empty (0 bytes) — not started
    saved/                       # wp_model_latest.pkl + timestamped copy (both tracked in git on purpose)

streamlit/
  app.py                  # entry point (`streamlit run`) — human review/correction UI for agent findings; NOT the end-user dashboard
  components/               # mvp.py, scoring.py, stats.py — empty stubs

output/raw-findings/      # gitignored — JSON dump per analyst run: {agent}_analyst_{game_id}.json
chroma_db/                 # gitignored — persisted ChromaDB vector store
test/                       # lightweight smoke tests for collectors/db
```

## Data model (PostgreSQL, [data/storage/models.py](data/storage/models.py))

- `games` — game_id, game_date, home_team, away_team, home_score, away_score, season
- `box_scores_players` / `box_scores_teams` — traditional boxscore stats (shooting splits, reb, ast, stl, blk, tov, pf, pts, plus_minus)
- `advanced_boxscore_players` / `advanced_boxscore_teams` — off/def/net rating, usage%, true shooting%, pace, PIE, possessions
- `play_by_play` — one row per action: period, clock, home_score, away_score, score_margin, event_type, description, player, team
- `quarter_scores` — per-team per-quarter point totals
- `season_team_stats` / `season_player_stats` — season aggregates with league ranks, cached with `last_updated`
- `game_outcomes` — game_id, home_won (1/0), season — the win-probability label table
- `game_chapters` — one row per chapter per game (game_id, chapter_idx PK): start/end action_id, period, clock, elapsed seconds, margin and WP at each end, `label`, `drivers` (JSON). Written by `ChapterSegmenter`; table is defined but not yet created in Postgres (run `init_db()`).
- `team_standings_snapshots` — dated league standings, keyed (snapshot_date, team_id). **Only captured going forward** by the daily pipeline: `nba_api`'s standings endpoint has no as-of-date parameter, so past dates cannot be backfilled.

Note: play-by-play from `nba_api` has **no shot locations**. Anything needing shot-quality/xy data would require a new collector (e.g. `ShotChartDetail`).

This schema is the shared vocabulary for the ML models, the LLM queries, and the dashboard.

## AI/LLM layer

All LLM calls run **locally through Ollama** — `qwen2.5:32b` for reasoning/analysis, `qwen2.5:14b` for converting free-form output into strict JSON ([analysis/agent.py](analysis/agent.py) `_call_with_reasoning()`). **No cloud LLM APIs (OpenAI, Anthropic) are used anywhere in this repo.**

Four analyst agents run per game — scoring, team stats, player stats, MVP — each pulling data via [analysis/queries.py](analysis/queries.py) and a prompt template from [analysis/prompts/](analysis/prompts/). Downstream writer/editor agents (`run_scoring_writer`, `run_stats_writer`, `run_mvp_writer`, `run_editor`) are stubbed; prompt files exist but aren't wired up.

**Correction loop**: [streamlit/app.py](streamlit/app.py) lets a reviewer hand-edit both the structured JSON and the narrative text for a game's findings. "Save & Re-run" pushes edits into ChromaDB via `store_correction()`, and each analyst pulls its own prior corrections back in as prompt context on the next run — a human-in-the-loop feedback mechanism, not a one-shot pipeline.

## Win probability model (built)

[analysis/models/win_probability.py](analysis/models/win_probability.py) predicts home-win probability at every play. Design: `StandardScaler → LogisticRegression → CalibratedClassifierCV`, grouped CV by game, key feature `margin_x_pct` (score margin × time remaining). It has `predict_game()`, `get_significant_moments()`, `detect_scoring_runs()`, `evaluate()`, `check_temporal_bias()`, and `plot_calibration_curve()`, and a trained model is saved in `analysis/models/saved/`.

Its role going forward: the *play-to-play change* in win probability is the raw material for the storyline — chapter boundaries, momentum swings, and per-player Win Probability Added. Being good at forecasting game winners is not the objective.

## Known gaps / bugs

- Streamlit correction save/re-run only works for the Scoring & Momentum tab (`store_correction()` is called from tab 1 only). The Statistical Outliers and MVP tabs render editable fields but never persist them.
- `requirements.txt` was re-pinned 2026-08-17 but is missing `altair`, `pyarrow` and possibly others — what's installed in `venv` is the source of truth.
- `streamlit/components/{mvp,scoring,stats}.py` are empty — no component extraction from `app.py` has happened.
- `evaluate.py` and `game_context.py` are empty files.
- `FeatureEngineer.calculate_seconds_remaining` is wrong in overtime: it adds `(period - 4) * 300` on top of the OT clock, so 5:00 left at OT1 tip-off returns 600, not 300. Affects only OT plays in the win-probability features (the model was trained with this). Chapter segmentation computes elapsed time itself to avoid it.
- Substitution rows in `play_by_play` carry only the player going **out** in `player_id`/`player_name`; the incoming player exists only as a last name in `description` ("SUB: Smart FOR Vincent"). Lineup reconstruction (needed for bench-impact work) has to resolve incoming names against that game's box score roster.

## Direction / not yet built

**Dashboard vision**: pick a game, get a story. Proposed shape: a chaptered timeline of the game (scrubbable), each chapter showing its own visuals (margin/win-probability curve, team stat comparison, key players) alongside narration grounded in computed numbers. Story-level views (archetype, chapter list, headline) sit above the per-chapter detail.

**Chosen next**: (1) game-chapter segmentation and (3) player impact with a bench focus — audience is a coach ("where did the game shift, how did it get here", "which bench had the edge, should we play them more").

**ML models** (ordered by expected payoff; only #1 is under construction):

1. **Game-chapter segmentation** — *skeleton in `analysis/models/chapter_segmentation.py`*. Optimal (dynamic-programming) changepoint segmentation of margin *drift* on a fixed time grid, 3–6 chapters per game, WP used to rank/label chapters rather than find them, plus computed per-chapter "drivers" (shooting/turnovers/FT/off-rebounds/fouls). Persists to `game_chapters`. Gives the dashboard its timeline spine and the agents their narrative skeleton.
2. **Game-shape archetypes** — cluster margin curves across a season (wire-to-wire, comeback, seesaw, blowout, late collapse) so claims like "4th-biggest comeback of the season" are computed, and each archetype can have its own story template.
3. **Player impact, bench focus** — needs lineup reconstruction from Substitution events first (validate against box-score minutes). Then: per-game bench-unit net rating and on-court WP change (credits defense/screens, which actor-based WPA misses), and season-level regularized adjusted plus-minus (ridge regression on stints, leverage-weighted to discount garbage time) with uncertainty, to answer "should this player play more". Single-game numbers are noisy; minutes recommendations only at season level with confidence intervals. Play-by-play WPA (crediting the acting player) is a complementary lens.
4. **Performance "surprise" model** — predict expected player lines (season averages, opponent, minutes) and score deviation, giving the outlier agents a ranked list of statistically grounded outliers.
5. **Myth-busting event analysis** (e.g. do timeouts actually stop runs?) — a recurring content-style segment rather than per-game structure.

**Proposed agentic workflow**: ML layer writes chapters/archetype/WPA/surprise signals to Postgres → a **planner agent** picks the story angle from those signals → **specialist agents** each narrate their chapter or player from only the relevant data → an **editor agent** checks the narrative against the computed facts → the dashboard renders it. The existing four analyst agents would become (or feed) the specialists.

## Tech stack

- **Data**: PostgreSQL via SQLAlchemy, `nba_api` for scraping, `.env` (gitignored) holds Postgres credentials — read via [config/settings.py](config/settings.py)
- **LLM**: Ollama running `qwen2.5:32b` / `qwen2.5:14b` locally, `json_repair` for malformed JSON recovery — no cloud LLM APIs
- **Vector store**: ChromaDB, local/embedded (`./chroma_db`)
- **UI**: Streamlit (currently the reviewer tool; the end-user dashboard is to be built)
- **ML**: scikit-learn (win probability). Changepoint/HMM and clustering libraries (e.g. `ruptures`, `hmmlearn`) and XGBoost are not yet dependencies.
