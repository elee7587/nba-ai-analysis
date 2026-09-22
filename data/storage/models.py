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

    season          = Column(String, primary_key=True)
    team_id         = Column(String, primary_key=True)
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

    season            = Column(String, primary_key=True)
    player_id         = Column(String, primary_key=True)
    player_name       = Column(String)
    team_id           = Column(String)
    team_abbreviation = Column(String)
    gp                = Column(Integer)
    pts               = Column(Float)
    pts_rank          = Column(Integer)
    ast               = Column(Float)
    ast_rank          = Column(Integer)
    reb               = Column(Float)
    reb_rank          = Column(Integer)
    stl               = Column(Float)
    stl_rank          = Column(Integer)
    blk               = Column(Float)
    blk_rank          = Column(Integer)
    tov               = Column(Float)
    tov_rank          = Column(Integer)
    fg_pct            = Column(Float)
    fg_pct_rank       = Column(Integer)
    plus_minus        = Column(Float)
    plus_minus_rank   = Column(Integer)
    dd2               = Column(Integer)
    td3               = Column(Integer)
    last_updated      = Column(DateTime)

class GameOutcome(Base):
    __tablename__ = "game_outcomes"

    game_id      = Column(String, ForeignKey("games.game_id"), primary_key=True)
    home_team_id = Column(String)
    home_won     = Column(Integer)  # 1 = home won, 0 = home lost
    season       = Column(String)
    created_at   = Column(DateTime, default=datetime.utcnow)


class TeamStandingsSnapshot(Base):
    """A dated snapshot of one team's league standing — deliberately NOT an
    upsert-latest table like SeasonTeamStats. The composite primary key on
    (snapshot_date, team_id) lets a "before this game" row and an "after
    this game" row coexist for the same team, which is what the standings
    video segment diffs. Populated once per day (league-wide, all 30 teams
    at once) by data/processors/standings_processor.py, not per-game.

    NOTE: nba_api's LeagueStandingsV3 has no as-of-date parameter — it only
    ever returns the *current* live standings. That means a row's
    snapshot_date reflects whenever it was actually captured, and there is
    no way to backfill accurate snapshots for past dates. See
    data/collectors/standings_collector.py and pipeline.py for detail.
    """
    __tablename__ = "team_standings_snapshots"

    # "YYYY-MM-DD" — String, not DateTime like Game.game_date, so exact-match/range
    # queries on a once-a-day snapshot have no time-of-day equality footguns.
    snapshot_date        = Column(String, primary_key=True)
    team_id              = Column(String, primary_key=True)
    season               = Column(String)
    conference           = Column(String)
    division             = Column(String)
    wins                 = Column(Integer)
    losses               = Column(Integer)
    win_pct              = Column(Float)
    conference_rank      = Column(Integer)  # nba_api "PlayoffRank" — the team's conference seed, 1-15
    division_rank        = Column(Integer)  # nba_api "DivisionRank"
    conference_games_back = Column(Float)
    division_games_back  = Column(Float)
    conference_record    = Column(String)   # e.g. "8-4"
    division_record      = Column(String)
    home_record          = Column(String)   # nba_api "HOME"
    road_record          = Column(String)   # nba_api "ROAD"
    last_10              = Column(String)   # nba_api "L10"
    current_streak       = Column(String)   # nba_api "strCurrentStreak", e.g. "W 3"
    created_at           = Column(DateTime, default=datetime.utcnow)


class GameChapter(Base):
    """One row per chapter of a game, as produced by
    analysis/models/chapter_segmentation.py. Chapters are a *descriptive*
    partition of the game's score-margin curve into a fixed number of
    stretches (see the analysis in analysis/exploration/chapter_eda.py) —
    they are not claims of statistically distinct regimes. Chapters tile the
    game completely: chapter_idx 0..K-1, each starting at the play where the
    previous one ended, so margin_swing values sum to the final margin.
    """
    __tablename__ = "game_chapters"

    game_id        = Column(String, ForeignKey("games.game_id"), primary_key=True)
    chapter_idx    = Column(Integer, primary_key=True)  # 0-based, chronological

    # boundaries — action_id is the join key back to play_by_play
    start_action_id = Column(Integer)
    end_action_id   = Column(Integer)
    start_period    = Column(Integer)
    start_clock     = Column(String)    # nba_api format, e.g. "PT07M03.00S"
    end_period      = Column(Integer)
    end_clock       = Column(String)
    start_elapsed   = Column(Float)     # game seconds elapsed (OT-safe), for x-axis placement
    end_elapsed     = Column(Float)

    # what happened inside the chapter (home perspective: positive = home gained)
    start_margin    = Column(Integer)
    end_margin      = Column(Integer)
    margin_swing    = Column(Integer)   # end_margin - start_margin
    home_points     = Column(Integer)   # points scored by home inside the chapter
    away_points     = Column(Integer)

    label           = Column(String)    # short deterministic tag, e.g. "LAL +11 (28-17)"
    drivers         = Column(JSON)      # ranked reasons for the swing; empty until compute_drivers exists
    created_at      = Column(DateTime, default=datetime.utcnow)


class GameArchetype(Base):
    """One row per game: which whole-game shape cluster it belongs to, as
    produced by analysis/models/game_archetypes.py. This clusters each
    game's *entire* regulation-time margin curve (from the eventual winner's
    perspective, so a comeback is a comeback regardless of home/away) across
    a season — a different, and less fraught, exercise than GameChapter's
    per-game boundary finding: chapter_eda.py found no more within-game
    regime structure than chance, but whole-game shapes (blowout vs seesaw
    vs comeback) are just observably different curves, no significance test
    required.

    Feeds ChapterSegmenter: cluster_id maps to a fixed chapter count `k`
    (derived from the cluster's average margin-drift complexity, bucketed
    into a bounded range — see game_archetypes.py), so chapter granularity
    can vary by game shape without any single game picking its own count.
    archetype_id and k are meaningful only within the same model_version;
    a re-fit reassigns both for every game.
    """
    __tablename__ = "game_archetypes"

    game_id       = Column(String, ForeignKey("games.game_id"), primary_key=True)
    archetype_id  = Column(Integer)   # cluster index (within model_version)
    label         = Column(String)    # deterministic heuristic label for the cluster's centroid shape
    k             = Column(Integer)   # chapter count ChapterSegmenter should use for this game
    complexity    = Column(Float)     # total variation of this game's margin drift (input to the k mapping)
    model_version = Column(String)    # timestamp tag of the clustering run that produced this row
    created_at    = Column(DateTime, default=datetime.utcnow)
