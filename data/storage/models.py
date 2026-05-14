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

    game_id      = Column(String, primary_key=True)  # unique ID from NBA API
    game_date    = Column(DateTime)                   # date of the game
    home_team    = Column(String)                     # home team abbreviation
    away_team    = Column(String)                     # away team abbreviation
    home_score   = Column(Integer)                    # final home score
    away_score   = Column(Integer)                    # final away score
    season       = Column(String)                     # e.g. "2024-25"
    created_at   = Column(DateTime, default=datetime.utcnow)  # when we stored it

    # These let you navigate between tables easily
    boxscore_players  = relationship("BoxScore_Player", backref="game")
    boxscore_teams    = relationship("BoxScore_Team", backref="game")
    plays             = relationship("PlayByPlay", backref="game")
    quarter_scores    = relationship("QuarterScore", backref="game")


class BoxScore_Player(Base):
    __tablename__ = "box_scores_players"

    game_id = Column(String, ForeignKey("games.game_id"), primary_key=True)  # link to Game
    team_id = Column(String, primary_key=True)  # team abbreviation
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

    id              = Column(Integer, primary_key=True, autoincrement=True)  # auto generated ID
    game_id         = Column(String, ForeignKey("games.game_id"))            # link to Game
    period          = Column(Integer)    # quarter number (1-4, 5+ for OT)
    clock           = Column(String)     # time remaining in period (e.g. "5:32")
    home_score      = Column(Integer)    # running home score at this moment
    away_score      = Column(Integer)    # running away score at this moment
    score_margin    = Column(Integer)    # home - away at this moment
    event_type      = Column(Integer)    # type of event (score, foul, timeout etc)
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
