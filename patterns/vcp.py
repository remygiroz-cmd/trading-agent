"""
patterns/vcp.py — Volatility Contraction Pattern (Minervini).

Suite de contractions de plus en plus serrées (chaque repli < 60% du
précédent), la dernière très étroite (< 10%), avec assèchement du volume.
Signale qu'une cassure imminente est probable.
"""

import numpy as np

from . import base

DEFAULT_PARAMS = {
    "min_contractions": 3,
    "max_contractions": 6,
    "contraction_ratio": 0.6,
    "final_depth_max": 0.10,
    "volume_dry_up": 0.5,
    "swing_window": 3,
}


def _find_swings(values: np.ndarray, window: int):
    """Repère les sommets et creux locaux (extrema sur +/- window)."""
    highs, lows = [], []
    for i in range(window, len(values) - window):
        seg = values[i - window:i + window + 1]
        if values[i] == seg.max():
            highs.append(i)
        if values[i] == seg.min():
            lows.append(i)
    return highs, lows


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "vcp"

    if df is None or len(df) < 30:
        return base.make_result(name, False, notes="données insuffisantes")

    closes = df["close"].values
    w = p["swing_window"]
    highs, lows = _find_swings(closes, w)

    # Construire la séquence de contractions = repli de chaque sommet au creux suivant
    pivots = sorted(highs + lows)
    contractions = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        if closes[a] > closes[b]:  # repli
            depth = base.pct(closes[a], closes[b])
            if depth > 0.01:
                contractions.append(depth)

    # Garder les dernières contractions
    contractions = contractions[-p["max_contractions"]:]
    if len(contractions) < p["min_contractions"]:
        return base.make_result(name, False, notes=f"{len(contractions)} contractions (<min)")

    # Vérifier le rétrécissement progressif
    decreasing = all(
        contractions[i + 1] <= contractions[i] * (p["contraction_ratio"] + 0.25)
        for i in range(len(contractions) - 1)
    )
    final_depth = contractions[-1]
    final_ok = final_depth <= p["final_depth_max"] * 1.5  # tolérance

    # Assèchement du volume : volume récent vs moyenne
    if "volume" in df:
        recent_vol = df["volume"].tail(w + 2).mean()
        avg_vol = df["volume"].tail(40).mean()
        vol_dry = (recent_vol / avg_vol) if avg_vol else 1.0
    else:
        vol_dry = 1.0

    detected = bool(decreasing and final_ok and vol_dry <= p["volume_dry_up"] * 1.6)

    return base.make_result(
        name, detected,
        depth=round(final_depth, 3), max_depth=p["final_depth_max"],
        volume_ratio=round(vol_dry, 3),
        breakout_volume_ratio=round(base.last_breakout_volume_ratio(df, 5), 2),
        breakout=closes[-1] >= closes[-w - 2:].max() * 0.99,
        base_candles=len(contractions),
        notes=("" if detected else
               f"{len(contractions)} contr., finale={final_depth:.2f}, vol={vol_dry:.2f}"),
    )
