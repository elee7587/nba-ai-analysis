from nba_api.stats.endpoints import boxscoretraditionalv3
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class BoxScoreCollector:

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_boxscore_by_game_id(self, game_id:str) -> dict:
        """
        Fetches boxscore data for a specific game_id
        """
        time.sleep(REQUEST_DELAY)  # respect rate limits
        boxscore_dict = {}
        try:
            boxscore = boxscoretraditionalv3.BoxScoreTraditionalV3(
                game_id=game_id, 
                timeout=REQUEST_TIMEOUT
            )
            player_stats = boxscore.player_stats.get_data_frame()
            team_stats = boxscore.team_stats.get_data_frame()
            boxscore_dict = {
                "player_stats": player_stats,
                "team_stats": team_stats
            }
            logger.info(f"Successfully fetched boxscore for game {game_id}")
        except Exception as e:
            logger.error(f"Failed to fetch boxscore for {game_id}: {e}")
            raise
        return boxscore_dict