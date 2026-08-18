# analysis/models/win_probability.py
import numpy as np
import pandas as pd
import pickle
from pathlib import Path
from datetime import datetime
from loguru import logger
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from analysis.models.feature_engineering import FeatureEngineer
from data.storage.db import SessionLocal
from data.storage.models import Game, GameOutcome, PlayByPlay

MODEL_DIR  = Path("analysis/models/saved")
MODEL_PATH = MODEL_DIR / "wp_model_latest.pkl"

# feature columns used by the model
# must match exactly what FeatureEngineer.build_play_features() returns
FEATURE_COLS = [
    # Game state features (what we have)
    'score_margin',
    'seconds_remaining',
    'pct_game_remaining',
    'period',
    'margin_x_pct',
    'score_margin_sq',
    'is_overtime',
    'total_points',

    # Play event features (what we need to add)
    'is_made_shot',
    'is_missed_shot',
    'is_three_pointer',
    'is_free_throw',
    'is_turnover',
    'is_rebound',
    'is_offensive_rebound',
    'is_block',
    'is_steal',
    'points_scored_on_play',

    # Momentum context (derived from sequence of plays)
    'consecutive_team_scores',   # unanswered points streak going into this play
    'consecutive_team_misses',   # consecutive misses going into this play
    'run_size_at_play',          # how big the current run is
]

TARGET_COL = 'home_won'

class WinProbabilityModel:
    """
    Logistic Regression model for in-game win probability.

    Design decisions:
    - Logistic regression chosen for interpretability and calibration
    - StandardScaler normalizes features since LR is sensitive to scale
    - CalibratedClassifierCV ensures predicted probabilities are reliable
      i.e. a predicted 70% WP should win ~70% of the time
    - Pipeline wraps scaler + model to prevent data leakage during CV
    - StratifiedGroupKFold (grouped by game_id) preserves class balance
      AND keeps every play from a given game on one side of the split —
      plays within a game share the same home_won label, so an ordinary
      StratifiedKFold would leak game identity between train and test
    - Key insight: the interaction term margin_x_pct is the most important
      feature — it captures that the same lead means different things at
      different points in the game
    """

    def __init__(self):
        self.pipeline  = None  # sklearn Pipeline (scaler + model)
        self.engineer  = FeatureEngineer()
        self.is_fitted = False
        self.metrics   = {}    # stores latest fit/evaluation metadata

    def _check_fitted(self):
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("Model is not fitted. Call train() or load() first.")

    # ── Data Preparation ─────────────────────────────────────────

    def build_training_data(self, seasons: list[str] = None) -> pd.DataFrame:
        """
        Build full training dataset across one or more seasons
        Joins play by play features with game outcome labels

        Args:
            seasons: list of season strings e.g. ['22024', '22025']
                     if None pulls all available seasons

        Returns:
            DataFrame with FEATURE_COLS + TARGET_COL columns
            One row per play across all games
        """
        game_ids = self.get_game_ids(seasons)
        if not game_ids:
            logger.warning("No games found to build training data from")
            return pd.DataFrame()

        frames = []
        for i, game_id in enumerate(game_ids):
            try:
                game_df = self.engineer.build_play_features_df(game_id)
                if not game_df.empty:
                    frames.append(game_df)
            except Exception as e:
                logger.error(f"Skipping game {game_id}: {e}")

            if (i + 1) % 50 == 0:
                logger.info(f"Built features for {i + 1}/{len(game_ids)} games")

        if not frames:
            logger.warning("No play features could be built from any game")
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        logger.info(f"Built training data: {len(df)} plays across {len(frames)} games")
        return df

    def get_game_ids(self, seasons: list[str] = None) -> list[str]:
        """
        Get all game IDs that have both play by play and outcome data
        Filters out games missing either data source

        Args:
            seasons: list of season strings to filter by

        Returns:
            list of valid game IDs for training
        """
        session = SessionLocal()
        try:
            query = session.query(GameOutcome.game_id)\
                .join(Game, Game.game_id == GameOutcome.game_id)\
                .filter(GameOutcome.game_id.in_(
                    session.query(PlayByPlay.game_id).distinct()
                ))

            if seasons:
                query = query.filter(Game.season.in_(seasons))

            game_ids = [row[0] for row in query.distinct().all()]
            logger.info(
                f"Found {len(game_ids)} games with outcomes + play-by-play"
                + (f" for seasons {seasons}" if seasons else "")
            )
            return game_ids

        except Exception as e:
            logger.error(f"Failed to get game ids: {e}")
            return []
        finally:
            session.close()

    def validate_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate and clean feature DataFrame before training
        Handles:
        - Missing values (fills with sensible defaults)
        - Plays with null scores (non-scoring events)
        - Outliers in score margin (garbage time)
        - Class imbalance check

        Args:
            df: raw feature DataFrame from build_training_data

        Returns:
            cleaned DataFrame ready for training
        """
        if df.empty:
            return df

        df = df.copy()

        missing_before = df[FEATURE_COLS].isna().sum().sum()
        if missing_before:
            logger.warning(f"Found {missing_before} missing feature values, filling defaults")

        fill_defaults = {col: 0 for col in FEATURE_COLS}
        fill_defaults['pct_game_remaining'] = 0.5
        fill_defaults['period'] = 1
        df[FEATURE_COLS] = df[FEATURE_COLS].fillna(value=fill_defaults)

        before = len(df)
        df = df.dropna(subset=[TARGET_COL])
        if len(df) < before:
            logger.warning(f"Dropped {before - len(df)} rows with missing {TARGET_COL}")

        # clip extreme score margins (garbage time / data errors) so they
        # don't blow up the scaler, and keep the derived features consistent
        margin_cap = 50
        n_clipped = int((df['score_margin'].abs() > margin_cap).sum())
        if n_clipped:
            logger.info(f"Clipping {n_clipped} plays with |score_margin| > {margin_cap} (garbage time)")
            df['score_margin']    = df['score_margin'].clip(-margin_cap, margin_cap)
            df['score_margin_sq'] = df['score_margin'] ** 2
            df['margin_x_pct']    = df['score_margin'] * df['pct_game_remaining']

        class_counts = df[TARGET_COL].value_counts(normalize=True)
        logger.info(f"Class balance (home_won): {class_counts.to_dict()}")
        if class_counts.min() < 0.3:
            logger.warning("Class imbalance detected in home_won — consider class_weight or resampling")

        df[TARGET_COL] = df[TARGET_COL].astype(int)

        return df

    # ── Training ─────────────────────────────────────────────────

    def train(self, df: pd.DataFrame = None, seasons: list[str] = None):
        """
        Train the win probability model

        Args:
            df: pre-built feature DataFrame (if None builds from DB)
            seasons: seasons to train on (if df is None)

        Pipeline:
            StandardScaler → LogisticRegression → CalibratedClassifierCV

        Notes:
            - Uses C=1.0 regularization (tune if overfitting)
            - max_iter=1000 for convergence on large datasets
            - Calibration ensures reliable probability estimates
            - Fits on the full given dataset; this reports fit metadata only,
              not generalization performance — use cross_validate() or
              evaluate() on a held-out set for that
        """
        if df is None:
            df = self.build_training_data(seasons)

        df = self.validate_features(df)
        if df.empty:
            raise ValueError("No training data available — check seasons/game_ids and DB contents")

        X      = df[FEATURE_COLS]
        y      = df[TARGET_COL].values
        groups = df['game_id'].values

        base_pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('logreg', LogisticRegression(C=1.0, max_iter=1000)),
        ])

        # calibration CV folds grouped by game_id — see class docstring
        cv_splits = list(
            StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
            .split(X, y, groups=groups)
        )

        self.pipeline = CalibratedClassifierCV(base_pipeline, method='sigmoid', cv=cv_splits)

        logger.info(f"Training on {len(X)} plays from {df['game_id'].nunique()} games")
        self.pipeline.fit(X, y)
        self.is_fitted = True

        self.metrics = {
            "n_plays":       int(len(df)),
            "n_games":       int(df['game_id'].nunique()),
            "class_balance": {int(k): float(v) for k, v in df[TARGET_COL].value_counts(normalize=True).items()},
            "trained_at":    datetime.now().isoformat(),
        }
        logger.info(f"Training complete: {self.metrics}")
        return self.metrics

    def cross_validate(self, df: pd.DataFrame) -> dict:
        """
        Run stratified group k-fold cross validation, grouped by game_id
        so no game's plays appear in both the train and test side of a fold
        Reports mean and std of key metrics across folds

        Returns:
            dict with log_loss, brier_score, roc_auc, accuracy per fold
        """
        df = self.validate_features(df)
        if df.empty:
            raise ValueError("No data to cross-validate on")

        X      = df[FEATURE_COLS].values
        y      = df[TARGET_COL].values
        groups = df['game_id'].values

        cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
        fold_metrics = {"log_loss": [], "brier_score": [], "roc_auc": [], "accuracy": []}

        for fold, (train_idx, test_idx) in enumerate(cv.split(X, y, groups=groups), start=1):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('logreg', LogisticRegression(C=1.0, max_iter=1000)),
            ])
            calibrated = CalibratedClassifierCV(pipeline, method='sigmoid', cv=3)
            calibrated.fit(X_train, y_train)

            probs = calibrated.predict_proba(X_test)[:, 1]
            preds = (probs >= 0.5).astype(int)

            fold_metrics["log_loss"].append(log_loss(y_test, probs))
            fold_metrics["brier_score"].append(brier_score_loss(y_test, probs))
            fold_metrics["roc_auc"].append(roc_auc_score(y_test, probs))
            fold_metrics["accuracy"].append(float((preds == y_test).mean()))

            logger.info(
                f"Fold {fold}: log_loss={fold_metrics['log_loss'][-1]:.4f} "
                f"brier={fold_metrics['brier_score'][-1]:.4f} "
                f"auc={fold_metrics['roc_auc'][-1]:.4f} "
                f"acc={fold_metrics['accuracy'][-1]:.4f}"
            )

        summary = {
            metric: {"mean": float(np.mean(vals)), "std": float(np.std(vals))}
            for metric, vals in fold_metrics.items()
        }
        logger.info(f"5-fold CV summary: {summary}")
        return summary

    # ── Inference ────────────────────────────────────────────────

    def predict(self, features: dict) -> float:
        """
        Predict win probability for a single play

        Args:
            features: dict from FeatureEngineer.build_play_features()

        Returns:
            float: probability (0-1) that home team wins from this moment

        Raises:
            RuntimeError if model not fitted
        """
        self._check_fitted()
        row = pd.DataFrame([{col: features.get(col, 0) for col in FEATURE_COLS}])
        return float(self.pipeline.predict_proba(row)[0, 1])

    def predict_proba_df(self, df: pd.DataFrame) -> np.ndarray:
        """
        Predict win probability for a DataFrame of plays
        Internal helper used by predict_game()

        Args:
            df: DataFrame with FEATURE_COLS columns

        Returns:
            numpy array of probabilities
        """
        self._check_fitted()
        return self.pipeline.predict_proba(df[FEATURE_COLS])[:, 1]

    def _build_inference_df(self, game_id: str) -> pd.DataFrame:
        """
        Build engineered features + raw play context for one game
        Unlike FeatureEngineer.build_play_features_df() (training-focused,
        drops raw play metadata) this keeps clock/description/player_name
        alongside the features, since predict_game/get_significant_moments/
        detect_scoring_runs all need to report on the underlying play
        """
        session = SessionLocal()
        try:
            plays = session.query(PlayByPlay)\
                .filter(PlayByPlay.game_id == game_id)\
                .filter(~PlayByPlay.event_type.in_(['Timeout']))\
                .order_by(PlayByPlay.action_id)\
                .all()

            if not plays:
                logger.warning(f"No play-by-play found for game {game_id}")
                return pd.DataFrame()

            rows = []
            for play in plays:
                play_dict = {
                    "period":       play.period,
                    "clock":        play.clock,
                    "home_score":   play.home_score,
                    "away_score":   play.away_score,
                    "score_margin": play.score_margin,
                    "event_type":   play.event_type,
                    "description":  play.description,
                    "team":         play.team,
                }
                features = self.engineer.build_play_features(play_dict)
                features.update({
                    "game_id":      game_id,
                    "action_id":    play.action_id,
                    "period":       play.period,
                    "clock":        play.clock,
                    "home_score":   play.home_score,
                    "away_score":   play.away_score,
                    "score_margin": play.score_margin,
                    "event_type":   play.event_type,
                    "description":  play.description,
                    "player_name":  play.player_name,
                    "team":         play.team,
                })
                rows.append(features)

            df = pd.DataFrame(rows)
            df = self.engineer.add_momentum_features(df)
            return df

        except Exception as e:
            logger.error(f"Failed to build inference data for game {game_id}: {e}")
            raise
        finally:
            session.close()

    def predict_game(self, game_id: str) -> pd.DataFrame:
        """
        Calculate win probability for every play in a game

        Args:
            game_id: NBA game ID

        Returns:
            DataFrame with columns:
                action_id, period, clock, home_score, away_score,
                score_margin, event_type, description,
                home_wp, wp_shift
            Sorted by action_id ascending
        """
        self._check_fitted()

        df = self._build_inference_df(game_id)
        if df.empty:
            return df

        df = df.sort_values('action_id').reset_index(drop=True)
        df['home_wp']  = self.predict_proba_df(df)
        df['wp_shift'] = df['home_wp'].diff().fillna(0.0)

        output_cols = [
            'action_id', 'period', 'clock', 'home_score', 'away_score',
            'score_margin', 'event_type', 'description', 'home_wp', 'wp_shift'
        ]
        return df[output_cols]

    # ── Moment Detection ─────────────────────────────────────────

    def get_significant_moments(
        self,
        game_id:   str,
        threshold: float = 0.08
    ) -> list[dict]:
        """
        Find plays where win probability shifted significantly
        These become inputs to the quarter analyst agents

        Args:
            game_id:   NBA game ID
            threshold: minimum absolute WP shift to flag (default 8%)
                       tune this based on how many moments you want per game

        Returns:
            list of dicts sorted by wp_shift descending:
            [
                {
                    "action_id":    int,
                    "period":       int,
                    "clock":        str,
                    "description":  str,
                    "player_name":  str,
                    "team":         str,
                    "wp_before":    float,
                    "wp_after":     float,
                    "wp_shift":     float,  # signed — positive = home team gained
                    "abs_shift":    float,  # absolute value for ranking
                }
            ]
        """
        self._check_fitted()

        df = self._build_inference_df(game_id)
        if df.empty:
            return []

        df = df.sort_values('action_id').reset_index(drop=True)
        df['home_wp']   = self.predict_proba_df(df)
        df['wp_before'] = df['home_wp'].shift(1).fillna(df['home_wp'].iloc[0])
        df['wp_shift']  = df['home_wp'] - df['wp_before']
        df['abs_shift'] = df['wp_shift'].abs()

        significant = df[df['abs_shift'] >= threshold].sort_values('abs_shift', ascending=False)

        moments = []
        for _, row in significant.iterrows():
            moments.append({
                "action_id":   int(row['action_id']),
                "period":      int(row['period']),
                "clock":       row['clock'],
                "description": row['description'],
                "player_name": row['player_name'],
                "team":        row['team'],
                "wp_before":   float(row['wp_before']),
                "wp_after":    float(row['home_wp']),
                "wp_shift":    float(row['wp_shift']),
                "abs_shift":   float(row['abs_shift']),
            })

        logger.info(f"Found {len(moments)} significant moments in {game_id} (threshold={threshold})")
        return moments

    def detect_scoring_runs(
        self,
        game_id:        str,
        min_run_size:   int   = 6,
        wp_shift_weight: float = 0.5
    ) -> list[dict]:
        """
        Detect scoring runs using both point differential and WP shifts
        Combines algorithmic run detection with WP context

        A run is significant if:
        1. One team scores min_run_size+ unanswered points AND
        2. The cumulative WP shift during the run exceeds wp_shift_weight

        This hybrid approach is more meaningful than counting points alone
        — a 6-0 run with 30 seconds left is more significant than one in Q1

        Args:
            game_id:         NBA game ID
            min_run_size:    minimum unanswered points to flag
            wp_shift_weight: minimum cumulative WP shift during run

        Returns:
            list of run dicts with start/end times, WP context, key players
        """
        self._check_fitted()

        df = self._build_inference_df(game_id)
        if df.empty:
            return []

        df = df.sort_values('action_id').reset_index(drop=True)
        df['home_wp']         = self.predict_proba_df(df)
        df['wp_before_play']  = df['home_wp'].shift(1).fillna(df['home_wp'].iloc[0])

        scoring = df[df['points_scored_on_play'] > 0].reset_index(drop=True)
        if scoring.empty:
            return []

        runs            = []
        run_team        = None
        run_points      = 0
        run_start_idx   = 0
        wp_at_run_start = 0.0

        def close_run(end_idx):
            if run_team is None or run_points < min_run_size:
                return
            start_row = scoring.iloc[run_start_idx]
            end_row   = scoring.iloc[end_idx]
            wp_shift  = float(end_row['home_wp'] - wp_at_run_start)

            if abs(wp_shift) < wp_shift_weight:
                return

            key_players = sorted({
                p for p in scoring.iloc[run_start_idx:end_idx + 1]['player_name'] if p
            })

            runs.append({
                "team":            run_team,
                "points":          int(run_points),
                "start_action_id": int(start_row['action_id']),
                "end_action_id":   int(end_row['action_id']),
                "start_period":    int(start_row['period']),
                "start_clock":     start_row['clock'],
                "end_period":      int(end_row['period']),
                "end_clock":       end_row['clock'],
                "wp_before":       float(wp_at_run_start),
                "wp_after":        float(end_row['home_wp']),
                "wp_shift":        wp_shift,
                "abs_wp_shift":    abs(wp_shift),
                "key_players":     key_players,
            })

        for i, row in scoring.iterrows():
            team = row['team']
            if team == run_team:
                run_points += row['points_scored_on_play']
            else:
                close_run(i - 1)
                run_team        = team
                run_points      = row['points_scored_on_play']
                run_start_idx   = i
                wp_at_run_start = float(row['wp_before_play'])

        close_run(len(scoring) - 1)

        runs.sort(key=lambda r: r['abs_wp_shift'], reverse=True)
        logger.info(f"Detected {len(runs)} significant scoring runs in {game_id}")
        return runs

    # ── Persistence ──────────────────────────────────────────────

    def save(self, path: Path = None):
        """
        Save trained model to disk
        Saves both latest and versioned copy with timestamp

        Args:
            path: optional custom save path
        """
        self._check_fitted()
        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        save_path = path or MODEL_PATH
        payload = {
            "pipeline":     self.pipeline,
            "feature_cols": FEATURE_COLS,
            "metrics":      self.metrics,
            "trained_at":   datetime.now().isoformat(),
        }

        with open(save_path, "wb") as f:
            pickle.dump(payload, f)

        if Path(save_path) == MODEL_PATH:
            versioned_path = MODEL_DIR / f"wp_model_{datetime.now():%Y%m%d_%H%M%S}.pkl"
            with open(versioned_path, "wb") as f:
                pickle.dump(payload, f)
            logger.info(f"Saved model to {save_path} and {versioned_path}")
        else:
            logger.info(f"Saved model to {save_path}")

    def load(self, path: Path = None) -> bool:
        """
        Load saved model from disk

        Args:
            path: optional custom load path (defaults to latest)

        Returns:
            True if loaded successfully, False if no saved model found
        """
        load_path = Path(path) if path else MODEL_PATH
        if not load_path.exists():
            logger.warning(f"No saved model found at {load_path}")
            return False

        try:
            with open(load_path, "rb") as f:
                payload = pickle.load(f)

            self.pipeline  = payload["pipeline"]
            self.metrics   = payload.get("metrics", {})
            self.is_fitted = True

            saved_cols = payload.get("feature_cols", FEATURE_COLS)
            if saved_cols != FEATURE_COLS:
                logger.warning("Loaded model's feature columns differ from current FEATURE_COLS")

            logger.info(f"Loaded model from {load_path} (trained_at={payload.get('trained_at', 'unknown')})")
            return True

        except Exception as e:
            logger.error(f"Failed to load model from {load_path}: {e}")
            return False

    # ── Evaluation ───────────────────────────────────────────────

    def evaluate(self, df: pd.DataFrame) -> dict:
        """
        Full model evaluation including temporal bias check

        Metrics:
        - Accuracy
        - Log loss (primary metric for probability models)
        - Brier score (measures calibration quality)
        - ROC AUC
        - Calibration curve data

        Temporal bias check:
        - Splits test set into 4 time buckets (Q1, Q2, Q3, Q4)
        - Reports accuracy per bucket
        - Flags if early game accuracy < late game accuracy by >5%

        Args:
            df: test DataFrame with features + labels

        Returns:
            dict with all metrics and temporal bias results
        """
        self._check_fitted()

        df = self.validate_features(df)
        if df.empty:
            raise ValueError("No data to evaluate")

        probs = self.predict_proba_df(df)
        preds = (probs >= 0.5).astype(int)
        y     = df[TARGET_COL].values

        metrics = {
            "n_plays":     int(len(df)),
            "accuracy":    float((preds == y).mean()),
            "log_loss":    float(log_loss(y, probs)),
            "brier_score": float(brier_score_loss(y, probs)),
            "roc_auc":     float(roc_auc_score(y, probs)),
        }

        prob_true, prob_pred = calibration_curve(y, probs, n_bins=10, strategy='uniform')
        metrics["calibration_curve"] = {
            "prob_true": prob_true.tolist(),
            "prob_pred": prob_pred.tolist(),
        }

        metrics["temporal_bias"] = self.check_temporal_bias(df.assign(home_wp=probs))

        logger.info(
            f"Eval — acc={metrics['accuracy']:.3f} log_loss={metrics['log_loss']:.4f} "
            f"brier={metrics['brier_score']:.4f} auc={metrics['roc_auc']:.4f}"
        )
        return metrics

    def check_temporal_bias(self, df: pd.DataFrame) -> dict:
        """
        Check if model is biased toward late game situations

        Buckets plays into time periods and reports accuracy per bucket:
        - 0-25% game elapsed (early Q1)
        - 25-50% game elapsed (late Q1 / early Q2)
        - 50-75% game elapsed (Q3)
        - 75-100% game elapsed (Q4 / OT)

        A well calibrated model should have similar accuracy across all buckets

        Args:
            df: test DataFrame with pct_game_remaining column
                (optionally a precomputed 'home_wp' column to avoid re-predicting)

        Returns:
            dict mapping time bucket → accuracy, plus a bias_flag
        """
        self._check_fitted()

        if 'home_wp' in df.columns:
            probs = df['home_wp'].values
        else:
            probs = self.predict_proba_df(df)

        preds       = (probs >= 0.5).astype(int)
        y           = df[TARGET_COL].values
        pct_elapsed = 1 - df['pct_game_remaining'].values  # 0 = game start, 1 = game end

        buckets = {
            "0-25%_elapsed":   (pct_elapsed >= 0.00) & (pct_elapsed < 0.25),
            "25-50%_elapsed":  (pct_elapsed >= 0.25) & (pct_elapsed < 0.50),
            "50-75%_elapsed":  (pct_elapsed >= 0.50) & (pct_elapsed < 0.75),
            "75-100%_elapsed": (pct_elapsed >= 0.75) & (pct_elapsed <= 1.00),
        }

        results = {}
        for name, mask in buckets.items():
            results[name] = float((preds[mask] == y[mask]).mean()) if mask.sum() > 0 else None

        early = results.get("0-25%_elapsed")
        late  = results.get("75-100%_elapsed")
        bias_flag = early is not None and late is not None and (late - early) > 0.05
        if bias_flag:
            logger.warning(
                f"Temporal bias detected: early-game accuracy ({early:.3f}) is "
                f">5% lower than late-game accuracy ({late:.3f})"
            )
        results["bias_flag"] = bias_flag

        return results

    def plot_calibration_curve(self, df: pd.DataFrame, save_path: Path = None):
        """
        Plot reliability diagram (calibration curve)
        Perfect calibration = diagonal line
        Shows if model over/under-confidently predicts probabilities

        Args:
            df:        test DataFrame
            save_path: optional path to save the plot
        """
        self._check_fitted()

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError as e:
            raise ImportError(
                "matplotlib is required for plot_calibration_curve() but is not installed. "
                "Run: pip install matplotlib"
            ) from e

        df = self.validate_features(df)
        probs = self.predict_proba_df(df)
        y     = df[TARGET_COL].values

        prob_true, prob_pred = calibration_curve(y, probs, n_bins=10, strategy='uniform')

        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot([0, 1], [0, 1], linestyle='--', color='gray', label='Perfect calibration')
        ax.plot(prob_pred, prob_true, marker='o', label='Model')
        ax.set_xlabel("Predicted win probability")
        ax.set_ylabel("Observed win frequency")
        ax.set_title("Win Probability Calibration Curve")
        ax.legend()

        save_path = Path(save_path) if save_path else (MODEL_DIR / "calibration_curve.png")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        logger.info(f"Saved calibration curve to {save_path}")
