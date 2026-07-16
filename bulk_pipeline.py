# bulk_pipeline.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from nba_api.stats.endpoints import leaguegamelog
from data.processors.game_processor import GameProcessor
from data.storage.db import SessionLocal
from data.storage.models import Game, GameOutcome
from loguru import logger
import time
import pandas as pd
from datetime import datetime
from data.storage.models import Game, GameOutcome

def get_games_in_range(season: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Get all games within a date range"""
    time.sleep(2)
    log = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star='Regular Season'
    )
    df = log.get_data_frames()[0]
    df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
    mask = (df['GAME_DATE'] >= start_date) & (df['GAME_DATE'] <= end_date)
    return df[mask]

def get_home_team_result(game_rows: pd.DataFrame) -> dict | None:
    """
    Determine which team was home and whether they won
    MATCHUP format: 'LAL vs. GSW' = home team, 'GSW @ LAL' = away team
    """
    for _, row in game_rows.iterrows():
        if 'vs.' in row['MATCHUP']:
            return {
                "game_id":      str(row['GAME_ID']),
                "home_team_id": str(row['TEAM_ID']),
                "home_won":     1 if row['WL'] == 'W' else 0,
                "game_date":    row['GAME_DATE'],
                "season":       str(row['SEASON_ID'])
            }
    return None

def store_game_record(game_rows: pd.DataFrame, game_id: str):
    """Store the game record in the games table first"""
    session = SessionLocal()
    try:
        # get home and away rows
        home_row = None
        away_row = None
        for _, row in game_rows.iterrows():
            if 'vs.' in row['MATCHUP']:
                home_row = row
            else:
                away_row = row

        if home_row is None or away_row is None:
            logger.warning(f"Could not determine home/away for {game_id}")
            return

        game = Game(
            game_id    = str(game_id),
            game_date  = pd.to_datetime(home_row['GAME_DATE']),
            home_team  = str(int(home_row['TEAM_ID'])),
            away_team  = str(int(away_row['TEAM_ID'])),
            home_score = int(home_row['PTS']),
            away_score = int(away_row['PTS']),
            season     = str(home_row['SEASON_ID'])
        )
        session.merge(game)
        session.commit()
        logger.info(f"Stored game record for {game_id}")

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to store game record for {game_id}: {e}")
    finally:
        session.close()

def store_game_outcome(result: dict):
    """Store win/loss outcome for a game in the database"""
    session = SessionLocal()
    try:
        outcome = GameOutcome(
            game_id      = result['game_id'],
            home_team_id = result['home_team_id'],
            home_won     = result['home_won'],
            season       = result['season']
        )
        session.merge(outcome)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to store outcome for {result['game_id']}: {e}")
    finally:
        session.close()

def bulk_process(season: str, start_date: str, end_date: str, batch_size: int = 50, start_from: int = 0):
    """
    Process games in a date range in batches
    season:     NBA season string e.g. '2025-26'
    start_date: 'YYYY-MM-DD'
    end_date:   'YYYY-MM-DD'
    batch_size: number of games per batch
    start_from: index to resume from if interrupted
    """
    df = get_games_in_range(season, start_date, end_date)
    unique_game_ids = df['GAME_ID'].unique().tolist()

    # apply start_from for resuming
    unique_game_ids = unique_game_ids[start_from:]
    logger.info(f"Found {len(unique_game_ids)} games to process starting from index {start_from}")

    processor    = GameProcessor()
    success      = 0
    failed       = 0
    failed_games = []

    for i, game_id in enumerate(unique_game_ids):
        try:
            logger.info(f"Processing game {i + 1 + start_from}/{len(unique_game_ids) + start_from}: {game_id}")

            game_rows = df[df['GAME_ID'] == game_id]

            # step 1 — store game record first (required for foreign keys)
            store_game_record(game_rows, game_id)

            # step 2 — store win/loss outcome
            result = get_home_team_result(game_rows)
            if result:
                store_game_outcome(result)

            # step 3 — process boxscore and play by play
            processor.process_boxscore(game_id)
            processor.process_play_by_play(game_id)

            success += 1
            time.sleep(3)

        except Exception as e:
            logger.error(f"Failed to process game {game_id}: {e}")
            failed_games.append(game_id)
            failed += 1
            time.sleep(5)

    logger.info(f"Bulk processing complete — {success} succeeded, {failed} failed")
    if failed_games:
        logger.warning(f"Failed games: {failed_games}")
        # save failed games to file for retry
        with open("failed_games.txt", "w") as f:
            f.write("\n".join(failed_games))

    return {"success": success, "failed": failed, "failed_games": failed_games}


if __name__ == "__main__":
    import sys

    season     = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
    start_date = sys.argv[2] if len(sys.argv) > 2 else "2025-10-21"
    end_date   = sys.argv[3] if len(sys.argv) > 3 else "2025-11-21"
    batch_size = int(sys.argv[4]) if len(sys.argv) > 4 else 50
    start_from = int(sys.argv[5]) if len(sys.argv) > 5 else 0

    bulk_process(season, start_date, end_date, batch_size, start_from)