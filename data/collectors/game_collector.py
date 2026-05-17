from nba_api.stats.endpoints import scoreboardv2
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class GameCollector:
    
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_games_by_date(self, date: str) -> dict:
        """
        Fetches all games for specific date format: 'YYYY-MM-DD'
        Grab both game_header df and line_score df
        """
        time.sleep(REQUEST_DELAY)  # respect rate limits
        games = {}
        try:
            board = scoreboardv2.ScoreboardV2(
                game_date=date, 
                timeout=REQUEST_TIMEOUT
            )
            game_header = board.game_header.get_data_frame()
            line_score = board.line_score.get_data_frame()
            # split into home and away
            for _, game in game_header.iterrows():
                game_id = game['GAME_ID']
                home_team_id = game["HOME_TEAM_ID"]
                away_team_id = game["VISITOR_TEAM_ID"]
                
                # filter line_score using these values
                home_line = line_score[
                    (line_score['GAME_ID'] == game_id) & (line_score['TEAM_ID'] == home_team_id)
                ].iloc[0]  # should only be one row
                away_line = line_score[
                    (line_score['GAME_ID'] == game_id) & (line_score['TEAM_ID'] == away_team_id)
                ].iloc[0]  # should only be one row
                
                games.append({
                    "game_id": game_id,
                    "game_date": date,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home_score": home_line['PTS'],
                    "away_score": away_line['PTS'],
                    "season": game['SEASON']
                })
        except Exception as e:
            logger.error(f"Failed to fetch games for {date}: {e}")
            raise
        return games
