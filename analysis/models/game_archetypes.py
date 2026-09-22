# analysis/models/game_archetypes.py
"""
Whole-game shape archetypes: cluster games by the shape of their entire
regulation-time margin curve (wire-to-wire, comeback, seesaw, blowout,
nailbiter, ...), then use each archetype to pick how many chapters
ChapterSegmenter should cut that game into.

This is a DIFFERENT kind of claim than chapter boundaries, and doesn't run
into the caution in chapter_segmentation.py's docstring. chapter_eda.py found
no more *within-game* regime structure (streaks, changepoints) than a
shuffled-scoring null model — that's about whether a game changed character
at some moment. Whole-game shape is not that question: a 30-point wire-to-wire
win and an 8-lead-change nailbiter are simply different curves by
construction, final margin and all. No null model is needed to say two curves
look different; clustering just organizes that variation.

Curve, from the eventual winner's perspective (so home/away is not a free
parameter of the shape): margin * sign(final_margin), resampled onto the same
fixed 30s grid ChapterSegmenter uses, truncated/padded to exactly one
regulation game (2880s / bin_seconds bins). Overtime is deliberately not
included in the curve — a game that reached OT is tied at the end of
regulation *by definition*, so the curve already ends near zero for those
games, which is the right signal ("this was close") without needing OT-length
bookkeeping.

Method:
  Cluster: KMeans over the resampled curves, k chosen by silhouette score
           over CANDIDATE_K.
  Label:   each cluster's centroid curve is turned into a deterministic
           heuristic label (final margin, biggest deficit, lead changes) —
           first-pass thresholds, meant to be revisited once real centroids
           have been inspected on a full season.
  K for chapters: each game's total variation of its margin drift
           ("complexity" — how much back-and-forth there was, independent of
           final margin) is averaged per cluster, then that per-cluster
           average is bucketed by global quantile into CHAPTER_K_BOUNDS
           (default 3..6, restoring the bounded range the original chapter
           skeleton had before it was fixed at K=4). One k per cluster, not
           per game, so games in the same archetype segment identically.

Pipeline:
    ChapterSegmenter (curves + drift) -> fit() [KMeans + labeling + k mapping]
        -> fit_and_save() persists game_archetypes and the fitted model
        -> classify_game() assigns a single new game against a loaded model
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from loguru import logger
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from analysis.models.chapter_segmentation import ChapterSegmenter, DEFAULT_BIN_SECONDS, REG_GAME_SECONDS
from data.storage.db import SessionLocal, engine
from data.storage.models import Game, GameArchetype as GameArchetypeORM

SAVED_DIR = Path(__file__).parent / "saved"

CANDIDATE_K       = range(3, 9)   # archetype counts to try; best by silhouette
CHAPTER_K_BOUNDS  = (3, 6)        # bounded range chapter count can vary over


@dataclass
class GameArchetype:
    """One game's archetype assignment. Mirrors the GameArchetype table."""
    game_id:       str
    archetype_id:  int
    label:         str
    k:             int
    complexity:    float
    model_version: str


def _winner_curve(segmenter: ChapterSegmenter, df, final_margin: float, n_reg_bins: int) -> np.ndarray:
    """Regulation-length margin curve from the eventual winner's perspective."""
    signal = segmenter.build_signal(df)
    margin = signal["margin"].to_numpy(dtype=float)
    curve = margin[:n_reg_bins] * (1.0 if final_margin > 0 else -1.0)
    if len(curve) < n_reg_bins:
        curve = np.pad(curve, (0, n_reg_bins - len(curve)), mode="edge")
    return curve


def _complexity(curve: np.ndarray) -> float:
    """Total variation of the curve's bin-to-bin drift — how much back-and-
    forth there was, independent of final margin or which side led."""
    drift = np.diff(np.concatenate([[0.0], curve]))
    return float(np.abs(drift).sum())


def _centroid_features(centroid: np.ndarray) -> dict:
    sign_seq = np.sign(centroid)
    sign_seq = sign_seq[sign_seq != 0]
    lead_changes = int((np.diff(sign_seq) != 0).sum()) if len(sign_seq) > 1 else 0
    return dict(final=float(centroid[-1]), min=float(centroid.min()), lead_changes=lead_changes)


def _label_from_features(feats: dict) -> str:
    """Deterministic, no LLM. First-pass thresholds — revisit once real
    cluster centroids from a full season have been inspected."""
    final, min_, lead_changes = feats["final"], feats["min"], feats["lead_changes"]
    if lead_changes >= 4:
        return "seesaw"
    if min_ <= -8 and final > 0:
        return "comeback"
    if min_ >= -3 and final >= 8:
        return "wire-to-wire"
    if final >= 15:
        return "blowout"
    if final <= 5:
        return "nailbiter"
    return "mixed"


class GameArchetypeClassifier:
    """
    Clusters whole-game margin-curve shapes and derives a chapter count per
    archetype.

    Typical use:
        clf = GameArchetypeClassifier()
        summary = clf.fit_and_save(["22024", "22025"])   # fits + persists
        clf.save_model()                                  # already done by fit_and_save

    Later, without refitting:
        clf = GameArchetypeClassifier.load_model()
        row = clf.classify_game("0022500002")
    """

    def __init__(
        self,
        candidate_k:      range = CANDIDATE_K,
        chapter_k_bounds: tuple = CHAPTER_K_BOUNDS,
        bin_seconds:      int   = DEFAULT_BIN_SECONDS,
    ):
        self.candidate_k = candidate_k
        self.chapter_k_bounds = chapter_k_bounds
        self.bin_seconds = bin_seconds
        self.n_reg_bins = REG_GAME_SECONDS // bin_seconds
        self.k_values = list(range(chapter_k_bounds[0], chapter_k_bounds[1] + 1))
        self.segmenter = ChapterSegmenter(bin_seconds=bin_seconds)

        self.model = None            # fitted sklearn KMeans
        self.n_clusters = None
        self.complexity_edges = None # quantile edges bucketing complexity -> k_values
        self.cluster_k = {}          # cluster_id -> chapter count
        self.cluster_label = {}      # cluster_id -> heuristic label
        self.model_version = None
        self._table_ready = False

    # ── Data ─────────────────────────────────────────────────────

    def _load_curves(self, seasons: list[str] = None) -> tuple[list[str], np.ndarray, np.ndarray]:
        """
        game_ids, curves (n_games x n_reg_bins), complexity (n_games,).
        Skips games with no play-by-play, truncated play-by-play (final score
        doesn't match the games table), or a tied final score (shouldn't
        happen in the NBA, but a winner-perspective curve is undefined for it).
        """
        with SessionLocal() as session:
            query = session.query(Game.game_id, Game.home_score, Game.away_score)
            if seasons:
                query = query.filter(Game.season.in_(seasons))
            rows = query.all()

        game_ids, curves, complexity = [], [], []
        for game_id, home_score, away_score in rows:
            if home_score is None or away_score is None:
                continue
            final_margin = home_score - away_score
            if final_margin == 0:
                continue
            df = self.segmenter.load_game_series(game_id)
            if df.empty:
                continue
            if (int(df["home_score"].iloc[-1]), int(df["away_score"].iloc[-1])) != (home_score, away_score):
                continue  # truncated play-by-play — same guard as ChapterSegmenter.segment_game
            curve = _winner_curve(self.segmenter, df, final_margin, self.n_reg_bins)
            game_ids.append(game_id)
            curves.append(curve)
            complexity.append(_complexity(curve))
        return game_ids, np.array(curves), np.array(complexity)

    # ── Fit ──────────────────────────────────────────────────────

    def fit(self, seasons: list[str] = None, random_state: int = 7) -> dict:
        """
        Fit KMeans (k chosen by silhouette over candidate_k), derive a
        deterministic label and a bounded chapter count per cluster.

        Returns a summary dict: n_games, silhouette, n_clusters, model_version,
        and per-cluster stats (n_games, mean_complexity, k, label).
        """
        game_ids, curves, complexity = self._load_curves(seasons)
        min_needed = max(self.candidate_k) * 5
        if len(game_ids) < min_needed:
            raise ValueError(f"Only {len(game_ids)} usable games; need at least {min_needed} to fit "
                              f"up to k={max(self.candidate_k)} clusters")

        best = None
        for k in self.candidate_k:
            km = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit(curves)
            score = silhouette_score(curves, km.labels_)
            if best is None or score > best[0]:
                best = (score, k, km)
        score, n_clusters, km = best

        labels = km.labels_
        edges = (np.quantile(complexity, np.linspace(0, 1, len(self.k_values) + 1)[1:-1])
                 if len(self.k_values) > 1 else np.array([]))

        cluster_k, cluster_label, cluster_stats = {}, {}, {}
        for c in range(n_clusters):
            mask = labels == c
            mean_complexity = float(complexity[mask].mean())
            bucket = min(int(np.searchsorted(edges, mean_complexity)), len(self.k_values) - 1)
            k_c = self.k_values[bucket]
            feats = _centroid_features(curves[mask].mean(axis=0))
            label = _label_from_features(feats)
            cluster_k[c] = k_c
            cluster_label[c] = label
            cluster_stats[c] = dict(n_games=int(mask.sum()), mean_complexity=mean_complexity, k=k_c, label=label)

        self.model = km
        self.n_clusters = n_clusters
        self.complexity_edges = edges
        self.cluster_k = cluster_k
        self.cluster_label = cluster_label
        self.model_version = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        # cached so fit_and_save doesn't reload/recompute what fit() just built
        self._fit_cache = (game_ids, labels, complexity)

        logger.info(f"Fit {n_clusters} archetypes on {len(game_ids)} games "
                    f"(silhouette={score:.3f}): {cluster_stats}")
        return dict(n_games=len(game_ids), silhouette=float(score), n_clusters=n_clusters,
                    model_version=self.model_version, clusters=cluster_stats)

    # ── Classify a single game against a fitted/loaded model ───────

    def classify_game(self, game_id: str) -> GameArchetype | None:
        """Assign one game to an already-fitted or loaded model's clusters."""
        if self.model is None:
            raise RuntimeError("No fitted model — call fit() or load_model() first")
        with SessionLocal() as session:
            game = session.get(Game, game_id)
        if game is None or game.home_score is None or game.away_score is None:
            logger.warning(f"Game {game_id} missing final score; skipping")
            return None
        final_margin = game.home_score - game.away_score
        if final_margin == 0:
            return None
        df = self.segmenter.load_game_series(game_id)
        if df.empty:
            return None
        if (int(df["home_score"].iloc[-1]), int(df["away_score"].iloc[-1])) != (game.home_score, game.away_score):
            logger.warning(f"Truncated play-by-play for {game_id}; skipping")
            return None

        curve = _winner_curve(self.segmenter, df, final_margin, self.n_reg_bins)
        complexity = _complexity(curve)
        cluster_id = int(self.model.predict(curve.reshape(1, -1))[0])
        return GameArchetype(
            game_id=game_id, archetype_id=cluster_id, label=self.cluster_label[cluster_id],
            k=self.cluster_k[cluster_id], complexity=complexity, model_version=self.model_version,
        )

    # ── Persistence: fitted model (pickle) ──────────────────────────

    def save_model(self, path: Path = None) -> Path:
        """Pickle this fitted classifier (KMeans + cluster->k/label mapping)
        so classify_game() can run later without refitting.

        joblib.dump/load is pickle-based (arbitrary code execution on load),
        but this only ever reads files this same codebase wrote to
        analysis/models/saved/ — same convention as win_probability.py's
        saved models. Never load an archetype_model_*.pkl from anywhere else.
        """
        import joblib
        if self.model is None:
            raise RuntimeError("Nothing fitted to save — call fit() first")
        SAVED_DIR.mkdir(parents=True, exist_ok=True)
        path = path or SAVED_DIR / f"archetype_model_{self.model_version}.pkl"
        joblib.dump(self, path)
        joblib.dump(self, SAVED_DIR / "archetype_model_latest.pkl")
        return path

    @classmethod
    def load_model(cls, path: Path = None) -> "GameArchetypeClassifier":
        import joblib
        path = path or (SAVED_DIR / "archetype_model_latest.pkl")
        return joblib.load(path)

    # ── Persistence: game_archetypes table ──────────────────────────

    def _ensure_table(self):
        if not self._table_ready:
            GameArchetypeORM.__table__.create(engine, checkfirst=True)
            self._table_ready = True

    def save_archetypes(self, rows: list[GameArchetype]) -> None:
        """Upsert rows by game_id (creates the table if missing)."""
        self._ensure_table()
        with SessionLocal() as session:
            for r in rows:
                session.merge(GameArchetypeORM(
                    game_id=r.game_id, archetype_id=r.archetype_id, label=r.label,
                    k=r.k, complexity=r.complexity, model_version=r.model_version,
                ))
            session.commit()

    def load_archetype(self, game_id: str) -> GameArchetype | None:
        """Read one game's saved archetype. None if it hasn't been classified."""
        self._ensure_table()
        with SessionLocal() as session:
            r = session.get(GameArchetypeORM, game_id)
        if r is None:
            return None
        return GameArchetype(game_id=r.game_id, archetype_id=r.archetype_id, label=r.label,
                              k=r.k, complexity=r.complexity, model_version=r.model_version)

    def fit_and_save(self, seasons: list[str] = None, save_model: bool = True) -> dict:
        """Fit on `seasons` (None = every game in the database), persist a
        game_archetypes row for every game that went into the fit, and by
        default pickle the fitted model too."""
        summary = self.fit(seasons)
        game_ids, labels, complexity = self._fit_cache
        rows = [
            GameArchetype(game_id=gid, archetype_id=int(c), label=self.cluster_label[int(c)],
                          k=self.cluster_k[int(c)], complexity=float(comp), model_version=self.model_version)
            for gid, c, comp in zip(game_ids, labels, complexity)
        ]
        self.save_archetypes(rows)
        if save_model:
            self.save_model()
        summary["saved_games"] = len(rows)
        return summary
