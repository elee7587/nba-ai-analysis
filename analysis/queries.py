# analysis/queries.py
from data.storage.db import SessionLocal
from data.storage.models import (
    PlayByPlay, BoxScore_Player, BoxScore_Team,
    AdvancedBoxScorePlayer, SeasonPlayerStats, SeasonTeamStats
)

def get_play_by_play(game_id: str) -> list:
    # query play_by_play ordered by action_id
    session = SessionLocal()
    try:
        plays = session.query(PlayByPlay)\
            .filter(PlayByPlay.game_id == game_id)\
            .order_by(PlayByPlay.action_id)\
            .all()
        return [{
            f"{k}": v 
            for k, v in play.__dict__.items() if k != "_sa_instance_state"
        } for play in plays]
    except Exception as e:
        print(f"Failed to get play by play for game {game_id}: {e}")
        raise
    finally:
        session.close()

def get_team_comparison(game_id: str) -> dict:
    # query box_scores_teams + season_team_stats for both teams
    session = SessionLocal()
    try:
        # queries for both teams in the game
        game_stats = session.query(BoxScore_Team)\
            .filter(BoxScore_Team.game_id == game_id)\
            .all()
        result = []
        # for each team, queries season stats
        for team in game_stats:
            season_stats = session.query(SeasonTeamStats)\
            .filter(SeasonTeamStats.team_id == team.team_id)\
            .first()
            # attach season stats to team object with prefix season_
            game_dict = {
                f"game_{k}": v
                for k, v in team.__dict__.items()
                if k != "_sa_instance_state"
            }
            season_dict = {
                f"season_{k}": v
                for k, v in season_stats.__dict__.items()
                if k != "_sa_instance_state"
            } if season_stats else {}
            result.append({**game_dict, **season_dict})
        return result
    except Exception as e:
        print(f"Failed to get team comparison for game {game_id}: {e}")
        raise
    finally:
        session.close()

def get_player_comparison(game_id: str) -> dict:
    # query box_scores_players + season_player_stats for all players in game
    session = SessionLocal()
    try:
        # queries for all players in the game
        game_stats = session.query(BoxScore_Player)\
            .filter(BoxScore_Player.game_id == game_id)\
            .all()
        result = []
        # for each player, queries season stats
        for player in game_stats:
            season_stats = session.query(SeasonPlayerStats)\
                .filter(SeasonPlayerStats.player_id == player.player_id)\
                .first()
            # attach season stats to player object with prefix season_
            game_dict = {
                f"game_{k}": v
                for k, v in player.__dict__.items()
                if k != "_sa_instance_state"
            }
            season_dict = {
                f"season_{k}": v
                for k, v in season_stats.__dict__.items()
                if k != "_sa_instance_state"
            } if season_stats else {}
            result.append({**game_dict, **season_dict})
        return result
    except Exception as e:
        print(f"Failed to get player comparison for game {game_id}: {e}")
        raise
    finally:
        session.close()

def get_mvp_data(game_id: str) -> dict:
    # query box_scores_players + advanced_boxscore_players + season_player_stats
    session = SessionLocal()
    try:
        players_comparsion = get_player_comparison(game_id)
        for player in players_comparsion:
            advanced_stats = session.query(AdvancedBoxScorePlayer)\
                .filter(AdvancedBoxScorePlayer.game_id == game_id)\
                .filter(AdvancedBoxScorePlayer.player_id == player['game_player_id'])\
                .first()
            if advanced_stats:
                advanced_dict = {
                    f"advanced_{k}": v
                    for k, v in advanced_stats.__dict__.items()
                    if k != "_sa_instance_state"
                }
                player.update(advanced_dict)
        return players_comparsion
    except Exception as e:
        print(f"Failed to get MVP data for game {game_id}: {e}")
        raise
    finally:
        session.close()