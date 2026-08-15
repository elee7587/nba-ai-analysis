# analysis/models/feature_engineering.py
from operator import and_

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

    def _normalize_season(self, season: str) -> str:
        """
        Convert season format to match what's stored in DB
        "2025-26" → "22025"
        "22025"   → "22025" (already correct)
        """
        if '-' in season:
            year = season.split('-')[0]
            return f"2{year}"
        return season

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
        return int(total_seconds_remaining)

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
        # sigmoid scaling — dampens extreme margins
        import scipy.special
        margin_x_pct = scipy.special.expit(score_margin * 0.1) * pct_remaining
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

        try:
            seconds_remaining = self.calculate_seconds_remaining(period, clock)
        except Exception:
            # fallback if clock is malformed
            seconds_remaining = 0

        pct_remaining = self.calculate_pct_game_remaining(seconds_remaining, period)

        return {
            'score_margin':       score_margin,
            'seconds_remaining':  seconds_remaining,
            'pct_game_remaining': pct_remaining,
            'period':             period,
            'margin_x_pct':       self.calculate_margin_x_pct(score_margin, pct_remaining),
            'score_margin_sq':    self.calculate_score_margin_squared(score_margin),
            'is_overtime':        1 if period > 4 else 0,
            'total_points':       self.calculate_total_points(home_score, away_score)
        }

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

            # query all plays
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
                }
                features             = self.build_play_features(play_dict)
                features['home_won'] = home_won
                features['game_id']  = game_id
                features['action_id'] = play.action_id
                rows.append(features)

            logger.info(f"Built {len(rows)} play features for game {game_id}")
            return pd.DataFrame(rows)

        except Exception as e:
            logger.error(f"Failed to build features for game {game_id}: {e}")
            raise
        finally:
            session.close()
        

    # ── Game Level Features (for XGBoost model) ─────────────────

    def calculate_win_streak(self, team_id: str, game_date: str, season: str) -> int:
        session = SessionLocal()
        try:
            # get previous games for this team before game_date
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

            streak = 0
            for game, outcome in previous_games:
                # determine if this team won
                if game.home_team == team_id:
                    won = outcome.home_won == 1
                else:
                    won = outcome.home_won == 0  # away team wins when home_won = 0

                # first game sets the direction
                if streak == 0:
                    streak = 1 if won else -1
                elif won and streak > 0:
                    streak += 1  # win streak continues
                elif not won and streak < 0:
                    streak -= 1  # loss streak continues
                else:
                    break  # streak broken

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
            # get previous games for this team before game_date
            """
            SELECT g.game_id, g.game_date, g.home_team, g.away_team, go.home_won
            FROM games g
            JOIN game_outcomes go On g.game_id = go.game_id
            WHERE g.game_date < :game_date
            AND (g.home_team = :team_id OR g.away_team = :team_id)

            """
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
            wins = sum(1 for game, outcome in previous_games if (game.home_team == team_id and outcome.home_won) or (game.away_team == team_id and not outcome.home_won))
            losses = sum(1 for game, outcome in previous_games if (game.home_team == team_id and not outcome.home_won) or (game.away_team == team_id and outcome.home_won))
            return {
                "wins": wins,
                "losses": losses
            }
        except Exception as e:
            logger.error(f"Failed to calculate last {n} games record for {team_id}: {e}")
            return {"wins": 0, "losses": 0}
        finally:
            session.close()

    def calculate_days_since_last_game(self, team_id: str, game_date: str) -> int:
        """
        Rest days between games
        1 = back to back, 2 = one day rest, etc.
        """
        session = SessionLocal()
        try:
            """
            SELECT g.game_date
            FROM games g
            WHERE g.game_date < :game_date
            AND (g.home_team = :team_id OR g.away_team = :team_id)
            ORDER BY g.game_date DESC
            LIMIT 1
            """
            last_game = session.query(Game.game_date)\
                .filter(Game.game_date < game_date)\
                .filter(
                    (Game.home_team == team_id) |
                    (Game.away_team == team_id)
                )\
                .order_by(Game.game_date.desc())\
                .limit(1)\
                .first()
            days_since_last_game = (pd.to_datetime(game_date) - pd.to_datetime(last_game.game_date)).days if last_game else 7
            return days_since_last_game
        except Exception as e:
            logger.error(f"Failed to calculate days since last game for {team_id}: {e}")
            return 0
        finally:
            session.close()

    def calculate_season_win_pct(self, team_id: str, game_date: str, season: str) -> float:
        """
        Overall win percentage for the season up to this game
        """
        session = SessionLocal()
        try:
            """
            SELECT COUNT(*) as total_games,
            SUM(CASE WHEN (g.home_team = :team_id AND go.home_won = 1) OR (g.away_team = :team_id AND go.home_won = 0) THEN 1 ELSE 0 END) as wins
            FROM games g
            JOIN game_outcomes go on g.game_id = go.game_id
            WHERE g.game_date < :game_date
            AND g.season = :season
            AND (g.home_team = :team_id OR g.away_team = :team_id)
            """
            total_games, wins = session.query(
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
            return wins / total_games if total_games > 0 else 0.0
        except Exception as e:
            logger.error(f"Failed to calculate season win pct for {team_id}: {e}")
            return 0.0
        finally:
            session.close()

    def get_previous_season_context(self, team_id: str, season: str) -> dict:
        # handle both formats
        if '-' in season:
            # "2025-26" format
            year        = int(season.split('-')[0])
            prev_season = f"{year - 1}-{str(year)[-2:]}"
        else:
            # "22025" format → previous is "2024-25"
            year        = int(season[1:])  # strip leading "2" → 2025
            prev_season = f"{year - 1}-{str(year)[-2:]}"  # → "2024-25"
        
        logger.info(f"Looking up previous season: {prev_season} for team {team_id}")
        session = SessionLocal()
        try:
            prev_stats = session.query(SeasonTeamStats)\
                .filter(SeasonTeamStats.team_id == team_id)\
                .filter(SeasonTeamStats.season == prev_season)\
                .first()
            return {
                "prev_win_pct": prev_stats.win_pct if prev_stats else 0.5,
                "prev_pts_rank": prev_stats.pts_rank if prev_stats else 15,
                "prev_ast_rank": prev_stats.ast_rank if prev_stats else 15,
                "prev_reb_rank": prev_stats.reb_rank if prev_stats else 15,
                "prev_plus_minus_rank": prev_stats.plus_minus_rank if prev_stats else 15,
            }
        except Exception as e:
            logger.error(f"Failed to get previous season context for {team_id}: {e}")
            return {
                "prev_win_pct": 0.5,
                "prev_pts_rank": 15,
                "prev_ast_rank": 15,
                "prev_reb_rank": 15,
                "prev_plus_minus_rank": 15,
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
            # get game date and season for this game
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
        win_streak   = self.calculate_win_streak(team_id, game_date, season)
        last_10      = self.calculate_last_n_record(team_id, game_date, n=10)
        days_since   = self.calculate_days_since_last_game(team_id, game_date)
        season_pct   = self.calculate_season_win_pct(team_id, game_date, season)
        prev_season  = self.get_previous_season_context(team_id, season)

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
        db_season = self._normalize_season(season)
        session = SessionLocal()
        try:
            # get all games for this season with outcomes
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
                # build features for home team
                home_features = self.build_game_context_features(
                    game.game_id, game.home_team
                )
                # build features for away team
                away_features = self.build_game_context_features(
                    game.game_id, game.away_team
                )

                # prefix home and away
                home_prefixed = {f"home_{k}": v for k, v in home_features.items()}
                away_prefixed = {f"away_{k}": v for k, v in away_features.items()}

                # combine into one row
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