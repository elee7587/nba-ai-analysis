from data.collectors.standings_collector import StandingsCollector
from data.storage.db import SessionLocal
from data.storage.models import TeamStandingsSnapshot
from datetime import datetime
from loguru import logger


def _safe_float(value, default=0.0):
    """nba.com's classic standings feed has historically returned '-' for
    the conference/division leader's games-back instead of 0 — defend
    against that (and None/empty) rather than letting float() throw."""
    if value in (None, '', '-'):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class StandingsProcessor:

    def __init__(self):
        self.standings_collector = StandingsCollector()

    def capture_standings_snapshot(self, snapshot_date: str, season: str):
        """
        League-wide, once per day — snapshot_date is the caller's chosen
        date (typically the daily pipeline's `date`), season is passed in
        explicitly (see pipeline.py) rather than re-derived here, so there's
        only one place (SeasonStatsProcessor.get_current_season()) computing
        the October-rollover season-string logic.

        NOTE: this always captures the CURRENT live standings (see
        StandingsCollector.get_standings) — it should only ever be called
        with snapshot_date == today, never for a past date. See pipeline.py
        and bulk_pipeline.py for why backfilling this is intentionally not
        supported.
        """
        df = self.standings_collector.get_standings(season)
        session = SessionLocal()
        try:
            for _, row in df.iterrows():
                session.merge(TeamStandingsSnapshot(
                    snapshot_date=snapshot_date,
                    team_id=str(row['TeamID']),
                    season=season,
                    conference=row['Conference'],
                    division=row['Division'],
                    wins=int(row['WINS']),
                    losses=int(row['LOSSES']),
                    win_pct=_safe_float(row['WinPCT']),
                    conference_rank=int(row['PlayoffRank']),
                    division_rank=int(row['DivisionRank']),
                    conference_games_back=_safe_float(row['ConferenceGamesBack']),
                    division_games_back=_safe_float(row['DivisionGamesBack']),
                    conference_record=row['ConferenceRecord'],
                    division_record=row['DivisionRecord'],
                    home_record=row['HOME'],
                    road_record=row['ROAD'],
                    last_10=row['L10'],
                    current_streak=row['strCurrentStreak'],
                    created_at=datetime.utcnow(),
                ))
            session.commit()
            logger.info(f"Stored standings snapshot for {snapshot_date} ({len(df)} teams)")
        except Exception as e:
            session.rollback()
            logger.error(f"Error storing standings snapshot for {snapshot_date}: {e}")
            raise
        finally:
            session.close()
