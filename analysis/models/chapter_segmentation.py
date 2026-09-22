# analysis/models/chapter_segmentation.py
"""
Game-chapter segmentation: split one game into a fixed number (K) of chapters
that best summarize the shape of its score-margin curve.

This is DESCRIPTIVE, not inferential. analysis/exploration/chapter_eda.py
showed that statistical changepoint detection finds no more "regime shifts"
in real games than in the same games with their scoring shuffled, and that
real games are less streaky than chance (variance ratio 0.82 at 16 minutes,
lag-1 autocorrelation -0.08). So chapters here make no claim that the game
changed character at a boundary; they are the K-piece summary of the margin
curve that loses the least information. The same analysis found those
boundaries are stable across time-bin sizes (81-84% agreement within 90s vs
an 18% chance baseline).

Method:
  Signal:  score-margin *drift* — the change in home-minus-away margin per
           fixed 30s bin of game time.
  Fit:     exact optimal partition into K segments (dynamic programming),
           minimizing within-segment squared error of the drift, each chapter
           at least 4 game-minutes. Plain numpy.
  Label:   deterministic, from the points each team scored in the chapter.

Not built yet: compute_drivers() — *why* the margin moved in a chapter
(shooting vs turnovers vs ...). Win-probability-based importance ranking is
also deferred until the win-probability model is fixed and retrained.

K is fixed per instance by default, but can instead be looked up per game
from analysis/models/game_archetypes.py (use_archetype_k=True): each game's
whole-game shape cluster maps to a chapter count bounded to
game_archetypes.CHAPTER_K_BOUNDS (default 3..6), so a blowout and a seesaw
game aren't forced into the same chapter count, without any single game's
own noise picking its own K (which is exactly what got simplified away here
in the first place — see git history of this file).

Pipeline:
    play_by_play -> load_game_series() -> build_signal() -> find_boundaries()
                 -> build_chapters() -> label_chapter() -> save_chapters()
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from data.storage.db import SessionLocal, engine
from data.storage.models import Game, GameChapter, PlayByPlay
from data.team_lookup import get_abbr

# Regulation is 4 x 12 min; each overtime is 5 min. Elapsed time is computed
# here from period + clock directly — do NOT reuse
# FeatureEngineer.calculate_seconds_remaining, whose overtime branch is wrong.
REG_PERIOD_SECONDS = 12 * 60
OT_PERIOD_SECONDS  = 5 * 60
REG_GAME_SECONDS   = 4 * REG_PERIOD_SECONDS

DEFAULT_K                   = 4
DEFAULT_BIN_SECONDS         = 30
DEFAULT_MIN_CHAPTER_SECONDS = 240
EVEN_THRESHOLD              = 3   # |margin swing| at or below this is labeled "even"


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
    home_points:     int
    away_points:     int
    label:           str = ""
    drivers:         list[dict] = field(default_factory=list)

    @property
    def margin_swing(self) -> int:
        return self.end_margin - self.start_margin


def _segment_k(x: np.ndarray, k: int, min_size: int) -> list[int]:
    """
    Optimal partition of x into exactly k contiguous segments, each at least
    min_size long, minimizing total within-segment squared error.

    Returns the sorted start indices of the segments (always begins with 0).
    k is reduced if x is too short to fit k segments of min_size.
    """
    n = len(x)
    k = max(1, min(k, n // min_size))
    cs  = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])

    D = np.full((k + 1, n + 1), np.inf)   # D[m, j]: best cost splitting x[:j] into m segments
    D[0, 0] = 0.0
    P = np.zeros((k + 1, n + 1), dtype=int)
    for m in range(1, k + 1):
        for j in range(m * min_size, n + 1):
            starts = np.arange((m - 1) * min_size, j - min_size + 1)
            length = j - starts
            cost   = cs2[j] - cs2[starts] - (cs[j] - cs[starts]) ** 2 / length
            total  = D[m - 1, starts] + cost
            best   = int(np.argmin(total))
            D[m, j], P[m, j] = total[best], starts[best]

    bounds, j = [], n
    for m in range(k, 0, -1):
        bounds.append(int(P[m, j]))
        j = P[m, j]
    return sorted(bounds)


class ChapterSegmenter:
    """
    Finds K chapters for a game and persists them.

    Typical use:
        segmenter = ChapterSegmenter()
        chapters  = segmenter.segment_game("0022500002")
        segmenter.save_chapters("0022500002", chapters)
    """

    def __init__(
        self,
        k:                   int  = DEFAULT_K,
        bin_seconds:         int  = DEFAULT_BIN_SECONDS,
        min_chapter_seconds: int  = DEFAULT_MIN_CHAPTER_SECONDS,
        use_archetype_k:     bool = False,
    ):
        """
        k:                   default number of chapters per game
        bin_seconds:         width of the fixed time grid; must divide 300 so
                             regulation and overtime periods both tile evenly
        min_chapter_seconds: no chapter shorter than this
        use_archetype_k:     if True, look up each game's chapter count from
                             its saved GameArchetype row (see
                             game_archetypes.py) instead of always using `k`.
                             Falls back to `k` for a game with no archetype
                             row yet (e.g. not classified, or too new).
        """
        if OT_PERIOD_SECONDS % bin_seconds:
            raise ValueError(f"bin_seconds must divide {OT_PERIOD_SECONDS}, got {bin_seconds}")
        self.k = k
        self.bin_seconds = bin_seconds
        self.min_chapter_seconds = min_chapter_seconds
        self.use_archetype_k = use_archetype_k
        self._table_ready = False

    def _k_for_game(self, game_id: str) -> int:
        if not self.use_archetype_k:
            return self.k
        # Imported here, not at module level, to avoid a circular import
        # (game_archetypes.py imports ChapterSegmenter itself).
        from data.storage.models import GameArchetype
        with SessionLocal() as session:
            row = session.get(GameArchetype, game_id)
        return row.k if row is not None else self.k

    # ── Data ─────────────────────────────────────────────────────

    def load_game_series(self, game_id: str) -> pd.DataFrame:
        """
        One row per play, in order, with the running score carried forward.

        play_by_play only records scores on scoring plays (~74% of rows are
        NULL), so scores are forward-filled within the game, starting at 0.

        Returns:
            DataFrame with columns:
                action_id, period, clock, elapsed_seconds, home_score,
                away_score, score_margin, event_type, description,
                player_name, team
            Sorted by action_id. elapsed_seconds is non-decreasing and
            OT-safe. Empty DataFrame if the game has no play-by-play.
        """
        stmt = (
            select(PlayByPlay.action_id, PlayByPlay.period, PlayByPlay.clock,
                   PlayByPlay.home_score, PlayByPlay.away_score, PlayByPlay.event_type,
                   PlayByPlay.description, PlayByPlay.player_name, PlayByPlay.team)
            .where(PlayByPlay.game_id == game_id)
            .order_by(PlayByPlay.action_id)
        )
        df = pd.read_sql(stmt, engine)
        if df.empty:
            logger.warning(f"No play-by-play found for game {game_id}")
            return df

        df[["home_score", "away_score"]] = df[["home_score", "away_score"]].ffill().fillna(0)
        df["score_margin"] = (df["home_score"] - df["away_score"]).astype(int)

        parts = df["clock"].str.extract(r"PT(\d+)M([\d.]+)S").astype(float)
        remaining = parts[0] * 60 + parts[1]
        df["elapsed_seconds"] = np.where(
            df["period"] <= 4,
            (df["period"] - 1) * REG_PERIOD_SECONDS + (REG_PERIOD_SECONDS - remaining),
            REG_GAME_SECONDS + (df["period"] - 5) * OT_PERIOD_SECONDS + (OT_PERIOD_SECONDS - remaining),
        )
        df = df.dropna(subset=["elapsed_seconds"]).reset_index(drop=True)
        df["elapsed_seconds"] = np.maximum.accumulate(df["elapsed_seconds"].to_numpy())
        return df

    def build_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Resample the play-level series onto a fixed time grid so every bin
        covers the same amount of game time.

        Returns:
            DataFrame, one row per bin:
                bin_idx, bin_end_elapsed, margin (margin after the last play
                at or before the bin edge — carried through quiet bins),
                drift (margin change during the bin), last_action_id
        """
        periods = int(df["period"].max())
        total   = REG_GAME_SECONDS + OT_PERIOD_SECONDS * max(0, periods - 4)
        edges   = np.arange(self.bin_seconds, total + 1e-9, self.bin_seconds)

        idx    = np.searchsorted(df["elapsed_seconds"].to_numpy(), edges, side="right") - 1
        safe   = np.clip(idx, 0, None)
        margin = np.where(idx >= 0, df["score_margin"].to_numpy()[safe], 0)
        drift  = np.diff(np.concatenate([[0], margin]))
        last_action_id = np.where(idx >= 0, df["action_id"].to_numpy()[safe], df["action_id"].iloc[0])

        return pd.DataFrame({
            "bin_idx":         np.arange(len(edges)),
            "bin_end_elapsed": edges,
            "margin":          margin,
            "drift":           drift.astype(float),
            "last_action_id":  last_action_id,
        })

    # ── Segmentation ─────────────────────────────────────────────

    def find_boundaries(self, signal: pd.DataFrame, k: int = None) -> list[int]:
        """
        Start bin index of each chapter (first is always 0). Exactly k
        chapters (self.k if not given) unless the game is too short to fit k
        of the minimum length.
        """
        min_size = max(1, self.min_chapter_seconds // self.bin_seconds)
        return _segment_k(signal["drift"].to_numpy(), k if k is not None else self.k, min_size)

    def build_chapters(
        self,
        game_id: str,
        df:      pd.DataFrame,
        signal:  pd.DataFrame,
        starts:  list[int],
    ) -> list[Chapter]:
        """
        Turn chapter start bins into Chapter objects. Boundaries land on real
        plays (the last play at or before the bin edge), and chapters tile the
        game: chapter i ends on the same play chapter i+1 starts on, so the
        margin swings sum to the final margin.
        """
        first, last = df["action_id"].iloc[0], df["action_id"].iloc[-1]
        boundary_ids = [first] + [int(signal["last_action_id"].iloc[s - 1]) for s in starts[1:]] + [last]
        boundary_elapsed = ([0.0] + [float(signal["bin_end_elapsed"].iloc[s - 1]) for s in starts[1:]]
                            + [float(df["elapsed_seconds"].iloc[-1])])
        by_action = df.set_index("action_id")

        chapters = []
        for i in range(len(starts)):
            a, b = by_action.loc[boundary_ids[i]], by_action.loc[boundary_ids[i + 1]]
            chapters.append(Chapter(
                game_id=game_id, chapter_idx=i,
                start_action_id=int(boundary_ids[i]), end_action_id=int(boundary_ids[i + 1]),
                start_period=int(a["period"]), start_clock=a["clock"],
                end_period=int(b["period"]),   end_clock=b["clock"],
                start_elapsed=boundary_elapsed[i], end_elapsed=boundary_elapsed[i + 1],
                start_margin=int(a["score_margin"]), end_margin=int(b["score_margin"]),
                home_points=int(b["home_score"] - a["home_score"]),
                away_points=int(b["away_score"] - a["away_score"]),
            ))
        return chapters

    # ── Description ──────────────────────────────────────────────

    def compute_drivers(self, game_id: str, chapter: Chapter, df: pd.DataFrame) -> list[dict]:
        """
        NOT BUILT YET. Why did the margin move in this chapter? Compare the
        two teams' events inside the chapter (shooting vs season norms,
        turnovers, free throws, offensive rebounds, fouls). Given that scoring
        in real games is mean-reverting, the useful framing is likely
        "skill vs luck" (e.g. opponent shot 58% from three vs their 36% season
        average), which needs season stats joined in.
        """
        raise NotImplementedError

    def label_chapter(self, chapter: Chapter, home_abbr: str, away_abbr: str) -> str:
        """
        Short deterministic tag, no LLM:
            "LAL +11 (28-17)"   the team that outscored the other, with the
                                points each side scored (leader's first)
            "Even (22-21)"      when |swing| <= EVEN_THRESHOLD
        """
        swing = chapter.margin_swing
        if abs(swing) <= EVEN_THRESHOLD:
            return f"Even ({chapter.home_points}-{chapter.away_points})"
        if swing > 0:
            return f"{home_abbr} +{swing} ({chapter.home_points}-{chapter.away_points})"
        return f"{away_abbr} +{-swing} ({chapter.away_points}-{chapter.home_points})"

    # ── End to end + persistence ─────────────────────────────────

    @staticmethod
    def _team_abbrs(game: Game) -> tuple[str, str]:
        def abbr(team_id):
            try:
                return get_abbr(team_id) or str(team_id)
            except (TypeError, ValueError):
                return str(team_id)
        return abbr(game.home_team), abbr(game.away_team)

    def segment_game(self, game_id: str) -> list[Chapter]:
        """
        Run the pipeline for one game. Returns [] (with a warning) if the game
        has no play-by-play, isn't in the games table, or its play-by-play
        stops short of the final score (truncated data would yield chapters
        for only part of the game).
        """
        df = self.load_game_series(game_id)
        if df.empty:
            return []
        with SessionLocal() as session:
            game = session.get(Game, game_id)
        if game is None:
            logger.warning(f"Game {game_id} not in games table; skipping")
            return []
        if (int(df["home_score"].iloc[-1]), int(df["away_score"].iloc[-1])) != (game.home_score, game.away_score):
            logger.warning(f"Play-by-play for {game_id} ends at {int(df['home_score'].iloc[-1])}-"
                           f"{int(df['away_score'].iloc[-1])} but the final was "
                           f"{game.home_score}-{game.away_score}; skipping (truncated data)")
            return []
        signal = self.build_signal(df)
        starts = self.find_boundaries(signal, k=self._k_for_game(game_id))
        chapters = self.build_chapters(game_id, df, signal, starts)
        home, away = self._team_abbrs(game)
        for ch in chapters:
            ch.label = self.label_chapter(ch, home, away)
        return chapters

    def _ensure_table(self):
        if not self._table_ready:
            GameChapter.__table__.create(engine, checkfirst=True)
            self._table_ready = True

    def save_chapters(self, game_id: str, chapters: list[Chapter]) -> None:
        """
        Replace any existing GameChapter rows for the game (delete + insert in
        one transaction, so re-running is idempotent). Creates the
        game_chapters table if it doesn't exist yet.
        """
        self._ensure_table()
        with SessionLocal() as session:
            session.query(GameChapter).filter(GameChapter.game_id == game_id).delete()
            for ch in chapters:
                session.add(GameChapter(
                    game_id=ch.game_id, chapter_idx=ch.chapter_idx,
                    start_action_id=ch.start_action_id, end_action_id=ch.end_action_id,
                    start_period=ch.start_period, start_clock=ch.start_clock,
                    end_period=ch.end_period, end_clock=ch.end_clock,
                    start_elapsed=ch.start_elapsed, end_elapsed=ch.end_elapsed,
                    start_margin=ch.start_margin, end_margin=ch.end_margin,
                    margin_swing=ch.margin_swing,
                    home_points=ch.home_points, away_points=ch.away_points,
                    label=ch.label, drivers=ch.drivers,
                ))
            session.commit()

    def load_chapters(self, game_id: str) -> list[Chapter]:
        """Read a game's saved chapters, ordered by chapter_idx. [] if none."""
        self._ensure_table()
        with SessionLocal() as session:
            rows = (session.query(GameChapter)
                    .filter(GameChapter.game_id == game_id)
                    .order_by(GameChapter.chapter_idx).all())
        return [Chapter(
            game_id=r.game_id, chapter_idx=r.chapter_idx,
            start_action_id=r.start_action_id, end_action_id=r.end_action_id,
            start_period=r.start_period, start_clock=r.start_clock,
            end_period=r.end_period, end_clock=r.end_clock,
            start_elapsed=r.start_elapsed, end_elapsed=r.end_elapsed,
            start_margin=r.start_margin, end_margin=r.end_margin,
            home_points=r.home_points, away_points=r.away_points,
            label=r.label or "", drivers=r.drivers or [],
        ) for r in rows]

    def segment_season(self, seasons: list[str] = None, overwrite: bool = False) -> dict:
        """
        Segment and save every game in the given season codes (same
        convention as train.py, e.g. "22024"; None = every game in the
        database). Skips games that already have chapters unless
        overwrite=True.

        Returns: {"segmented": int, "skipped": int, "failed": [game_id, ...]}
        """
        self._ensure_table()
        with SessionLocal() as session:
            query = session.query(Game.game_id)
            if seasons:
                query = query.filter(Game.season.in_(seasons))
            game_ids = sorted(g for (g,) in query.all())
            done = {g for (g,) in session.query(GameChapter.game_id).distinct().all()}

        summary = {"segmented": 0, "skipped": 0, "failed": []}
        for i, game_id in enumerate(game_ids):
            if game_id in done and not overwrite:
                summary["skipped"] += 1
                continue
            try:
                chapters = self.segment_game(game_id)
                if not chapters:
                    summary["skipped"] += 1
                    continue
                self.save_chapters(game_id, chapters)
                summary["segmented"] += 1
            except Exception as e:
                logger.error(f"Chapter segmentation failed for {game_id}: {e}")
                summary["failed"].append(game_id)
            if (i + 1) % 200 == 0:
                logger.info(f"Processed {i + 1}/{len(game_ids)} games")
        return summary
