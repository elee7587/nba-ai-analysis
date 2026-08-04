# analysis/models/feature_engineering.py
import pandas as pd
import numpy as np
from data.storage.db import SessionLocal
from data.storage.models import PlayByPlay, GameOutcome, Game, TeamGameContext
from loguru import logger

class FeatureEngineer:
    """
    Shared feature calculations used by both LR and XGBoost models.
    All feature engineering lives here to ensure consistency between
    training and inference.
    """

    def __init__(self):
        pass

    # ── Play Level Features (for LR model) ──────────────────────

    def calculate_seconds_remaining(self, period: int, clock: str) -> int:
        """
        Convert period + clock string to total seconds remaining in game
        clock format: 'PT05M30.00S'
        """
        # Example: 'PT05M30.00S' -> 5 minutes, 30 seconds
        # calculation starts at 00:00 of the 1st quarter - there should be 48 minutes or 2880 seconds in a regulation game
        # overtime doesn't matter until you're in overtime, so we can just calculate the seconds remaining in regulation and then add overtime seconds if needed
        minutes, seconds = clock[2:-1].split('M')
        if period > 4:
            # Overtime periods are 5 minutes each
            # ex. 1st overtime with 2:30 on the clock (5-1) periods left * 5 minutes * 60 seconds + 2 minutes * 60 seconds + 30 seconds
            total_seconds_remaining = (period - 4) * 5 * 60 + int(minutes) * 60 + float(seconds)
        else:
            # ex. 1st quarter with 10:50 on the clock (4-1) periods left * 12 minutes * 60 seconds + 10 minutes * 60 seconds + 50 seconds
            total_seconds_remaining = (4 - period) * 12 * 60 + int(minutes) * 60 + float(seconds)
        return total_seconds_remaining

    def calculate_pct_game_remaining(self, seconds_remaining: int, period: int) -> float:
        """
        Normalize seconds remaining to 0-1 scale
        0 = game over, 1 = game just started
        """
        # Assuming a regulation game has 2880 seconds (48 minutes * 60)
        if period <= 4:
            total_seconds = 2880  # regulation
        else:
            # add 5 minutes per OT period
            total_seconds = 2880 + (period - 4) * 300
        
        seconds_remaining = max(0, seconds_remaining)
        return seconds_remaining / total_seconds

    def calculate_margin_x_pct(self, score_margin: int, pct_remaining: float) -> float:
        """
        Interaction term: score margin weighted by time remaining
        Key feature for WP model — same margin means different things at different times
        """
        # consider using a non-linear transformation of score_margin and pct_remaining to capture diminishing returns
        # also we don't want the last play of the game to completely dominate the model so we can use a log transformation or a sigmoid function to scale the margin by time remaining
        # TODO: experiment with different transformations and see which one gives the best performance on the validation set
        margin_x_pct = score_margin * pct_remaining
        return margin_x_pct

    def calculate_score_margin_squared(self, score_margin: int) -> float:
        """
        Non-linear margin effect
        Captures that going from +2 to +4 is more impactful than +20 to +22
        """
        score_margin_squared = score_margin ** 2
        return score_margin_squared

    def calculate_total_points(self, home_score: int, away_score: int) -> int:
        """
        Total points scored so far — pace context
        High scoring games are more variable than low scoring games
        """
        total_points = home_score + away_score
        return total_points
    
    def build_play_features(self, play: dict) -> dict:
        period       = play.get('period', 1)
        clock        = play.get('clock', 'PT00M00.00S')
        home_score   = play.get('home_score', 0) or 0
        away_score   = play.get('away_score', 0) or 0
        score_margin = play.get('score_margin', 0) or 0

        seconds_remaining = self.calculate_seconds_remaining(period, clock)
        pct_remaining     = self.calculate_pct_game_remaining(seconds_remaining, period)

        return {
            'score_margin':      score_margin,
            'seconds_remaining': seconds_remaining,
            'pct_game_remaining': pct_remaining,
            'period':            period,
            'margin_x_pct':      self.calculate_margin_x_pct(score_margin, pct_remaining),
            'score_margin_sq':   self.calculate_score_margin_squared(score_margin),
            'is_overtime':       1 if period > 4 else 0,
            'total_points':      self.calculate_total_points(home_score, away_score)
        }

    def build_play_features_df(self, game_id: str) -> pd.DataFrame:
        """
        Build features for all plays in a game
        Used during training and batch inference
        Output: DataFrame with all features + home_won label
        """
        pass

    # ── Game Level Features (for XGBoost model) ─────────────────

    def calculate_win_streak(self, team_id: str, game_date: str, season: str) -> int:
        """
        Current win/loss streak for a team going into a game
        Positive = win streak, negative = loss streak
        e.g. +5 means won last 5, -3 means lost last 3
        """
        pass

    def calculate_last_n_record(self, team_id: str, game_date: str, n: int = 10) -> dict:
        """
        Win/loss record over last N games
        Returns: {"wins": X, "losses": Y}
        """
        pass

    def calculate_days_since_last_game(self, team_id: str, game_date: str) -> int:
        """
        Rest days between games
        1 = back to back, 2 = one day rest, etc.
        """
        pass

    def calculate_season_win_pct(self, team_id: str, game_date: str, season: str) -> float:
        """
        Overall win percentage for the season up to this game
        """
        pass

    def get_previous_season_context(self, team_id: str, season: str) -> dict:
        """
        Pull previous season stats for bootstrap
        Used when current season history < 10 games
        Returns: {"prev_win_pct": X, "prev_net_rating": Y}
        """
        pass

    def build_game_context_features(self, game_id: str, team_id: str) -> dict:
        """
        Build all pre-game context features for XGBoost model
        Input: game_id and team_id
        Output: feature dict ready for model.predict()
        """
        pass

    def build_game_context_df(self, season: str) -> pd.DataFrame:
        """
        Build context features for all games in a season
        Used during training
        Output: DataFrame with all features + home_won label
        """
        pass