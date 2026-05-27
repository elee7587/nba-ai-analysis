from data.collectors.game_collector import GameCollector
from data.collectors.boxscore_collector import BoxScoreCollector
from data.collectors.playbyplay_collector import PlayByPlayCollector
from data.storage.db import SessionLocal
from data.storage.models import Game, BoxScore_Player, BoxScore_Team, AdvancedBoxScorePlayer, AdvancedBoxScoreTeam, PlayByPlay
from loguru import logger
from datetime import datetime

class GameProcessor:

    def __init__(self):
        self.game_collector     = GameCollector()
        self.boxscore_collector = BoxScoreCollector()
        self.pbp_collector      = PlayByPlayCollector()

    def process_date(self, date: str):
        games = self.game_collector.get_games_by_date(date)
        if not games:
            logger.info(f"No games found for {date}, skipping.")
            return
        for game in games:
            session = SessionLocal()
            try:
                game_record = Game(
                    game_id    = game['game_id'],
                    season     = game['season'],
                    game_date = datetime.strptime(game['game_date'].replace('Z', ''), "%Y-%m-%dT%H:%M:%S"),
                    home_team  = game['home_team'],
                    away_team  = game['away_team'],
                    home_score = game['home_score'],
                    away_score = game['away_score']
                )
                session.merge(game_record)
                session.commit()
                logger.info(f"Stored game {game['game_id']} for date {date}")
                self.process_boxscore(game['game_id'])
                self.process_play_by_play(game['game_id'])
            except Exception as e:
                session.rollback()
                logger.error(f"Error processing game {game['game_id']}: {e}")
            finally:
                session.close()

    def process_boxscore(self, game_id: str):
        boxscore_data = self.boxscore_collector.get_boxscore_by_game_id(game_id)
        session = SessionLocal()
        try:
            # store player stats
            for _, row in boxscore_data["player_stats"].iterrows():
                session.merge(BoxScore_Player(
                    game_id        = game_id,
                    team_id        = str(int(row['teamId'])),
                    team_abbrev    = row['teamTricode'],
                    team_city      = row['teamCity'],
                    player_id      = str(int(row['personId'])),
                    player_name    = row['firstName'] + ' ' + row['familyName'],
                    nickname       = row['nameI'],
                    start_position = row['position'],
                    comment        = row['comment'],
                    minutes        = row['minutes'],
                    fgm            = row['fieldGoalsMade'],
                    fga            = row['fieldGoalsAttempted'],
                    fg_pct         = row['fieldGoalsPercentage'],
                    fg_3m          = row['threePointersMade'],
                    fg_3a          = row['threePointersAttempted'],
                    fg_3_pct       = row['threePointersPercentage'],
                    ftm            = row['freeThrowsMade'],
                    fta            = row['freeThrowsAttempted'],
                    ft_pct         = row['freeThrowsPercentage'],
                    oreb           = row['reboundsOffensive'],
                    dreb           = row['reboundsDefensive'],
                    reb            = row['reboundsTotal'],
                    ast            = row['assists'],
                    stl            = row['steals'],
                    blk            = row['blocks'],
                    tov            = row['turnovers'],
                    pf             = row['foulsPersonal'],
                    pts            = row['points'],
                    plus_minus     = row['plusMinusPoints']
                ))
            session.commit()

            # store team stats
            for _, row in boxscore_data["team_stats"].iterrows():
                session.merge(BoxScore_Team(
                    game_id   = game_id,
                    team_id   = str(int(row['teamId'])),
                    team_abbrev = row['teamTricode'],
                    team_city = row['teamCity'],
                    minutes   = row['minutes'],
                    fgm       = row['fieldGoalsMade'],
                    fga       = row['fieldGoalsAttempted'],
                    fg_pct    = row['fieldGoalsPercentage'],
                    fg_3m     = row['threePointersMade'],
                    fg_3a     = row['threePointersAttempted'],
                    fg_3_pct  = row['threePointersPercentage'],
                    ftm       = row['freeThrowsMade'],
                    fta       = row['freeThrowsAttempted'],
                    ft_pct    = row['freeThrowsPercentage'],
                    oreb      = row['reboundsOffensive'],
                    dreb      = row['reboundsDefensive'],
                    reb       = row['reboundsTotal'],
                    ast       = row['assists'],
                    stl       = row['steals'],
                    blk       = row['blocks'],
                    tov       = row['turnovers'],
                    pf        = row['foulsPersonal'],
                    pts       = row['points'],
                    plus_minus = row['plusMinusPoints']
                ))
            session.commit()

            # store advanced player stats
            for _, row in boxscore_data["advanced_player_stats"].iterrows():
                session.merge(AdvancedBoxScorePlayer(
                    game_id                    = game_id,
                    team_id                    = str(int(row['teamId'])),
                    team_tricode               = row['teamTricode'],
                    player_id                  = str(int(row['personId'])),
                    player_name                = row['firstName'] + ' ' + row['familyName'],
                    minutes                    = row['minutes'],
                    estimated_offensive_rating = row['estimatedOffensiveRating'],
                    offensive_rating           = row['offensiveRating'],
                    estimated_defensive_rating = row['estimatedDefensiveRating'],
                    defensive_rating           = row['defensiveRating'],
                    estimated_net_rating       = row['estimatedNetRating'],
                    net_rating                 = row['netRating'],
                    assist_percentage          = row['assistPercentage'],
                    assist_to_turnover         = row['assistToTurnover'],
                    assist_ratio               = row['assistRatio'],
                    offensive_rebound_pct      = row['offensiveReboundPercentage'],
                    defensive_rebound_pct      = row['defensiveReboundPercentage'],
                    rebound_percentage         = row['reboundPercentage'],
                    turnover_ratio             = row['turnoverRatio'],
                    effective_fg_pct           = row['effectiveFieldGoalPercentage'],
                    true_shooting_pct          = row['trueShootingPercentage'],
                    usage_pct                  = row['usagePercentage'],
                    estimated_usage_pct        = row['estimatedUsagePercentage'],
                    estimated_pace             = row['estimatedPace'],
                    pace                       = row['pace'],
                    pace_per40                 = row['pacePer40'],
                    possessions                = row['possessions'],
                    pie                        = row['PIE']
                ))
            session.commit()

            # store advanced team stats
            for _, row in boxscore_data["advanced_team_stats"].iterrows():
                session.merge(AdvancedBoxScoreTeam(
                    game_id                    = game_id,
                    team_id                    = str(int(row['teamId'])),
                    team_tricode               = row['teamTricode'],
                    minutes                    = row['minutes'],
                    estimated_offensive_rating = row['estimatedOffensiveRating'],
                    offensive_rating           = row['offensiveRating'],
                    estimated_defensive_rating = row['estimatedDefensiveRating'],
                    defensive_rating           = row['defensiveRating'],
                    estimated_net_rating       = row['estimatedNetRating'],
                    net_rating                 = row['netRating'],
                    assist_percentage          = row['assistPercentage'],
                    assist_to_turnover         = row['assistToTurnover'],
                    assist_ratio               = row['assistRatio'],
                    offensive_rebound_pct      = row['offensiveReboundPercentage'],
                    defensive_rebound_pct      = row['defensiveReboundPercentage'],
                    rebound_percentage         = row['reboundPercentage'],
                    turnover_ratio             = row['turnoverRatio'],
                    effective_fg_pct           = row['effectiveFieldGoalPercentage'],
                    true_shooting_pct          = row['trueShootingPercentage'],
                    usage_percentage           = row['usagePercentage'],
                    estimated_usage_pct        = row['estimatedUsagePercentage'],
                    estimated_pace             = row['estimatedPace'],
                    pace                       = row['pace'],
                    pace_per40                 = row['pacePer40'],
                    possessions                = row['possessions'],
                    pie                        = row['PIE']
                ))
            session.commit()
            logger.info(f"Stored boxscore for game {game_id}")

        except Exception as e:
            session.rollback()
            logger.error(f"Error processing boxscore for {game_id}: {e}")
        finally:
            session.close()

    def process_play_by_play(self, game_id: str):
        pbp_data = self.pbp_collector.get_play_by_play_by_game_id(game_id)
        session = SessionLocal()
        try:
            for _, row in pbp_data.iterrows():
                session.merge(PlayByPlay(
                    game_id     = game_id,
                    action_id = row['actionId'],
                    period      = row['period'],
                    clock       = row['clock'],
                    home_score   = int(row['scoreHome']) if row['scoreHome'] != '' else None,
                    away_score   = int(row['scoreAway']) if row['scoreAway'] != '' else None,
                    score_margin = int(row['scoreHome']) - int(row['scoreAway']) if row['scoreHome'] and row['scoreAway'] else None,
                    event_type  = row['actionType'],
                    description = row['description'],
                    player_id   = row['personId'],
                    player_name = row['playerName'],
                    team        = row['teamTricode']
                ))
            session.commit()
            logger.info(f"Stored play by play for game {game_id}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error processing play by play for {game_id}: {e}")
        finally:
            session.close()