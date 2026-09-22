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

2. **ML layer** ([analysis/models/](analysis/models/)) — models that turn play-by-play and box-score data into story signals. Built: game-chapter segmentation. Win probability has code but **no trained model** (removed as broken — see Win probability model). The rest are proposed (see Direction). Exploratory analyses that justify design choices live in [analysis/exploration/](analysis/exploration/).

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
  prompts/                   # markdown prompt templates, filled with str.format() — keep placeholders and doubled {{ }} in JSON schemas intact. Wired-in analysts: scoring/team_stats/player_stats/mvp; writers + editor are worded for dashboard text but not called yet. game_analyst.md / quarter_analyst.md are legacy (imported, never used; their schemas have drifted from agent.py)
  models/
    feature_engineering.py    # FeatureEngineer — play-level + momentum features, plus game-context features for a possible pre-game model
    win_probability.py         # WinProbabilityModel — code only, NO trained model; has the score-carry-forward bug (see Known gaps), fix before retraining
    train.py                    # trains the WP model on DEFAULT_SEASONS (2024, 2025 regular season + playoffs) and saves to saved/ (dir doesn't exist until a model is saved)
    chapter_segmentation.py      # ChapterSegmenter — built: descriptive chapters from the margin curve, K fixed or archetype-driven; saves to game_chapters
    game_archetypes.py            # GameArchetypeClassifier — built: clusters whole-game margin-curve shapes, derives a chapter count per cluster; saves to game_archetypes + saved/archetype_model_latest.pkl
    evaluate.py, game_context.py   # empty (0 bytes) — not started
  exploration/
    chapter_eda.py              # analysis behind the chapter design; writes figures + summary.json to output/chapter_eda/ (gitignored)

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
- `game_chapters` — one row per chapter per game (game_id, chapter_idx PK): start/end action_id, period, clock, elapsed seconds, margin at each end, `margin_swing`, `home_points`/`away_points`, `label`, `drivers` (JSON, empty until built). Written by `ChapterSegmenter.save_chapters()`, which creates the table if missing.
- `game_archetypes` — one row per game (game_id PK): `archetype_id` (cluster index) and `label` (heuristic shape name), the `k` ChapterSegmenter should use for that game, `complexity` (total variation of the margin drift), and `model_version` (timestamp of the clustering run — `archetype_id`/`k` are only meaningful within the same version). Written by `GameArchetypeClassifier.save_archetypes()` (upsert by game_id), which creates the table if missing.
- `team_standings_snapshots` — dated league standings, keyed (snapshot_date, team_id). **Only captured going forward** by the daily pipeline: `nba_api`'s standings endpoint has no as-of-date parameter, so past dates cannot be backfilled.

Note: play-by-play from `nba_api` has **no shot locations**. Anything needing shot-quality/xy data would require a new collector (e.g. `ShotChartDetail`).

This schema is the shared vocabulary for the ML models, the LLM queries, and the dashboard.

## AI/LLM layer

All LLM calls run **locally through Ollama** — `qwen2.5:32b` for reasoning/analysis, `qwen2.5:14b` for converting free-form output into strict JSON ([analysis/agent.py](analysis/agent.py) `_call_with_reasoning()`). **No cloud LLM APIs (OpenAI, Anthropic) are used anywhere in this repo.**

Four analyst agents run per game — scoring, team stats, player stats, MVP — each pulling data via [analysis/queries.py](analysis/queries.py) and a prompt template from [analysis/prompts/](analysis/prompts/). Downstream writer/editor agents (`run_scoring_writer`, `run_stats_writer`, `run_mvp_writer`, `run_editor`) are stubbed; prompt files exist but aren't wired up.

**Correction loop**: [streamlit/app.py](streamlit/app.py) lets a reviewer hand-edit both the structured JSON and the narrative text for a game's findings. "Save & Re-run" pushes edits into ChromaDB via `store_correction()`, and each analyst pulls its own prior corrections back in as prompt context on the next run — a human-in-the-loop feedback mechanism, not a one-shot pipeline.

## Win probability model (code only — trained model removed)

[analysis/models/win_probability.py](analysis/models/win_probability.py) is code for a per-play home-win-probability model: `StandardScaler → LogisticRegression → CalibratedClassifierCV`, grouped CV by game, key feature `margin_x_pct` (score margin × time remaining), with `predict_game()`, `get_significant_moments()`, `detect_scoring_runs()`, `evaluate()`, `check_temporal_bias()`, `plot_calibration_curve()`.

**The trained model was deleted on 2026-09-19** (`analysis/models/saved/*.pkl`, still in git history) because it was trained on corrupted features — see the first item in Known gaps. Until the bug is fixed and the model retrained, nothing in the repo depends on it: chapter segmentation uses only the score margin.

Its intended role once fixed: the *play-to-play change* in win probability measures how much each moment mattered — used to rank chapters by importance and for per-player Win Probability Added. Being good at forecasting game winners is not the objective.

## Known gaps / bugs

- **Win-probability code has a feature bug (found 2026-09-19; not yet fixed; trained model deleted).** `play_by_play` only records scores on scoring plays (~74% of rows are NULL) and nothing carries them forward. In the training path (`FeatureEngineer.build_play_features_df` → `build_play_features`) `play.get('score_margin', 0) or 0` turns NULL into 0, so **74.8% of training rows have `score_margin == 0` when only 4.5% truly should** (checked on 40 games); `total_points`, `margin_x_pct` etc. are zeroed the same way. In the inference path `WinProbabilityModel._build_inference_df` overwrites the engineered `score_margin` with the raw DB value, so `predict_game()` crashes with NaN on every game. The deleted model was trained on the corrupted features, so its outputs and any earlier feature analysis should not be trusted. Fix = forward-fill `home_score`/`away_score` within each game (start 0) before building features, in both paths, then retrain.
- **Prompt/data mismatches** (prompts were rewritten 2026-09-19 to be honest about these; fix at the source when convenient):
  - `get_play_by_play` passes raw ORM rows including noise (`created_at`, `game_id`, `player_id`) and null scores on ~74% of plays; the prompts now tell the model to carry the last non-null score forward, but carrying it forward in `queries.py` would be more reliable. Timeouts are filtered out (`EXCLUDE_EVENT_TYPES`), so prompts must not cite them.
  - `run_mvp_analyst` is not given play-by-play, so its "key moments" are statistical highlights only; the MVP writer does receive it.
  - Season baselines exist only for pts/reb/ast/stl/blk/tov/fg_pct (+ plus_minus and ranks): no usage, minutes, 3P%, FT% or pace baseline. Season figures are a full-season snapshot that includes the game itself. Ranks are 1 = best (turnovers inverted).
  - The editor is told to infer home/away from which score increases on a scoring play; passing the home and away tricodes explicitly would be cleaner.
  - The agent-side JSON schemas in `agent.py` (used by the formatting model) differ from the shapes in `game_analyst.md` and `mvp_writer.md` (e.g. flat MVP stats vs nested `key_stats`, `value` vs `game_value`).
  - Prompt stance from the chapter analysis: don't attribute later scoring to "momentum" — real games are mean-reverting; describe what happened to the margin and whether the opponent answered.
- Streamlit correction save/re-run only works for the Scoring & Momentum tab (`store_correction()` is called from tab 1 only). The Statistical Outliers and MVP tabs render editable fields but never persist them.
- `requirements.txt` was re-pinned 2026-08-17 but is missing `altair`, `pyarrow` and possibly others — what's installed in `venv` is the source of truth.
- `streamlit/components/{mvp,scoring,stats}.py` are empty — no component extraction from `app.py` has happened.
- `evaluate.py` and `game_context.py` are empty files.
- Game `0022500232` has truncated play-by-play (last recorded score 60-55, final 112-123); `ChapterSegmenter.segment_game` skips any game whose play-by-play doesn't reach the final score. `db.py` creates the engine with `echo=True`, so every query is logged to the console (noisy for batch runs).
- `FeatureEngineer.calculate_seconds_remaining` is wrong in overtime: it adds `(period - 4) * 300` on top of the OT clock, so 5:00 left at OT1 tip-off returns 600, not 300. Affects only OT plays in the win-probability features (the model was trained with this). Chapter segmentation computes elapsed time itself to avoid it.
- Substitution rows in `play_by_play` carry only the player going **out** in `player_id`/`player_name`; the incoming player exists only as a last name in `description` ("SUB: Smart FOR Vincent"). Lineup reconstruction (needed for bench-impact work) has to resolve incoming names against that game's box score roster.

## Direction / not yet built

**Dashboard vision**: pick a game, get a story. Proposed shape: a chaptered timeline of the game (scrubbable), each chapter showing its own visuals (margin/win-probability curve, team stat comparison, key players) alongside narration grounded in computed numbers. Story-level views (archetype, chapter list, headline) sit above the per-chapter detail.

**Chosen next**: (1) game-chapter segmentation and (3) player impact with a bench focus — audience is a coach ("where did the game shift, how did it get here", "which bench had the edge, should we play them more").

**ML models** (ordered by expected payoff; #1 and #2 built, the rest not started):

1. **Game-chapter segmentation** — *built, in `analysis/models/chapter_segmentation.py`*. Splits each game into K chapters (each ≥ 4 game-minutes) by exact dynamic-programming partition of the margin *drift* on a 30s grid, and labels each deterministically (e.g. `"MEM +11 (26-15)"`, `"Even (24-22)"`). K defaults to a fixed 4, or — with `use_archetype_k=True` — is looked up per game from its `game_archetypes` row (see #2), bounded to 3–6. Persists to `game_chapters`. Validated on 300 games: always K chapters, chapters tile the game, margin swings sum to the final margin, boundaries identical to the EDA prototype; the full database has not been segmented yet (`ChapterSegmenter().segment_season([...])`).

   **It is descriptive, not inferential** — this is a deliberate result of `analysis/exploration/chapter_eda.py` (2,619 games): (a) a penalized changepoint detector found no more chapters in real games than in the same games with scoring shuffled; (b) real games are *less* streaky than chance (lag-1 autocorrelation of 30s margin drift −0.08, variance ratio 0.82 at 16 minutes; biggest 4-minute run 12 pts real vs 13.25 shuffled) — mean-reverting, no evidence of momentum; (c) fixed-K boundaries are stable across 15/30/60s bins (81–84% within 90s vs an 18% chance baseline). So a chapter boundary is *not* a claim the game "changed"; close games get near-arbitrary chapters (labeled "Even"). Don't write narrative implying momentum. **Still to build**: `compute_drivers()` — *why* the margin moved (likely framed as skill vs luck: opponent shooting vs season norms) — and WP-based importance ranking once win probability is fixed.
2. **Game-shape archetypes** — *built, in `analysis/models/game_archetypes.py`*, fit once on all 2,618 usable 2024/2025 games (`fit_and_save(["22024","42024","22025","42025"])`, model version `20260922T215055`). Clusters each game's whole regulation-time margin curve (from the eventual winner's perspective, so home/away isn't a free parameter of the shape) via KMeans, k chosen by silhouette; each cluster gets a deterministic heuristic label (wire-to-wire, comeback, seesaw, blowout, nailbiter, mixed — first-pass thresholds, meant to be revisited, see below) and a chapter count (3–6) bucketed by the cluster's average margin-drift "complexity". Persists to `game_archetypes`; the fitted model pickles to `analysis/models/saved/archetype_model_latest.pkl` (gitignored — regenerate with `fit_and_save()`; only ever loaded from files this codebase wrote itself, same trust boundary as the win-probability model).

   **First real fit is weak, not yet trustworthy**: silhouette came out to only 0.267, and silhouette-over-`CANDIDATE_K` picked the smallest candidate (k=3) — a sign 96-dimensional raw curves aren't separating cleanly. Two of the three resulting clusters both got labeled `"wire-to-wire"` (1,213 games, k=4, and 485 games, k=5) and the third is `"mixed"` (920 games, k=4); mean complexity is nearly identical across all three (142.7–145.6), so the k differences barely reflect a real distinction yet. Usable as a coupling mechanism for `ChapterSegmenter(use_archetype_k=True)`, but the archetype *labels* shouldn't be trusted for narrative yet. Likely fixes to try before relying on it: a lower-dimensional/normalized feature representation (e.g. explicit features like max deficit, lead changes, half-margins instead of the raw 96-point curve) rather than raw-curve Euclidean KMeans, and re-checking whether label thresholds calibrated on synthetic curves hold on the real centroid distribution. This is still a different kind of claim than chapter boundaries and isn't subject to the "no more than chance" caution — whole-game shapes are just observably different curves — but the current clustering isn't yet finding that difference well. Not yet wired: claims like "4th-biggest comeback of the season" (needs a season-wide rank over `complexity`/`min` per label) and per-archetype story templates.
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
