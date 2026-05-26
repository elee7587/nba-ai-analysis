from nba_api.stats.endpoints import playbyplayv3
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class PlayByPlayCollector:

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_play_by_play_by_game_id(self, game_id:str) -> dict:
        """
        Fetches play-by-play data for a specific game_id
        """
        time.sleep(REQUEST_DELAY)  # respect rate limits
        playbyplay_dict = {}
        try:
            playbyplay = playbyplayv3.PlayByPlayV3(
                game_id=game_id, 
                timeout=REQUEST_TIMEOUT
            )
            playbyplay_dict = playbyplay.play_by_play.get_data_frame()
            logger.info(f"Successfully fetched play-by-play for game {game_id}")
        except Exception as e:
            logger.error(f"Failed to fetch play-by-play for {game_id}: {e}")
            raise
        return playbyplay_dict