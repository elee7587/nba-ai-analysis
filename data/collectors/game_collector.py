from nba_api.stats.endpoints import scoreboardv3
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger
import time
from config.settings import REQUEST_DELAY, REQUEST_TIMEOUT

class GameCollector:
    
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_games_by_date(self, date: str) -> list:
        """
        Fetches all games for specific date format: 'YYYY-MM-DD'
        """
        time.sleep(REQUEST_DELAY)
        games = []
        try:
            board = scoreboardv3.ScoreboardV3(
                game_date=date,
                timeout=REQUEST_TIMEOUT
            )
            game_header = board.game_header.get_data_frame()
            line_score  = board.line_score.get_data_frame()

            for _, game in game_header.iterrows():
                game_id = game['gameId']

                # get the two rows for this game from line_score
                teams = line_score[line_score['gameId'] == game_id]

                if len(teams) < 2:
                    logger.warning(f"Could not find two teams for game {game_id}, skipping")
                    continue

                # parse home and away from gameCode format: YYYYMMDD/AWAYTEAMHOMETEAM
                game_code  = game['gameCode']
                teams_part = game_code.split('/')[1]

                home_team = None
                away_team = None

                for _, team in teams.iterrows():
                    tricode = team['teamTricode']
                    if teams_part.endswith(tricode):
                        home_team = team
                    else:
                        away_team = team

                if home_team is None or away_team is None:
                    logger.warning(f"Could not determine home/away for game {game_id}, skipping")
                    continue

                # derive season from gameTimeUTC year
                game_time = str(game['gameTimeUTC'])
                year      = int(game_time[:4])
                month     = int(game_time[5:7])
                if month >= 10:
                    season = f"{year}-{str(year + 1)[-2:]}"
                else:
                    season = f"{year - 1}-{str(year)[-2:]}"

                games.append({
                    "game_id":    str(game_id),
                    "game_date":  str(game['gameEt']),
                    "home_team":  int(home_team['teamId']),
                    "away_team":  int(away_team['teamId']),
                    "home_score": int(home_team['score']) if home_team['score'] not in (None, '') else None,
                    "away_score": int(away_team['score']) if away_team['score'] not in (None, '') else None,
                    "season":     season
                })

            logger.info(f"Found {len(games)} games on {date}")
        except Exception as e:
            logger.error(f"Failed to fetch games for {date}: {e}")
            raise
        return games