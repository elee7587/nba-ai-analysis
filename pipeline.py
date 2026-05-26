import sys
from datetime import datetime
from data.processors.game_processor import GameProcessor
from data.processors.season_stats_processor import SeasonStatsProcessor
from loguru import logger

def run(date: str):
    logger.info(f"Starting pipeline for {date}")
    
    # 1. run season stats processor
    season_stats_processor = SeasonStatsProcessor()
    season_stats_processor.process_season_stats()
    
    # 2. run game processor
    game_processor = GameProcessor()
    game_processor.process_date(date)
    
    # 3. log summary
    logger.info(f"Pipeline completed for {date}")
    pass

if __name__ == "__main__":
    # if date argument provided use it, otherwise default to today
    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        date = datetime.now().strftime("%Y-%m-%d")

    run(date)