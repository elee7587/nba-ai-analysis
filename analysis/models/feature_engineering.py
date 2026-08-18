# analysis/models/feature_engineering.py
import pandas as pd
import numpy as np
from sqlalchemy import func, case, and_
from data.storage.db import SessionLocal
from data.storage.models import PlayByPlay, GameOutcome, Game, SeasonTeamStats
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
        minutes, seconds = clock[2:-1].split('M')
        if period > 4:
            total_seconds_remaining = (period - 4) * 5 * 60 + int(minutes) * 60 + float(seconds)
        else:
            total_seconds_remaining = (4 - period) * 12 * 60 + int(minutes) * 60 + float(seconds)
        return int(total_seconds_remaining)

    def calculate_pct_game_remaining(self, seconds_remaining: int, period: int) -> float:
        """
        Normalize seconds remaining to 0-1 scale
        0 = game over, 1 = game just started
        """
        if period <= 4:
            total_seconds = 2880
        else:
            total_seconds = 2880 + (period - 4) * 300

        seconds_remaining = max(0, seconds_remaining)
        return seconds_remaining / total_seconds

    def calculate_margin_x_pct(self, score_margin: int, pct_remaining: float) -> float:
        """
        Interaction term: score margin weighted by time remaining
        Key feature for WP model — same margin means different things at different times
        """
        return score_margin * pct_remaining

    def calculate_score_margin_squared(self, score_margin: int) -> float:
        """
        Non-linear margin effect
        Captures that going from +2 to +4 is more impactful than +20 to +22
        """
        return float(score_margin ** 2)

    def calculate_total_points(self, home_score: int, away_score: int) -> int:
        """
        Total points scored so far — pace context
        High scoring games are more variable than low scoring games
        """
        return home_score + away_score

    def _extract_points(self, event_type: str, description: str) -> int:
        """
        Extract how many points were scored on this play
        Returns 0 if no points scored
        """
        event_lower = event_type.lower() if event_type else ''
        desc_lower  = description.lower() if description else ''

        if 'free throw' in event_lower and 'miss' not in desc_lower:
            return 1
        if 'made shot' in event_lower:
            if '3pt' in desc_lower or 'three' in desc_lower or 'three-point' in desc_lower:
                return 3
            return 2
        return 0

    def extract_play_features(self, event_type: str, description: str) -> dict:
        """
        Extract play level features from event_type and description strings
        These capture WHAT happened on the play, not just the game state
        """
        event_lower = event_type.lower() if event_type else ''
        desc_lower  = description.lower() if description else ''

        return {
            'is_made_shot':         1 if event_lower == 'made shot' else 0,
            'is_missed_shot':       1 if event_lower == 'missed shot' else 0,
            'is_three_pointer':     1 if any(x in desc_lower for x in ['3pt', 'three', 'three-point']) else 0,
            'is_free_throw':        1 if 'free throw' in event_lower else 0,
            'is_turnover':          1 if event_lower == 'turnover' else 0,
            'is_rebound':           1 if 'rebound' in event_lower else 0,
            'is_offensive_rebound': 1 if 'offensive' in desc_lower and 'rebound' in desc_lower else 0,
            'is_block':             1 if event_lower in ['block', 'blocked shot'] else 0,
            'is_steal':             1 if 'steal' in desc_lower else 0,
            'points_scored_on_play': self._extract_points(event_type, description)
        }

    def build_play_features(self, play: dict) -> dict:
        """
        Build all game state features for a single play
        Used during inference to get WP for a specific moment
        Input: single play dict from play_by_play table
        Output: feature dict ready for model.predict()
        Note: momentum features are added separately via add_momentum_features()
        """
        period       = play.get('period', 1)
        clock        = play.get('clock', 'PT00M00.00S')
        home_score   = play.get('home_score', 0) or 0
        away_score   = play.get('away_score', 0) or 0
        score_margin = play.get('score_margin', 0) or 0
        event_type   = play.get('event_type', '') or ''
        description  = play.get('description', '') or ''

        try:
            seconds_remaining = self.calculate_seconds_remaining(period, clock)
        except Exception:
            seconds_remaining = 0

        pct_remaining = self.calculate_pct_game_remaining(seconds_remaining, period)

        # base game state features
        features = {
            'score_margin':       score_margin,
            'seconds_remaining':  seconds_remaining,
            'pct_game_remaining': pct_remaining,
            'period':             period,
            'margin_x_pct':       self.calculate_margin_x_pct(score_margin, pct_remaining),
            'score_margin_sq':    self.calculate_score_margin_squared(score_margin),
            'is_overtime':        1 if period > 4 else 0,
            'total_points':       self.calculate_total_points(home_score, away_score)
        }

        # play event features
        play_features = self.extract_play_features(event_type, description)
        features.update(play_features)

        return features

    def add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add momentum features that require context from previous plays
        Must be called AFTER building the base feature DataFrame
        Operates on the full game DataFrame to track sequences correctly
        """
        df = df.sort_values(['game_id', 'action_id']).copy()

        # initialize momentum columns
        df['consecutive_team_scores'] = 0
        df['consecutive_team_misses'] = 0
        df['run_size_at_play']        = 0

        for game_id, game_df in df.groupby('game_id'):
            run_team  = None
            run_size  = 0
            miss_team = None
            miss_size = 0

            for idx, row in game_df.iterrows():
                points = row['points_scored_on_play']
                team   = row.get('team', None)

                if points > 0:
                    # scoring play
                    if team == run_team:
                        run_size += points
                    else:
                        run_team = team
                        run_size = points
                    # reset miss streak
                    miss_size = 0
                    miss_team = None

                elif row['is_missed_shot'] == 1:
                    # missed shot
                    if team == miss_team:
                        miss_size += 1
                    else:
                        miss_team = team
                        miss_size = 1

                df.at[idx, 'consecutive_team_scores'] = run_size
                df.at[idx, 'consecutive_team_misses'] = miss_size
                df.at[idx, 'run_size_at_play']        = run_size

        return df

    def build_play_features_df(self, game_id: str) -> pd.DataFrame:
        """
        Build features for all plays in a game
        Used during training and batch inference
        Output: DataFrame with all features + home_won label
        """
        session = SessionLocal()
        try:
            # query outcome once — same label for every play in the game
            game_outcome = session.query(GameOutcome)\
                .filter(GameOutcome.game_id == game_id)\
                .first()

            if not game_outcome:
                logger.warning(f"No game outcome found for {game_id}")
                return pd.DataFrame()

            home_won = game_outcome.home_won

            # query all plays excluding timeouts
            plays = session.query(PlayByPlay)\
                .filter(PlayByPlay.game_id == game_id)\
                .filter(~PlayByPlay.event_type.in_(['Timeout']))\
                .order_by(PlayByPlay.action_id)\
                .all()

            # build feature rows
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
                features              = self.build_play_features(play_dict)
                features['home_won']  = home_won
                features['game_id']   = game_id
                features['action_id'] = play.action_id
                features['team']      = play.team
                rows.append(features)

            df = pd.DataFrame(rows)

            # add momentum features that require sequence context
            if not df.empty:
                df = self.add_momentum_features(df)

            logger.info(f"Built {len(rows)} play features for game {game_id}")
            return df

        except Exception as e:
            logger.error(f"Failed to build features for game {game_id}: {e}")
            raise
        finally:
            session.close()

    # ── Game Level Features (for XGBoost model) ─────────────────

    def _normalize_season(self, season: str) -> str:
        """
        Convert season format to match what's stored in DB
        "2025-26" → "22025"
        "22025"   → "22025"
        """
        if '-' in season:
            year = season.split('-')[0]
            return f"2{year}"
        return season

    def calculate_win_streak(self, team_id: str, game_date: str, season: str) -> int:
        """
        Current win/loss streak for a team going into a game
        Positive = win streak, negative = loss streak
        e.g. +5 means won last 5, -3 means lost last 3
        """
        session = SessionLocal()
        try:
            previous_games = session.query(Game, GameOutcome)\
                .join(GameOutcome, Game.game_id == GameOutcome.game_id)\
                .filter(Game.game_date < game_date)\
                .filter(Game.season == season)\
                .filter(
                    (Game.home_team == team_id) |
                    (Game.away_team == team_id)
                )\
                .order_by(Game.game_date.desc())\
                .all()

            if not previous_games:
                return 0

            streak       = 0
            first_result = None

            for game, outcome in previous_games:
                is_home = game.home_team == team_id
                won     = outcome.home_won == 1 if is_home else outcome.home_won == 0

                if first_result is None:
                    first_result = won
                    streak       = 1 if won else -1
                elif won == first_result:
                    streak = streak + 1 if won else streak - 1
                else:
                    break

            return streak

        except Exception as e:
            logger.error(f"Failed to calculate win streak for {team_id}: {e}")
            return 0
        finally:
            session.close()

    def calculate_last_n_record(self, team_id: str, game_date: str, n: int = 10) -> dict:
        """
        Win/loss record over last N games
        Returns: {"wins": X, "losses": Y}
        """
        session = SessionLocal()
        try:
            previous_games = session.query(Game, GameOutcome)\
                .join(GameOutcome, Game.game_id == GameOutcome.game_id)\
                .filter(Game.game_date < game_date)\
                .filter(
                    (Game.home_team == team_id) |
                    (Game.away_team == team_id)
                )\
                .order_by(Game.game_date.desc())\
                .limit(n)\
                .all()

            wins   = sum(1 for game, outcome in previous_games
                        if (game.home_team == team_id and outcome.home_won) or
                           (game.away_team == team_id and not outcome.home_won))
            losses = sum(1 for game, outcome in previous_games
                        if (game.home_team == team_id and not outcome.home_won) or
                           (game.away_team == team_id and outcome.home_won))

            return {"wins": wins, "losses": losses}

        except Exception as e:
            logger.error(f"Failed to calculate last {n} record for {team_id}: {e}")
            return {"wins": 0, "losses": 0}
        finally:
            session.close()

    def calculate_days_since_last_game(self, team_id: str, game_date: str) -> int:
        """
        Rest days between games
        1 = back to back, 2 = one day rest, etc.
        Returns 7 if no previous game found (start of season)
        """
        session = SessionLocal()
        try:
            last_game = session.query(Game.game_date)\
                .filter(Game.game_date < game_date)\
                .filter(
                    (Game.home_team == team_id) |
                    (Game.away_team == team_id)
                )\
                .order_by(Game.game_date.desc())\
                .limit(1)\
                .first()

            return (pd.to_datetime(game_date) - pd.to_datetime(last_game.game_date)).days \
                   if last_game else 7

        except Exception as e:
            logger.error(f"Failed to calculate days since last game for {team_id}: {e}")
            return 7
        finally:
            session.close()

    def calculate_season_win_pct(self, team_id: str, game_date: str, season: str) -> float:
        """
        Overall win percentage for the season up to this game
        """
        session = SessionLocal()
        try:
            result = session.query(
                func.count(Game.game_id),
                func.sum(
                    case(
                        (and_(Game.home_team == team_id, GameOutcome.home_won == 1), 1),
                        (and_(Game.away_team == team_id, GameOutcome.home_won == 0), 1),
                        else_=0
                    )
                )
            ).join(GameOutcome, Game.game_id == GameOutcome.game_id)\
             .filter(Game.game_date < game_date)\
             .filter(Game.season == season)\
             .filter(
                 (Game.home_team == team_id) |
                 (Game.away_team == team_id)
             )\
             .first()

            total_games, wins = result
            return float(wins / total_games) if total_games and total_games > 0 else 0.0

        except Exception as e:
            logger.error(f"Failed to calculate season win pct for {team_id}: {e}")
            return 0.0
        finally:
            session.close()

    def get_previous_season_context(self, team_id: str, season: str) -> dict:
        """
        Pull previous season stats for bootstrap
        Used when current season history < 10 games
        Handles both "22025" and "2025-26" season formats
        """
        session = SessionLocal()
        try:
            # derive previous season in "YYYY-YY" format
            if '-' in season:
                year        = int(season.split('-')[0])
                prev_season = f"{year - 1}-{str(year)[-2:]}"
            else:
                # "22025" → year=2025 → prev="2024-25"
                year        = int(season[1:])
                prev_season = f"{year - 1}-{str(year)[-2:]}"

            prev_stats = session.query(SeasonTeamStats)\
                .filter(SeasonTeamStats.team_id == team_id)\
                .filter(SeasonTeamStats.season == prev_season)\
                .first()

            if not prev_stats:
                logger.warning(f"No previous season stats for {team_id} in {prev_season}")
                return {
                    "prev_win_pct":         0.5,
                    "prev_pts_rank":        15,
                    "prev_ast_rank":        15,
                    "prev_reb_rank":        15,
                    "prev_plus_minus_rank": 15
                }

            return {
                "prev_win_pct":         prev_stats.w_pct,
                "prev_pts_rank":        prev_stats.pts_rank,
                "prev_ast_rank":        prev_stats.ast_rank,
                "prev_reb_rank":        prev_stats.reb_rank,
                "prev_plus_minus_rank": prev_stats.plus_minus_rank
            }

        except Exception as e:
            logger.error(f"Failed to get previous season context for {team_id}: {e}")
            return {
                "prev_win_pct":         0.5,
                "prev_pts_rank":        15,
                "prev_ast_rank":        15,
                "prev_reb_rank":        15,
                "prev_plus_minus_rank": 15
            }
        finally:
            session.close()

    def build_game_context_features(self, game_id: str, team_id: str) -> dict:
        """
        Build all pre-game context features for XGBoost model
        Input: game_id and team_id
        Output: feature dict ready for model.predict()
        """
        session = SessionLocal()
        try:
            game = session.query(Game)\
                .filter(Game.game_id == game_id)\
                .first()

            if not game:
                logger.warning(f"Game {game_id} not found")
                return {}

            game_date = str(game.game_date)
            season    = str(game.season)

        except Exception as e:
            logger.error(f"Failed to get game info for {game_id}: {e}")
            return {}
        finally:
            session.close()

        # call all feature methods
        win_streak  = self.calculate_win_streak(team_id, game_date, season)
        last_10     = self.calculate_last_n_record(team_id, game_date, n=10)
        days_since  = self.calculate_days_since_last_game(team_id, game_date)
        season_pct  = self.calculate_season_win_pct(team_id, game_date, season)
        prev_season = self.get_previous_season_context(team_id, season)

        return {
            "win_streak":           win_streak,
            "last_10_wins":         last_10["wins"],
            "last_10_losses":       last_10["losses"],
            "last_10_win_pct":      last_10["wins"] / 10 if (last_10["wins"] + last_10["losses"]) > 0 else 0.5,
            "days_since_last":      days_since,
            "is_back_to_back":      1 if days_since <= 1 else 0,
            "season_win_pct":       season_pct,
            "prev_win_pct":         prev_season.get("prev_win_pct", 0.5),
            "prev_pts_rank":        prev_season.get("prev_pts_rank", 15),
            "prev_ast_rank":        prev_season.get("prev_ast_rank", 15),
            "prev_reb_rank":        prev_season.get("prev_reb_rank", 15),
            "prev_plus_minus_rank": prev_season.get("prev_plus_minus_rank", 15),
        }

    def build_game_context_df(self, season: str) -> pd.DataFrame:
        """
        Build context features for all games in a season
        Used during training
        Output: DataFrame with all features + home_won label
        """
        db_season = self._normalize_season(season)
        session   = SessionLocal()
        try:
            games = session.query(Game, GameOutcome)\
                .join(GameOutcome, Game.game_id == GameOutcome.game_id)\
                .filter(Game.season == db_season)\
                .order_by(Game.game_date.asc())\
                .all()

            logger.info(f"Building context features for {len(games)} games in {season}")

        except Exception as e:
            logger.error(f"Failed to query games for season {season}: {e}")
            return pd.DataFrame()
        finally:
            session.close()

        rows = []
        for i, (game, outcome) in enumerate(games):
            try:
                home_features = self.build_game_context_features(game.game_id, game.home_team)
                away_features = self.build_game_context_features(game.game_id, game.away_team)

                home_prefixed = {f"home_{k}": v for k, v in home_features.items()}
                away_prefixed = {f"away_{k}": v for k, v in away_features.items()}

                row = {
                    "game_id":  game.game_id,
                    "home_won": outcome.home_won,
                    **home_prefixed,
                    **away_prefixed
                }
                rows.append(row)

                if (i + 1) % 25 == 0:
                    logger.info(f"Processed {i + 1}/{len(games)} games")

            except Exception as e:
                logger.error(f"Failed to build context for game {game.game_id}: {e}")
                continue

        df = pd.DataFrame(rows)
        logger.info(f"Built context DataFrame with shape {df.shape}")
        return df