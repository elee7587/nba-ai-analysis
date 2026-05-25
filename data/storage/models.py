# data/storage/models.py
from sqlalchemy import (
    Column, String, Integer, Float, 
    DateTime, JSON, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Game(Base):
    __tablename__ = "games"

    game_id    = Column(String, primary_key=True)
    game_date  = Column(DateTime)              # was "date"
    home_team  = Column(String)                # was "home_team_id"
    away_team  = Column(String)                # was "away_team_id"
    home_score = Column(Integer)
    away_score = Column(Integer)
    season     = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    # These let you navigate between tables easily
    boxscore_players  = relationship("BoxScore_Player", backref="game")
    boxscore_teams    = relationship("BoxScore_Team", backref="game")
    plays             = relationship("PlayByPlay", backref="game")
    quarter_scores    = relationship("QuarterScore", backref="game")


class BoxScore_Player(Base):
    __tablename__ = "box_scores_players"

    game_id   = Column(String, ForeignKey("games.game_id"), primary_key=True)
    player_id = Column(String, primary_key=True)  # was team_id
    team_id   = Column(String)  # team ID
    team_abbrev = Column(String)  # team abbreviation
    team_city = Column(String)    # team city
    player_id = Column(String)  # player ID from NBA API
    player_name = Column(String)  # player name
    nickname = Column(String)  # player nickname
    start_position = Column(String)  # starting position (e.g. "Guard")
    comment = Column(Text)  # any comments about the player's performance
    minutes = Column(String)  # minutes played (e.g. "34:12")
    fgm = Column(Integer)  # field goals made
    fga = Column(Integer)  # field goals attempted
    fg_pct = Column(Float)  # field goal percentage
    fg_3m = Column(Integer)  # three-pointers made
    fg_3a = Column(Integer)  # three-pointers attempted
    fg_3_pct = Column(Float)  # three-point percentage
    ftm = Column(Integer)  # free throws made
    fta = Column(Integer)  # free throws attempted
    ft_pct = Column(Float)  # free throw percentage
    oreb = Column(Integer)  # offensive rebounds
    dreb = Column(Integer)  # defensive rebounds
    reb = Column(Integer)  # total rebounds
    ast = Column(Integer)  # assists
    stl = Column(Integer)  # steals
    blk = Column(Integer)  # blocks
    tov = Column(Integer)  # turnovers
    pf = Column(Integer)  # personal fouls
    pts = Column(Integer)  # points scored
    plus_minus = Column(Integer)  # plus/minus rating
    created_at = Column(DateTime, default=datetime.utcnow)  # when we stored it


class BoxScore_Team(Base):
    __tablename__ = "box_scores_teams"

    game_id = Column(String, ForeignKey("games.game_id"), primary_key=True)  # link to Game
    team_id = Column(String, primary_key=True)  # team abbreviation
    team_abbrev = Column(String)  # team abbreviation
    team_city = Column(String)    # team city
    minutes = Column(String)  # minutes played (e.g. "34:12")
    fgm = Column(Integer)  # field goals made
    fga = Column(Integer)  # field goals attempted
    fg_pct = Column(Float)  # field goal percentage
    fg_3m = Column(Integer)  # three-pointers made
    fg_3a = Column(Integer)  # three-pointers attempted
    fg_3_pct = Column(Float)  # three-point percentage
    ftm = Column(Integer)  # free throws made
    fta = Column(Integer)  # free throws attempted
    ft_pct = Column(Float)  # free throw percentage
    oreb = Column(Integer)  # offensive rebounds
    dreb = Column(Integer)  # defensive rebounds
    reb = Column(Integer)  # total rebounds
    ast = Column(Integer)  # assists
    stl = Column(Integer)  # steals
    blk = Column(Integer)  # blocks
    tov = Column(Integer)  # turnovers
    pf = Column(Integer)  # personal fouls
    pts = Column(Integer)  # points scored
    plus_minus = Column(Integer)  # plus/minus rating
    created_at = Column(DateTime, default=datetime.utcnow)  # when we stored it

class PlayByPlay(Base):
    __tablename__ = "play_by_play"

    game_id      = Column(String, ForeignKey("games.game_id"), primary_key=True)
    action_id    = Column(Integer, primary_key=True)  # unique per play
    period          = Column(Integer)    # quarter number (1-4, 5+ for OT)
    clock           = Column(String)     # time remaining in period (e.g. "5:32")
    home_score      = Column(Integer)    # running home score at this moment
    away_score      = Column(Integer)    # running away score at this moment
    score_margin    = Column(Integer)    # home - away at this moment
    event_type      = Column(String)     # type of event (score, foul, timeout etc)
    description     = Column(Text)       # human readable description of the play
    player_id       = Column(String)     # player involved in the play
    player_name     = Column(String)     # player name
    team            = Column(String)     # team abbreviation
    created_at      = Column(DateTime, default=datetime.utcnow)


class QuarterScore(Base):
    __tablename__ = "quarter_scores"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    game_id     = Column(String, ForeignKey("games.game_id"))  # link to Game
    team        = Column(String)   # team abbreviation
    quarter     = Column(Integer)  # quarter number (1-4, 5+ for OT)
    score       = Column(Integer)  # points scored in that quarter
    created_at  = Column(DateTime, default=datetime.utcnow)

class AdvancedBoxScorePlayer(Base):
    __tablename__ = "advanced_boxscore_players"

    id                              = Column(Integer, primary_key=True, autoincrement=True)
    game_id                         = Column(String, ForeignKey("games.game_id"))
    team_id                         = Column(String)
    team_tricode                    = Column(String)
    player_id                       = Column(String)
    player_name                     = Column(String)
    minutes                         = Column(String)
    estimated_offensive_rating      = Column(Float)
    offensive_rating                = Column(Float)
    estimated_defensive_rating      = Column(Float)
    defensive_rating                = Column(Float)
    estimated_net_rating            = Column(Float)
    net_rating                      = Column(Float)
    assist_percentage = Column(Float)  # was assist_pct
    rebound_percentage = Column(Float)  # was rebound_pct
    assist_to_turnover              = Column(Float)
    assist_ratio                    = Column(Float)
    offensive_rebound_pct           = Column(Float)
    defensive_rebound_pct           = Column(Float)
    turnover_ratio                  = Column(Float)
    effective_fg_pct                = Column(Float)
    true_shooting_pct               = Column(Float)
    usage_pct                       = Column(Float)
    estimated_usage_pct             = Column(Float)
    estimated_pace                  = Column(Float)
    pace                            = Column(Float)
    pace_per40                      = Column(Float)
    possessions                     = Column(Integer)
    pie                             = Column(Float)
    created_at                      = Column(DateTime, default=datetime.utcnow)


class AdvancedBoxScoreTeam(Base):
    __tablename__ = "advanced_boxscore_teams"

    id                              = Column(Integer, primary_key=True, autoincrement=True)
    game_id                         = Column(String, ForeignKey("games.game_id"))
    team_id                         = Column(String)
    team_tricode                    = Column(String)
    minutes                         = Column(String)
    estimated_offensive_rating      = Column(Float)
    offensive_rating                = Column(Float)
    estimated_defensive_rating      = Column(Float)
    defensive_rating                = Column(Float)
    estimated_net_rating            = Column(Float)
    net_rating                      = Column(Float)
    assist_percentage               = Column(Float)
    assist_to_turnover              = Column(Float)
    assist_ratio                    = Column(Float)
    offensive_rebound_pct           = Column(Float)
    defensive_rebound_pct           = Column(Float)
    rebound_percentage              = Column(Float)
    turnover_ratio                  = Column(Float)
    effective_fg_pct                = Column(Float)
    true_shooting_pct               = Column(Float)
    usage_percentage                = Column(Float)
    estimated_usage_pct             = Column(Float)
    estimated_pace                  = Column(Float)
    pace                            = Column(Float)
    pace_per40                      = Column(Float)
    possessions                     = Column(Integer)
    pie                             = Column(Float)
    created_at                      = Column(DateTime, default=datetime.utcnow)


class SeasonTeamStats(Base):
    __tablename__ = "season_team_stats"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    season          = Column(String)
    team_id         = Column(String)
    team_name       = Column(String)
    gp              = Column(Integer)
    w_pct           = Column(Float)
    pts             = Column(Float)
    pts_rank        = Column(Integer)
    ast             = Column(Float)
    ast_rank        = Column(Integer)
    reb             = Column(Float)
    reb_rank        = Column(Integer)
    tov             = Column(Float)
    tov_rank        = Column(Integer)
    fg_pct          = Column(Float)
    fg_pct_rank     = Column(Integer)
    stl             = Column(Float)
    stl_rank        = Column(Integer)
    blk             = Column(Float)
    blk_rank        = Column(Integer)
    plus_minus      = Column(Float)
    plus_minus_rank = Column(Integer)
    last_updated    = Column(DateTime)


class SeasonPlayerStats(Base):
    __tablename__ = "season_player_stats"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    season          = Column(String)
    player_id       = Column(String)
    player_name     = Column(String)
    team_id         = Column(String)
    team_abbreviation = Column(String)
    gp              = Column(Integer)
    pts             = Column(Float)
    pts_rank        = Column(Integer)
    ast             = Column(Float)
    ast_rank        = Column(Integer)
    reb             = Column(Float)
    reb_rank        = Column(Integer)
    stl             = Column(Float)
    stl_rank        = Column(Integer)
    blk             = Column(Float)
    blk_rank        = Column(Integer)
    tov             = Column(Float)
    tov_rank        = Column(Integer)
    fg_pct          = Column(Float)
    fg_pct_rank     = Column(Integer)
    plus_minus      = Column(Float)
    plus_minus_rank = Column(Integer)
    dd2             = Column(Integer)
    td3             = Column(Integer)
    last_updated    = Column(DateTime)