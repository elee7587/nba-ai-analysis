# %% [markdown]
# # Win Probability Model — EDA & Statistical Analysis
#
# Scratch notebook for exploring play-by-play data and testing statistical
# analyses / visualizations ahead of (or alongside) `analysis/models/win_probability.py`.
#
# Uses the already-implemented `FeatureEngineer` / `WinProbabilityModel` classes so
# this stays in sync with the actual training pipeline — pull data through those
# rather than hand-rolling new SQL here.

# %% [markdown]
# ## 1. Setup

# %%
import sys
from pathlib import Path

# repo root on path so `analysis.*` / `data.*` imports work from notebooks/
PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score, classification_report
from sklearn.calibration import calibration_curve

from analysis.models.feature_engineering import FeatureEngineer
from analysis.models.win_probability import WinProbabilityModel, FEATURE_COLS, TARGET_COL
from data.storage.db import SessionLocal
from data.storage.models import Game, GameOutcome, PlayByPlay

sns.set_theme(style="whitegrid")
pd.set_option("display.max_columns", None)

# %% [markdown]
# ## 2. Load data
#
# Build the play-level feature set via `FeatureEngineer` / `WinProbabilityModel`
# (same code path used in training — see `analysis/models/train.py`). Start with
# one season to keep iteration fast, widen once the analysis stabilizes.

# %%
SEASONS = ["22024"]  # nba_api SEASON_ID convention: "2"+year = regular season, "4"+year = playoffs

engineer = FeatureEngineer()
wp_model = WinProbabilityModel()

raw_df = wp_model.build_training_data(SEASONS)
raw_df.shape

# %%
df = wp_model.validate_features(raw_df)
df.head()

# %% [markdown]
# ## 3. Data overview / sanity checks

# %%
print(f"rows: {len(df)}, games: {df['game_id'].nunique()}")
df.dtypes

# %%
df[FEATURE_COLS + [TARGET_COL]].isna().sum()

# %%
df[TARGET_COL].value_counts(normalize=True)

# %%
df[FEATURE_COLS].describe().T

# %% [markdown]
# ## 4. Exploratory analysis / visualizations
#
# Scratch space — try whatever's interesting here.

# %%
# feature distributions
fig, axes = plt.subplots(2, 3, figsize=(16, 8))
for ax, col in zip(axes.flat, ["score_margin", "pct_game_remaining", "margin_x_pct",
                                "run_size_at_play", "total_points", "consecutive_team_scores"]):
    sns.histplot(df[col], ax=ax, bins=40)
    ax.set_title(col)
plt.tight_layout()

# %% [markdown]
# ### Follow-ups from the distribution plots above
#
# - **Score margin**: does leading (even narrowly) at the end of each quarter predict the win?
# - **Run size at play**: does the team with the bigger scoring run in a game tend to win it?
# - **Consecutive team scores**: does streak length/timing shift by quarter, and does that track with outcome?

# %%
# score_margin per quarter — does leading at each quarter's end predict the win?
period_end = (
    df[df["period"].between(1, 4)]
    .sort_values(["game_id", "period", "action_id"])
    .groupby(["game_id", "period"], as_index=False)
    .last()[["game_id", "period", "score_margin"]]
)

margin_by_q = period_end.pivot(index="game_id", columns="period", values="score_margin")
margin_by_q.columns = [f"margin_end_q{c}" for c in margin_by_q.columns]
margin_by_q["home_won"] = df.groupby("game_id")["home_won"].first()

baseline_win_rate = margin_by_q["home_won"].mean()
for q in range(1, 5):
    col = f"margin_end_q{q}"
    if col not in margin_by_q:
        continue
    home_leading = margin_by_q[col] > 0
    print(
        f"Q{q} end — home leads in {home_leading.mean():.1%} of games; "
        f"wins {margin_by_q.loc[home_leading, 'home_won'].mean():.1%} of those "
        f"(baseline home win rate: {baseline_win_rate:.1%})"
    )

# per-quarter net score (who "won" that specific quarter) vs final outcome
margin_by_q = margin_by_q.rename(columns={"margin_end_q1": "q1_net"})
net_cols = ["q1_net"]
for q in [2, 3, 4]:
    if f"margin_end_q{q}" in margin_by_q and f"margin_end_q{q - 1}" in margin_by_q:
        margin_by_q[f"q{q}_net"] = margin_by_q[f"margin_end_q{q}"] - margin_by_q[f"margin_end_q{q - 1}"]
        net_cols.append(f"q{q}_net")

plt.figure(figsize=(6, 5))
sns.heatmap(margin_by_q[net_cols + ["home_won"]].corr(), annot=True, cmap="coolwarm", center=0)
plt.title("Per-quarter net score vs home_won")


# %%
# run_size_at_play — does the team with the bigger scoring run in a game tend to win it?
# 'team' on a row is whoever made the play; use the change in score_margin to tell
# which side (home/away) that run actually belongs to.
df_sorted = df.sort_values(["game_id", "action_id"]).copy()
df_sorted["margin_delta"] = df_sorted.groupby("game_id")["score_margin"].diff()
df_sorted["scoring_side"] = np.select(
    [df_sorted["margin_delta"] > 0, df_sorted["margin_delta"] < 0],
    ["home", "away"],
    default=None,
)

max_run_by_side = (
    df_sorted[df_sorted["run_size_at_play"] > 0]
    .groupby(["game_id", "scoring_side"], observed=True)["run_size_at_play"]
    .max()
    .unstack("scoring_side")
    .dropna(subset=["home", "away"])
)
max_run_by_side["home_won"] = df.groupby("game_id")["home_won"].first()
max_run_by_side["bigger_run_is_home"] = max_run_by_side["home"] > max_run_by_side["away"]

print("Win rate by which side had the game's single biggest scoring run:")
print(max_run_by_side.groupby("bigger_run_is_home")["home_won"].mean())

plt.figure(figsize=(6, 5))
sns.scatterplot(
    data=max_run_by_side, x="home", y="away", hue="home_won", alpha=0.4, palette="coolwarm"
)
plt.plot([0, max_run_by_side[["home", "away"]].values.max()],
         [0, max_run_by_side[["home", "away"]].values.max()],
         linestyle="--", color="gray")
plt.title("Biggest home run vs biggest away run, by game outcome")

# %%
# consecutive_team_scores by quarter — does streak length shift over the game,
# and does that relate to who wins? (avg ~2-3 plays per streak observed above)
# filter to actual scoring plays — consecutive_team_scores/run_size_at_play are
# carried forward onto every non-scoring row too (see feature_engineering.py),
# so filtering on the value itself would double-count carried-forward rows.
scoring_plays = df[(df["period"].between(1, 4)) & (df["points_scored_on_play"] > 0)]

plt.figure(figsize=(8, 5))
sns.boxplot(data=scoring_plays, x="period", y="consecutive_team_scores")
plt.title("Consecutive team scores by quarter")

quarter_streak = (
    scoring_plays
    .groupby(["game_id", "period"])["consecutive_team_scores"]
    .mean()
    .reset_index()
    .merge(df.groupby("game_id")["home_won"].first().reset_index(), on="game_id")
)

plt.figure(figsize=(8, 5))
sns.lineplot(data=quarter_streak, x="period", y="consecutive_team_scores", hue="home_won", errorbar="ci")
plt.title("Avg scoring-streak length per quarter, by game outcome (home_won)")
plt.xlabel("period")
plt.ylabel("avg consecutive_team_scores")


# %% [markdown]
# # Analysis
#
# From our analysis, it's difficult to see any strong correlations between the impact of conseuctive team scores vs. wins and biggest runs with wins. From here I think we need to look at this more holistically and move forward. This individual analysis isn't revealing much, and viewing this data in its totality is probably more benficial. Next we will check to see the correlation between these features (we are bound to see a few of these be similar as they pull from similar columns)

# %%
# correlation among candidate features
corr = df[FEATURE_COLS + [TARGET_COL]].corr()
plt.figure(figsize=(12, 10))
sns.heatmap(corr, cmap="coolwarm", center=0, annot=False)
plt.title("Feature correlation")

# %%
# margin_x_pct vs actual home win rate, binned — the key interaction feature
bins = pd.cut(df["margin_x_pct"], bins=20)
win_rate_by_bin = df.groupby(bins, observed=True)[TARGET_COL].mean()
win_rate_by_bin.plot(kind="bar", figsize=(14, 4), title="home_won rate by margin_x_pct bin")
plt.xticks(rotation=45, ha="right")

# %%
# score margin vs pct game remaining, colored by outcome — sanity check the WP surface shape
sample = df.sample(min(20000, len(df)), random_state=42)
plt.figure(figsize=(8, 6))
sns.scatterplot(
    data=sample, x="pct_game_remaining", y="score_margin",
    hue=TARGET_COL, alpha=0.15, s=10, palette="coolwarm"
)
plt.gca().invert_xaxis()  # game progresses left -> right
plt.title("Score margin over game time, by outcome")

# %%
# multicollinearity check — score_margin, score_margin_sq, and margin_x_pct are
# constructed from each other, so high correlation is expected; this affects how much
# to trust individual coefficients later, not the model's overall predictive power
from sklearn.linear_model import LinearRegression

collinear_cols = ["score_margin", "score_margin_sq", "margin_x_pct", "pct_game_remaining"]
print(df[collinear_cols].corr())

vif_rows = []
for col in collinear_cols:
    other_cols = [c for c in collinear_cols if c != col]
    r2 = LinearRegression().fit(df[other_cols], df[col]).score(df[other_cols], df[col])
    vif = 1 / (1 - r2) if r2 < 1 else np.inf
    vif_rows.append((col, vif))

# VIF > 10 is the usual rule-of-thumb flag for problematic multicollinearity
pd.DataFrame(vif_rows, columns=["feature", "VIF"]).sort_values("VIF", ascending=False)

# %%
# lead changes & biggest margin swing per game — a model-free "how dramatic was this
# game" proxy (no trained WP model needed yet), closer to the actual content-selection
# question than pure model diagnostics
sorted_df = df.sort_values(["game_id", "action_id"]).copy()
sorted_df["lead_sign"] = np.sign(sorted_df["score_margin"])
# ties (lead_sign == 0) aren't a "side" — carry forward the last actual leader so a
# tie isn't miscounted as a lead change
sorted_df["lead_sign_ffill"] = sorted_df.groupby("game_id")["lead_sign"].transform(
    lambda s: s.replace(0, np.nan).ffill()
)
sorted_df["lead_change"] = sorted_df.groupby("game_id")["lead_sign_ffill"].diff().fillna(0) != 0

game_drama = (
    sorted_df.groupby("game_id")
    .agg(
        lead_changes=("lead_change", "sum"),
        biggest_margin=("score_margin", lambda s: s.abs().max()),
        max_swing=("score_margin", lambda s: s.max() - s.min()),
    )
    .reset_index()
    .merge(df.groupby("game_id")["home_won"].first().reset_index(), on="game_id")
)

print(game_drama[["lead_changes", "biggest_margin", "max_swing"]].describe())

plt.figure(figsize=(7, 5))
sns.histplot(game_drama["lead_changes"], bins=30)
plt.title("Lead changes per game")

# most back-and-forth games — good candidates for the "momentum swing" content angle
game_drama.sort_values("lead_changes", ascending=False).head(10)

# %% [markdown]
# ## 5. Train / test split
#
# Grouped by `game_id` — plays from the same game must stay on one side of the
# split (see `WinProbabilityModel` docstring for why).

# %%
from sklearn.model_selection import GroupShuffleSplit

X = df[FEATURE_COLS]
y = df[TARGET_COL].values
groups = df["game_id"].values

train_idx, test_idx = next(
    GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42).split(X, y, groups)
)
X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
y_train, y_test = y[train_idx], y[test_idx]
len(X_train), len(X_test)

# %% [markdown]
# ## 6. Baseline model
#
# Quick uncalibrated fit for fast iteration on features — use
# `WinProbabilityModel.train()` / `cross_validate()` (StandardScaler → LogisticRegression
# → CalibratedClassifierCV) once you're ready for the "real" model.

# %%
baseline = Pipeline([
    ("scaler", StandardScaler()),
    ("logreg", LogisticRegression(C=1.0, max_iter=1000)),
])
baseline.fit(X_train, y_train)

probs = baseline.predict_proba(X_test)[:, 1]
preds = (probs >= 0.5).astype(int)

print(f"log_loss:  {log_loss(y_test, probs):.4f}")
print(f"brier:     {brier_score_loss(y_test, probs):.4f}")
print(f"roc_auc:   {roc_auc_score(y_test, probs):.4f}")
print(classification_report(y_test, preds))

# %%
# coefficients — since features are standardized, magnitude is roughly comparable
coefs = pd.Series(baseline.named_steps["logreg"].coef_[0], index=FEATURE_COLS).sort_values()
coefs.plot(kind="barh", figsize=(8, 8), title="Logistic regression coefficients (standardized)")

# %%
# calibration curve — is a predicted 70% WP actually right ~70% of the time?
prob_true, prob_pred = calibration_curve(y_test, probs, n_bins=10, strategy="uniform")
plt.figure(figsize=(6, 6))
plt.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")
plt.plot(prob_pred, prob_true, marker="o", label="Baseline model")
plt.xlabel("Predicted win probability")
plt.ylabel("Observed win frequency")
plt.legend()

# %% [markdown]
# ## 7. Full pipeline (calibrated + grouped CV)
#
# Uses the actual production model class — good for checking new features/ideas
# against the real CV setup before touching `win_probability.py`.

# %%
cv_results = wp_model.cross_validate(df)
cv_results

# %%
fit_metadata = wp_model.train(df=df)
fit_metadata

# %%
eval_metrics = wp_model.evaluate(df)
eval_metrics

# %% [markdown]
# ## 8. Single-game inspection
#
# Sanity-check the WP curve for one specific game.

# %%
SAMPLE_GAME_ID = df["game_id"].iloc[0]

game_wp = wp_model.predict_game(SAMPLE_GAME_ID)
game_wp.head()

# %%
plt.figure(figsize=(14, 4))
plt.plot(game_wp["action_id"], game_wp["home_wp"])
plt.axhline(0.5, linestyle="--", color="gray")
plt.title(f"Home win probability over game {SAMPLE_GAME_ID}")
plt.xlabel("action_id")
plt.ylabel("home_wp")

# %%
wp_model.get_significant_moments(SAMPLE_GAME_ID, threshold=0.08)

# %% [markdown]
# ## 9. Scratch
#
# Open space for one-off experiments.

# %%
