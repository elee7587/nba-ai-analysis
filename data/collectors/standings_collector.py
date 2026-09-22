from nba_api.stats.endpoints import leaguestandingsv3
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class StandingsCollector:

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_standings(self, season: str, season_type: str = "Regular Season"):
        """
        Fetches the CURRENT league-wide standings (all 30 teams). NOTE:
        LeagueStandingsV3 has no as-of-date parameter — this always returns
        standings as of *now*, regardless of what `season` is set to. There
        is no way to ask nba_api for standings as of a past date.
        """
        time.sleep(REQUEST_DELAY)  # respect rate limits
        try:
            standings = leaguestandingsv3.LeagueStandingsV3(
                season=season,
                season_type=season_type,  # NOTE: `season_type=`, not `season_type_all_star=` like
                                           # leaguedashteamstats/leaguedashplayerstats use — a real
                                           # signature difference between nba_api endpoint families
                timeout=REQUEST_TIMEOUT
            )
            df = standings.standings.get_data_frame()
            logger.info(f"Successfully fetched standings for {season} ({len(df)} teams)")
            return df
        except Exception as e:
            logger.error(f"Failed to fetch standings for {season}: {e}")
            raise
