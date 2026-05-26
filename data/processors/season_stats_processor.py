from data.collectors.season_stats_collector import SeasonStatsCollector
from datetime import datetime
from data.storage.db import SessionLocal
from data.storage.models import SeasonTeamStats, SeasonPlayerStats
from loguru import logger

class SeasonStatsProcessor:

    def __init__(self):
        self.season_stats_collector = SeasonStatsCollector()

    def get_current_season(self) -> str:
        today = datetime.today()
        if today.month >= 10:
            return f"{today.year}-{str(today.year + 1)[-2:]}"
        else:
            return f"{today.year - 1}-{str(today.year)[-2:]}"

    def process_season_stats(self):
        season  = self.get_current_season()
        session = SessionLocal()

        # check cache
        existing = session.query(SeasonTeamStats).filter_by(season=season).first()
        if existing and existing.last_updated.date() == datetime.today().date():
            logger.info(f"Season stats for {season} are up to date, skipping.")
            session.close()
            return

        try:
            season_stats = self.season_stats_collector.get_season_stats(szn=season)
            team_stats   = season_stats["team_stats"]
            player_stats = season_stats["player_stats"]

            # store team stats
            for _, row in team_stats.iterrows():
                session.merge(SeasonTeamStats(
                    season          = season,
                    team_id         = str(row['TEAM_ID']),
                    team_name       = row['TEAM_NAME'],
                    gp              = int(row['GP']),
                    w_pct           = float(row['W_PCT']),
                    pts             = float(row['PTS']),
                    pts_rank        = int(row['PTS_RANK']),
                    ast             = float(row['AST']),
                    ast_rank        = int(row['AST_RANK']),
                    reb             = float(row['REB']),
                    reb_rank        = int(row['REB_RANK']),
                    tov             = float(row['TOV']),
                    tov_rank        = int(row['TOV_RANK']),
                    fg_pct          = float(row['FG_PCT']),
                    fg_pct_rank     = int(row['FG_PCT_RANK']),
                    stl             = float(row['STL']),
                    stl_rank        = int(row['STL_RANK']),
                    blk             = float(row['BLK']),
                    blk_rank        = int(row['BLK_RANK']),
                    plus_minus      = float(row['PLUS_MINUS']),
                    plus_minus_rank = int(row['PLUS_MINUS_RANK']),
                    last_updated    = datetime.utcnow()
                ))
            session.commit()
            logger.info(f"Stored team season stats for {season}")

            # store player stats
            for _, row in player_stats.iterrows():
                session.merge(SeasonPlayerStats(
                    season            = season,
                    player_id         = str(row['PLAYER_ID']),
                    player_name       = row['PLAYER_NAME'],
                    team_id           = str(row['TEAM_ID']),
                    team_abbreviation = row['TEAM_ABBREVIATION'],
                    gp                = int(row['GP']),
                    pts               = float(row['PTS']),
                    pts_rank          = int(row['PTS_RANK']),
                    ast               = float(row['AST']),
                    ast_rank          = int(row['AST_RANK']),
                    reb               = float(row['REB']),
                    reb_rank          = int(row['REB_RANK']),
                    stl               = float(row['STL']),
                    stl_rank          = int(row['STL_RANK']),
                    blk               = float(row['BLK']),
                    blk_rank          = int(row['BLK_RANK']),
                    tov               = float(row['TOV']),
                    tov_rank          = int(row['TOV_RANK']),
                    fg_pct            = float(row['FG_PCT']),
                    fg_pct_rank       = int(row['FG_PCT_RANK']),
                    plus_minus        = float(row['PLUS_MINUS']),
                    plus_minus_rank   = int(row['PLUS_MINUS_RANK']),
                    dd2               = int(row['DD2']),
                    td3               = int(row['TD3']),
                    last_updated      = datetime.utcnow()
                ))
            session.commit()
            logger.info(f"Stored player season stats for {season}")

        except Exception as e:
            session.rollback()
            logger.error(f"Error storing season stats for {season}: {e}")
        finally:
            session.close()