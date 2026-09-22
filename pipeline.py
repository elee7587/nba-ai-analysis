import sys
from datetime import datetime
from data.processors.game_processor import GameProcessor
from data.processors.season_stats_processor import SeasonStatsProcessor
from data.processors.standings_processor import StandingsProcessor
from loguru import logger

def run(date: str):
    logger.info(f"Starting pipeline for {date}")

    # 1. run season stats processor
    season_stats_processor = SeasonStatsProcessor()
    season_stats_processor.process_season_stats()

    # 2. run game processor
    game_processor = GameProcessor()
    game_processor.process_date(date)

    # 3. capture today's league-wide standings snapshot (once per day, not
    #    per-game). NOTE: this assumes `date` is only run after all of that
    #    date's games are final (e.g. a next-morning batch run) — nba_api's
    #    standings endpoint has no as-of-date support, so it always returns
    #    *current* standings; running this mid-evening while games are still
    #    live would silently capture a partially-updated snapshot as that
    #    day's "after" state. See data/collectors/standings_collector.py.
    standings_processor = StandingsProcessor()
    standings_processor.capture_standings_snapshot(
        snapshot_date=date, season=season_stats_processor.get_current_season()
    )

    # 4. log summary
    logger.info(f"Pipeline completed for {date}")

if __name__ == "__main__":
    # if date argument provided use it, otherwise default to today
    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        date = datetime.now().strftime("%Y-%m-%d")

    run(date)