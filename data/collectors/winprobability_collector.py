##############################################################
#      TRY AGAIN LATER, API IS CURRENTLY UNRELIABLE          #
##############################################################
from nba_api.stats.endpoints import winprobabilitypbp
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class WinProbabilityCollector:

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_win_probability_by_game_id(self, game_id:str) -> dict:
        """
        Fetches win probability play-by-play data for a specific game_id
        """
        time.sleep(REQUEST_DELAY)  # respect rate limits
        win_prob_dict = {}
        try:
            winprob = winprobabilitypbp.WinProbabilityPBP(
                game_id=game_id,
                run_type=0,  # 0 for regular season, 1 for pre season 
                timeout=REQUEST_TIMEOUT
            )
            win_prob_dict["game_info"] = winprob.game_info.get_data_frame()
            win_prob_dict["win_prob"] = winprob.win_prob_pbp.get_data_frame()
            
            logger.info(f"Successfully fetched win probability play-by-play for game {game_id}")
            return win_prob_dict
        except Exception as e:
            logger.error(f"Failed to fetch win probability play-by-play for {game_id}: {e}")
            raise
