# analysis/models/chapter_segmentation.py
"""
Game-chapter segmentation: split one game into 3-6 chapters, each a stretch
where the scoring rate between the teams was roughly steady. The boundaries
are the moments the game shifted.

STATUS: skeleton. Every method below has its design documented but is
unimplemented (raises NotImplementedError). Nothing here has been run.

Design decisions (proposed — change them before implementing if you disagree):

  Signal:     the score-margin *drift* (home points minus away points gained
              per time bin), not win probability. WP saturates in blowouts and
              compresses early in games, which would hide real shifts; drift
              captures "who is winning the minutes right now" at every point.
  Method:     optimal segmentation by dynamic programming — pick the set of
              changepoints minimizing within-segment squared error plus a
              per-changepoint penalty, with a minimum chapter length. Plain
              numpy, no new dependency. `ruptures` (Pelt) is a drop-in
              alternative if the DP proves slow.
  Importance: win probability is used to *rank and label* chapters
              (wp_swing), not to find them. Reuses WinProbabilityModel.
  Why:        each chapter gets ranked "drivers" (shooting vs turnovers vs
              free throws vs offensive rebounds vs foul trouble) computed by
              comparing the two teams' play-by-play events inside the chapter.
              Lineup-based drivers ("bench unit outscored starters 18-6") come
              later, once lineup reconstruction exists.

Pipeline:  play_by_play + WP model
              -> load_game_series()   per-play margin + WP + elapsed time
              -> build_signal()       fixed time grid, margin drift per bin
              -> find_changepoints()  DP segmentation
              -> build_chapters()     Chapter objects w/ margin & WP swing
              -> compute_drivers()    ranked reasons per chapter
              -> save_chapters()      game_chapters table
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger

from analysis.models.win_probability import WinProbabilityModel
from data.storage.db import SessionLocal
from data.storage.models import GameChapter

# Regulation is 4 x 12 min; each overtime is 5 min. NOTE: elapsed time is
# computed here from period + clock directly. Do NOT reuse
# FeatureEngineer.calculate_seconds_remaining for it — its overtime branch
# adds (period - 4) * 300 on top of the OT clock (5:00 left at OT tip-off
# comes out as 600, not 300).
REG_PERIOD_SECONDS = 12 * 60
OT_PERIOD_SECONDS  = 5 * 60

# Tuning defaults — first guesses, to be set by looking at real games
DEFAULT_BIN_SECONDS         = 30    # width of the fixed time grid
DEFAULT_MIN_CHAPTER_SECONDS = 240   # no chapter shorter than 4 game-minutes
DEFAULT_PENALTY             = None  # None -> derive from noise level of the signal
MIN_CHAPTERS                = 3     # fewer than this and there's no "story"
MAX_CHAPTERS                = 6     # more than this and it's noise, not chapters


@dataclass
class Chapter:
    """One segment of a game. Mirrors the GameChapter table."""
    game_id:         str
    chapter_idx:     int
    start_action_id: int
    end_action_id:   int
    start_period:    int
    start_clock:     str
    end_period:      int
    end_clock:       str
    start_elapsed:   float          # game seconds elapsed at chapter start
    end_elapsed:     float
    start_margin:    int            # home - away
    end_margin:      int
    wp_start:        float          # home win probability
    wp_end:          float
    label:           str = ""
    drivers:         list[dict] = field(default_factory=list)

    @property
    def margin_swing(self) -> int:
        return self.end_margin - self.start_margin

    @property
    def wp_swing(self) -> float:
        return self.wp_end - self.wp_start


class ChapterSegmenter:
    """
    Finds chapters for a game and explains what drove each one.

    Typical use:
        segmenter = ChapterSegmenter()
        chapters  = segmenter.segment_game("0022500002")
        segmenter.save_chapters("0022500002", chapters)
    """

    def __init__(self, wp_model: WinProbabilityModel = None):
        """
        wp_model: a fitted WinProbabilityModel. If None, loads the latest
                  saved model (WinProbabilityModel.load()).
        """
        raise NotImplementedError

    # ── Data ─────────────────────────────────────────────────────

    def load_game_series(self, game_id: str) -> pd.DataFrame:
        """
        One row per play, in order, with everything segmentation needs.

        Returns:
            DataFrame with columns:
                action_id, period, clock, elapsed_seconds,
                home_score, away_score, score_margin, home_wp,
                event_type, description, player_name, team
            Sorted by action_id. elapsed_seconds is OT-safe (see module note).
            Empty DataFrame if the game has no play-by-play.

        Built from WinProbabilityModel.predict_game() (margin + WP), joined
        with play_by_play for player_name/team, plus elapsed_seconds.
        """
        raise NotImplementedError

    def build_signal(self, df: pd.DataFrame, bin_seconds: int = DEFAULT_BIN_SECONDS) -> pd.DataFrame:
        """
        Resample the play-level series onto a fixed time grid so every bin
        covers the same amount of game time.

        Returns:
            DataFrame, one row per bin:
                bin_idx, bin_end_elapsed, margin (last margin in the bin,
                carried forward through bins with no scoring), drift
                (margin change during the bin), home_wp, last_action_id

        The changepoint search runs on the `drift` column. Bins are mapped
        back to action_ids so boundaries land on a real play.
        """
        raise NotImplementedError

    # ── Segmentation ─────────────────────────────────────────────

    def find_changepoints(
        self,
        signal:         pd.DataFrame,
        penalty:        float = DEFAULT_PENALTY,
        min_size_bins:  int   = None,
    ) -> list[int]:
        """
        Optimal segmentation of `signal['drift']` by dynamic programming:
        choose changepoints minimizing
            sum(within-segment squared error) + penalty * n_changepoints
        subject to every segment being at least `min_size_bins` long.

        Args:
            penalty:       cost per changepoint. None -> derived from the
                           signal's noise variance (BIC-style), so a blowout
                           and a tight game both get sensible chapter counts.
            min_size_bins: minimum bins per chapter; None -> derived from
                           DEFAULT_MIN_CHAPTER_SECONDS.

        Returns:
            Sorted bin indices where a new chapter begins (excluding 0).

        The result is clamped to MIN_CHAPTERS..MAX_CHAPTERS chapters by
        adjusting the penalty and re-running, rather than by truncating.
        """
        raise NotImplementedError

    def build_chapters(
        self,
        game_id:    str,
        df:         pd.DataFrame,
        signal:     pd.DataFrame,
        boundaries: list[int],
    ) -> list[Chapter]:
        """
        Turn changepoint bin indices into Chapter objects: map each boundary
        to a real play (action_id), then read margin / WP / period / clock at
        each chapter's start and end from `df`. Chapters must tile the game:
        chapter i ends at the action_id chapter i+1 starts at.
        """
        raise NotImplementedError

    # ── Explanation ──────────────────────────────────────────────

    def compute_drivers(self, game_id: str, chapter: Chapter, df: pd.DataFrame) -> list[dict]:
        """
        Why did the margin move in this chapter? Compare the two teams'
        play-by-play inside the chapter on: field-goal shooting (makes vs
        misses, 3s), turnovers, free throws, offensive rebounds, fouls.

        Returns a list sorted by estimated points contribution, e.g.:
            [
                {"factor": "turnovers",  "team": "LAL", "detail": "GSW 6 TO vs 1", "points_impact": 5.0},
                {"factor": "3pt_shooting", ...},
            ]

        Lineup drivers (starters vs bench units) are out of scope here — they
        depend on lineup reconstruction from Substitution events, which is a
        separate piece of work.
        """
        raise NotImplementedError

    def label_chapter(self, chapter: Chapter, home_team: str, away_team: str) -> str:
        """
        Short deterministic tag, no LLM: names the team that gained and the
        size of the swing, e.g. "LAL 14-2 run" or "GSW grind, +6".
        Downstream narrative agents receive this plus `drivers`; they should
        not have to infer what happened from raw plays.
        """
        raise NotImplementedError

    # ── End to end + persistence ─────────────────────────────────

    def segment_game(self, game_id: str) -> list[Chapter]:
        """
        Run the whole pipeline for one game: load_game_series ->
        build_signal -> find_changepoints -> build_chapters ->
        compute_drivers -> label_chapter.
        Returns [] if the game has no play-by-play.
        """
        raise NotImplementedError

    def save_chapters(self, game_id: str, chapters: list[Chapter]) -> None:
        """
        Replace any existing GameChapter rows for the game with `chapters`
        (delete + insert in one transaction, so re-running is idempotent).
        """
        raise NotImplementedError

    def load_chapters(self, game_id: str) -> list[Chapter]:
        """Read a game's saved chapters, ordered by chapter_idx. [] if none."""
        raise NotImplementedError

    def segment_season(self, seasons: list[str] = None, overwrite: bool = False) -> dict:
        """
        Segment and save every game in the given season codes (same
        convention as train.py, e.g. "22024"). Skips games that already have
        chapters unless overwrite=True.

        Returns a summary: {"segmented": int, "skipped": int, "failed": [game_id, ...]}
        """
        raise NotImplementedError
