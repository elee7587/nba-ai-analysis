from nba_api.stats.endpoints import leaguedashteamstats
from nba_api.stats.endpoints import leaguedashplayerstats
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class SeasonStatsCollector:

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_season_stats(self, szn:str) -> dict:
        """
        Fetches season stats for teams and playerse for a specific season
        """
        season_stats_dict = {}
        time.sleep(REQUEST_DELAY)  # respect rate limits
        try:
            team_stats = leaguedashteamstats.LeagueDashTeamStats(
                season_type_all_star="Regular Season",
                per_mode_detailed="PerGame",
                season=szn,
                timeout=REQUEST_TIMEOUT
            )
            time.sleep(REQUEST_DELAY)  # respect rate limits

            player_stats = leaguedashplayerstats.LeagueDashPlayerStats(
                season_type_all_star="Regular Season",
                per_mode_detailed="PerGame",
                season=szn,
                timeout=REQUEST_TIMEOUT
            )
            time.sleep(REQUEST_DELAY)  # respect rate limits

            season_stats_dict["team_stats"] = team_stats.league_dash_team_stats.get_data_frame()
            season_stats_dict["player_stats"] = player_stats.league_dash_player_stats.get_data_frame()

            logger.info(f"Successfully fetched season stats for {szn}")
            return season_stats_dict
        except Exception as e:
            logger.error(f"Failed to fetch season stats for {szn}: {e}")
            raise