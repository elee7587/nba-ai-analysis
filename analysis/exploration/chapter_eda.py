# analysis/exploration/chapter_eda.py
"""
Exploratory analysis for game-chapter segmentation. Answers, with data,
whether the approach in analysis/models/chapter_segmentation.py is sound
before it gets built:

  1. Is the play-by-play clean enough to build a margin time series from?
  2. Is there run structure in scoring beyond what chance produces?
     (autocorrelation + variance ratio, real vs. within-game shuffled)
  3. Does a prototype dynamic-programming segmenter find a sensible number
     of chapters, and does it find *fewer* in shuffled (structureless) games?
  4. Are boundaries stable across time-bin sizes?
  5. What do chapters look like on real games? (figures)

Run from the repo root:   python analysis/exploration/chapter_eda.py
Writes figures + summary.json to output/chapter_eda/ (gitignored).
Does NOT use the win-probability model (see summary: it currently cannot
score a game, and was trained on features with the score zeroed out).
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data.storage.db import engine
from data.team_lookup import get_abbr

engine.echo = False

OUT = Path("output/chapter_eda")
OUT.mkdir(parents=True, exist_ok=True)

SEASONS        = ["22024", "42024", "22025", "42025"]
BIN_SECONDS    = 30
MIN_CHAPTER_S  = 240
PENALTY_GRID   = [0.5, 1, 2, 3, 5, 8]      # c in: penalty = c * sigma^2 * ln(n_bins)
FIXED_K        = 4                         # descriptive segmentation: ask for K chapters outright
SWEEP_GAMES    = 600
TARGET_CHAPTERS = (3, 6)
HOME_COLOR, AWAY_COLOR = "#6b7680", "#eb6834"
RNG = np.random.default_rng(7)


# ── Loading & preparation ────────────────────────────────────────

def load_data():
    plays = pd.read_sql(
        """select p.game_id, p.action_id, p.period, p.clock,
                  p.home_score, p.away_score
           from play_by_play p join games g on g.game_id = p.game_id
           where g.season = any(%(s)s)
           order by p.game_id, p.action_id""",
        engine, params={"s": SEASONS})
    games = pd.read_sql(
        """select game_id, game_date, home_team, away_team, home_score, away_score, season
           from games where season = any(%(s)s)""",
        engine, params={"s": SEASONS}).set_index("game_id")
    parts = plays.clock.str.extract(r"PT(\d+)M([\d.]+)S").astype(float)
    remaining = parts[0] * 60 + parts[1]
    plays["elapsed"] = np.where(
        plays.period <= 4,
        (plays.period - 1) * 720 + (720 - remaining),
        2880 + (plays.period - 5) * 300 + (300 - remaining))
    return plays, games


def per_game_series(plays):
    """game_id -> dict(elapsed, margin, periods, n_plays, clock_nan, elapsed_decreases)"""
    out = {}
    for gid, g in plays.groupby("game_id", sort=False):
        hs = g.home_score.ffill().fillna(0).to_numpy()
        as_ = g.away_score.ffill().fillna(0).to_numpy()
        el = g.elapsed.to_numpy()
        out[gid] = dict(
            elapsed=np.maximum.accumulate(np.nan_to_num(el)),
            margin=hs - as_,
            home=hs, away=as_,
            periods=int(g.period.max()),
            n_plays=len(g),
            clock_nan=int(np.isnan(el).sum()),
            elapsed_decreases=int((np.diff(el[~np.isnan(el)]) < 0).sum()),
        )
    return out


def to_grid(s, bin_s=BIN_SECONDS):
    """Fixed time grid: margin at the end of each bin (last play at or before
    the bin edge) and the drift (margin change) within each bin."""
    total = 2880 + 300 * max(0, s["periods"] - 4)
    edges = np.arange(bin_s, total + 1e-9, bin_s)
    idx = np.searchsorted(s["elapsed"], edges, side="right") - 1
    m = np.where(idx >= 0, s["margin"][np.clip(idx, 0, None)], 0.0)
    return np.diff(np.concatenate([[0.0], m])), m, edges


# ── Prototype segmenter (optimal partitioning, mean-shift on drift) ──

def segment(x, pen, min_size):
    """Optimal partition of x into segments minimising
    sum(within-segment squared error) + pen * (n_segments - 1),
    each segment at least min_size long. Returns segment start indices."""
    n = len(x)
    if n < min_size:
        return [0]
    cs = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])
    F = np.full(n + 1, np.inf)
    F[0] = -pen
    last = np.zeros(n + 1, dtype=int)
    for j in range(min_size, n + 1):
        starts = np.arange(0, j - min_size + 1)
        length = j - starts
        cost = cs2[j] - cs2[starts] - (cs[j] - cs[starts]) ** 2 / length
        tot = F[starts] + cost + pen
        k = int(np.argmin(tot))
        F[j], last[j] = tot[k], starts[k]
    bounds, j = [], n
    while j > 0:
        bounds.append(last[j])
        j = last[j]
    return sorted(bounds)


def segment_k(x, K, min_size):
    """Optimal partition of x into exactly K segments (each >= min_size)
    minimising within-segment squared error. Descriptive: it always returns K
    chapters and makes no claim they are statistically distinct."""
    n = len(x)
    K = max(1, min(K, n // min_size))
    cs = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])
    D = np.full((K + 1, n + 1), np.inf)
    D[0, 0] = 0.0
    P = np.zeros((K + 1, n + 1), dtype=int)
    for k in range(1, K + 1):
        for j in range(k * min_size, n + 1):
            starts = np.arange((k - 1) * min_size, j - min_size + 1)
            length = j - starts
            cost = cs2[j] - cs2[starts] - (cs[j] - cs[starts]) ** 2 / length
            tot = D[k - 1, starts] + cost
            i = int(np.argmin(tot))
            D[k, j], P[k, j] = tot[i], starts[i]
    bounds, j = [], n
    for k in range(K, 0, -1):
        bounds.append(P[k, j])
        j = P[k, j]
    return sorted(bounds)


def game_penalty(x, c):
    sigma2 = np.var(np.diff(x)) / 2 if len(x) > 2 else 1.0   # noise level, robust-ish to mean shifts
    return c * max(sigma2, 1e-6) * np.log(len(x))


def chapters_from(x, starts):
    ends = starts[1:] + [len(x)]
    return [(s, e, float(x[s:e].sum())) for s, e in zip(starts, ends)]   # (start_bin, end_bin, margin swing)


# ── Analyses ─────────────────────────────────────────────────────

def data_quality(series, games):
    rows = []
    for gid, s in series.items():
        gm = games.loc[gid] if gid in games.index else None
        final_pbp = s["margin"][-1]
        final_tbl = (gm.home_score - gm.away_score) if gm is not None and pd.notna(gm.home_score) else np.nan
        rows.append(dict(game_id=gid, n_plays=s["n_plays"], periods=s["periods"],
                         clock_nan=s["clock_nan"], elapsed_decreases=s["elapsed_decreases"],
                         final_matches=(final_pbp == final_tbl) if not np.isnan(final_tbl) else np.nan))
    q = pd.DataFrame(rows)
    return dict(
        games=len(q),
        plays_min_median_max=[int(q.n_plays.min()), int(q.n_plays.median()), int(q.n_plays.max())],
        overtime_games=int((q.periods > 4).sum()),
        games_with_unparseable_clock=int((q.clock_nan > 0).sum()),
        games_with_time_going_backwards=int((q.elapsed_decreases > 0).sum()),
        final_score_matches_games_table=float(q.final_matches.mean()),
        games_missing_from_games_table=int(q.final_matches.isna().sum()),
    ), q


def structure_tests(series):
    """Autocorrelation of 30s drift and variance ratio of margin increments,
    real vs. within-game shuffled. VR(k) > 1 means scoring is streakier than chance."""
    drifts = [to_grid(s)[0] for s in series.values()]
    ks = [1, 2, 4, 8, 16, 32]
    def vr(dlist):
        var1 = np.concatenate(dlist).var()
        out = {}
        for k in ks:
            incs = np.concatenate([np.convolve(d, np.ones(k), mode="valid") for d in dlist if len(d) >= k])
            out[k] = float(incs.var() / (k * var1))
        return out
    def acf(dlist, lags=range(1, 9)):
        allx = np.concatenate(dlist); mu, v = allx.mean(), allx.var()
        res = {}
        for L in lags:
            num = sum(((d[:-L] - mu) * (d[L:] - mu)).sum() for d in dlist)
            den = sum(len(d) - L for d in dlist)
            res[L] = float(num / den / v)
        return res
    shuffled = [RNG.permutation(d) for d in drifts]
    return dict(acf_real=acf(drifts), acf_shuffled=acf(shuffled),
                vr_real=vr(drifts), vr_shuffled=vr(shuffled))


def sweep(series, ids):
    """Chapter counts / swings for real vs shuffled games across the penalty grid."""
    min_size = MIN_CHAPTER_S // BIN_SECONDS
    rows, swings = [], {}
    for c in PENALTY_GRID:
        kr, kn, sr, sn, lens = [], [], [], [], []
        for gid in ids:
            x = to_grid(series[gid])[0]
            pen = game_penalty(x, c)
            cr = chapters_from(x, segment(x, pen, min_size))
            xn = RNG.permutation(x)
            cn = chapters_from(xn, segment(xn, pen, min_size))
            kr.append(len(cr)); kn.append(len(cn))
            sr += [abs(w) for _, _, w in cr]; sn += [abs(w) for _, _, w in cn]
            lens += [(e - s) * BIN_SECONDS / 60 for s, e, _ in cr]
        inr = lambda k: float(np.mean([TARGET_CHAPTERS[0] <= v <= TARGET_CHAPTERS[1] for v in k]))
        rows.append(dict(c=c, mean_K_real=np.mean(kr), mean_K_shuffled=np.mean(kn),
                         pct_3to6_real=inr(kr), pct_3to6_shuffled=inr(kn),
                         median_len_min_real=float(np.median(lens)),
                         median_abs_swing_real=float(np.median(sr)), median_abs_swing_shuffled=float(np.median(sn))))
        swings[c] = (kr, kn, sr, sn)
    return pd.DataFrame(rows), swings


def bin_sensitivity(series, ids, c):
    """Chapter counts and boundary agreement across bin sizes at penalty c."""
    res, bounds = {}, {}
    for b in (15, 30, 60):
        ks, bl = [], {}
        for gid in ids:
            x, _, edges = to_grid(series[gid], b)
            st = segment(x, game_penalty(x, c), max(1, MIN_CHAPTER_S // b))
            ks.append(len(st)); bl[gid] = [float(edges[s - 1]) for s in st if s > 0]   # boundary time in seconds
        res[b] = float(np.mean(ks)); bounds[b] = bl
    def agree(a, b, tol=90):
        hit = tot = 0
        for gid in ids:
            for t in bounds[a][gid]:
                tot += 1
                hit += any(abs(t - u) <= tol for u in bounds[b][gid])
        return hit / tot if tot else float("nan")
    return dict(mean_K=res, boundary_agreement_within_90s={"60s_vs_30s": agree(60, 30), "15s_vs_30s": agree(15, 30),
                                                          "30s_vs_60s": agree(30, 60)})


def max_window_test(series, window_minutes=(4, 6, 12)):
    """Is the biggest run in a real game bigger than in the same game with its
    30s drifts shuffled? Compares per-game max |margin change| over a sliding window."""
    res = {}
    for wm in window_minutes:
        k = int(wm * 60 // BIN_SECONDS)
        real, shuf, bigger = [], [], []
        for s in series.values():
            x = to_grid(s)[0]
            def mx(v):
                cs = np.concatenate([[0.0], np.cumsum(v)])
                return np.abs(cs[k:] - cs[:-k]).max()
            r = mx(x)
            nulls = [mx(RNG.permutation(x)) for _ in range(20)]
            real.append(r); shuf.append(np.mean(nulls)); bigger.append(np.mean([r > v for v in nulls]))
        res[f"{wm}min"] = dict(median_max_swing_real=float(np.median(real)),
                               median_max_swing_shuffled=float(np.median(shuf)),
                               mean_share_of_shuffles_real_exceeds=float(np.mean(bigger)))
    return res


def fixed_k_stability(series, ids, K=FIXED_K):
    """Do K-chapter boundaries land in the same place at 15/30/60s bins?
    Chance baseline: probability a random boundary is within tol of one of K-1 others."""
    bounds = {}
    for b in (15, 30, 60):
        bl = {}
        for gid in ids:
            x, _, edges = to_grid(series[gid], b)
            st = segment_k(x, K, max(1, MIN_CHAPTER_S // b))
            bl[gid] = [float(s * b) for s in st if s > 0]
        bounds[b] = bl
    def agree(a, b, tol=90):
        hit = tot = 0
        for gid in ids:
            for t in bounds[a][gid]:
                tot += 1
                hit += any(abs(t - u) <= tol for u in bounds[b][gid])
        return hit / tot
    chance = 1 - (1 - 2 * 90 / 2880) ** (K - 1)
    return dict(K=K, agreement_within_90s={"15s_vs_30s": agree(15, 30), "60s_vs_30s": agree(60, 30)},
                chance_baseline=float(chance))


def pick_sample_games(series, games):
    stats = []
    for gid, s in series.items():
        m = s["margin"]
        final = m[-1]
        deficit = (-m.min() if final > 0 else m.max()) if final != 0 else 0
        sign = np.sign(m[m != 0])
        stats.append(dict(game_id=gid, final=final, comeback=deficit, ot=s["periods"] > 4,
                          lead_changes=int((np.diff(sign) != 0).sum()) if len(sign) > 1 else 0))
    d = pd.DataFrame(stats)
    picks = {
        "Biggest comeback": d.sort_values("comeback").iloc[-1].game_id,
        "Biggest blowout": d.reindex(d.final.abs().sort_values().index).iloc[-1].game_id,
        "Closest, most lead changes": d[d.final.abs() <= 3].sort_values("lead_changes").iloc[-1].game_id,
        "Overtime": d[d.ot & (d.game_id != d[d.final.abs() <= 3].sort_values("lead_changes").iloc[-1].game_id)]
                     .sort_values("lead_changes").iloc[-1].game_id,
    }
    rest = d[~d.game_id.isin(picks.values())].game_id.to_numpy()
    for i, gid in enumerate(RNG.choice(rest, 2, replace=False)):
        picks[f"Random {i + 1}"] = gid
    return picks


# ── Figures ──────────────────────────────────────────────────────

def fig_structure(st, sweep_df, swings, c_star):
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    lags = list(st["acf_real"])
    w = 0.38
    ax[0, 0].bar(np.array(lags) - w / 2, list(st["acf_real"].values()), w, label="real", color=AWAY_COLOR)
    ax[0, 0].bar(np.array(lags) + w / 2, list(st["acf_shuffled"].values()), w, label="shuffled", color=HOME_COLOR)
    ax[0, 0].set(title="Autocorrelation of 30s margin drift", xlabel="lag (30s bins)"); ax[0, 0].legend()
    ks = list(st["vr_real"])
    ax[0, 1].plot(ks, list(st["vr_real"].values()), "o-", color=AWAY_COLOR, label="real")
    ax[0, 1].plot(ks, list(st["vr_shuffled"].values()), "o-", color=HOME_COLOR, label="shuffled")
    ax[0, 1].axhline(1, color="k", lw=.5); ax[0, 1].set_xscale("log", base=2)
    ax[0, 1].set(title="Variance ratio VR(k)  (>1 = streakier than chance)", xlabel="window k (30s bins)"); ax[0, 1].legend()
    kr, kn, sr, sn = swings[c_star]
    bins = np.arange(0.5, 12.5)
    ax[1, 0].hist([kr, kn], bins=bins, label=["real", "shuffled"], color=[AWAY_COLOR, HOME_COLOR])
    ax[1, 0].set(title=f"Chapters per game (penalty c={c_star})", xlabel="chapters"); ax[1, 0].legend()
    ax[1, 1].hist([sr, sn], bins=np.arange(0, 32, 2), label=["real", "shuffled"], color=[AWAY_COLOR, HOME_COLOR], density=True)
    ax[1, 1].set(title="|Margin swing| per chapter (points)", xlabel="points"); ax[1, 1].legend()
    fig.tight_layout(); fig.savefig(OUT / "structure_tests.png", dpi=130); plt.close(fig)


def fig_sample_games(series, games, picks):
    fig, axes = plt.subplots(3, 2, figsize=(15, 13))
    min_size = MIN_CHAPTER_S // BIN_SECONDS
    for a, (title, gid) in zip(axes.ravel(), picks.items()):
        s = series[gid]
        x, m, edges = to_grid(s)
        st = segment_k(x, FIXED_K, min_size)
        chs = chapters_from(x, st)
        a.step(np.concatenate([[0], edges]) / 60, np.concatenate([[0], m]), where="post", color="k", lw=1.2)
        a.axhline(0, color="k", lw=.4)
        for (sb, eb, sw) in chs:
            t0, t1 = sb * BIN_SECONDS / 60, eb * BIN_SECONDS / 60
            a.axvspan(t0, t1, color=HOME_COLOR if sw >= 0 else AWAY_COLOR, alpha=.18)
            a.text((t0 + t1) / 2, a.get_ylim()[1] * .92, f"{sw:+.0f}", ha="center", va="top", fontsize=9, weight="bold")
        for q in (12, 24, 36):
            a.axvline(q, color="k", lw=.5, ls=":")
        g = games.loc[gid]
        a.set(title=f"{title}: {get_abbr(g.away_team)} @ {get_abbr(g.home_team)} {int(g.away_score)}-{int(g.home_score)}  ({len(chs)} chapters)",
              xlabel="game minute", ylabel="home margin")
    fig.suptitle(f"Descriptive chapters: exactly K={FIXED_K} (bin={BIN_SECONDS}s, min length={MIN_CHAPTER_S // 60} min); "
                 f"gray = home gained, orange = away gained; number = margin swing", y=.995)
    fig.tight_layout(); fig.savefig(OUT / "sample_games.png", dpi=130); plt.close(fig)


# ── Main ─────────────────────────────────────────────────────────

def main():
    plays, games = load_data()
    series = per_game_series(plays)
    print(f"loaded {len(plays):,} plays across {len(series):,} games\n")

    quality, _ = data_quality(series, games)
    print("== 1. DATA QUALITY =="); print(json.dumps(quality, indent=2))

    st = structure_tests(series)
    print("\n== 2. STRUCTURE (real vs within-game shuffled) ==")
    print("lag-1..8 autocorr real:    ", [round(v, 3) for v in st["acf_real"].values()])
    print("lag-1..8 autocorr shuffled:", [round(v, 3) for v in st["acf_shuffled"].values()])
    print("variance ratio real:    ", {k: round(v, 2) for k, v in st["vr_real"].items()})
    print("variance ratio shuffled:", {k: round(v, 2) for k, v in st["vr_shuffled"].items()})

    ids = list(RNG.choice(list(series), SWEEP_GAMES, replace=False))
    sweep_df, swings = sweep(series, ids)
    print(f"\n== 3. SEGMENTATION SWEEP ({SWEEP_GAMES} games, bin={BIN_SECONDS}s, min chapter={MIN_CHAPTER_S // 60} min) ==")
    print(sweep_df.round(2).to_string(index=False))

    c_star = PENALTY_GRID[0]   # most permissive penalty; used for the histograms and sensitivity check
    mw = max_window_test(series)
    print("\n== 3b. BIGGEST RUN: REAL vs SHUFFLED (all games) =="); print(json.dumps(mw, indent=2))

    sens = bin_sensitivity(series, ids[:300], c_star)
    print(f"\n== 4. BIN-SIZE SENSITIVITY (penalty c={c_star}) =="); print(json.dumps(sens, indent=2))
    fk = fixed_k_stability(series, ids[:300])
    print(f"\n== 4b. FIXED-K (K={FIXED_K}) BOUNDARY STABILITY =="); print(json.dumps(fk, indent=2))

    picks = pick_sample_games(series, games)
    print("\n== 5. SAMPLE GAMES =="); print(json.dumps(picks, indent=2, default=str))
    fig_structure(st, sweep_df, swings, c_star)
    fig_sample_games(series, games, picks)

    json.dump(dict(quality=quality, structure=st, sweep=sweep_df.to_dict("records"), c_star=c_star,
                   bin_sensitivity=sens, max_window=mw, fixed_k_stability=fk,
                   sample_games={k: str(v) for k, v in picks.items()}),
              open(OUT / "summary.json", "w"), indent=2, default=float)
    print(f"\nwrote figures + summary.json to {OUT}/")


if __name__ == "__main__":
    main()
