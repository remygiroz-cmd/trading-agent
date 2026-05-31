"""
patterns/double_bottom.py — Double Bottom (double creux, forme en W).

Deux creux à un niveau proche (3% près), idéalement le 2e légèrement plus haut,
séparés d'au moins 10 bougies, avec cassure du pic médian en volume.
"""

import numpy as np

from . import base

DEFAULT_PARAMS = {
    "tolerance": 0.03,
    "second_bottom_higher": True,
    "min_distance_candles": 10,
    "breakout_volume_ratio": 1.5,
    "swing_window": 3,
}


def _local_minima(values: np.ndarray, window: int):
    out = []
    for i in range(window, len(values) - window):
        if values[i] == values[i - window:i + window + 1].min():
            out.append(i)
    return out


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "double_bottom"

    if df is None or len(df) < p["min_distance_candles"] + 10:
        return base.make_result(name, False, notes="données insuffisantes")

    closes = df["close"].values
    lows = df["low"].values if "low" in df else closes
    highs = df["high"].values if "high" in df else closes

    minima = _local_minima(lows, p["swing_window"])
    if len(minima) < 2:
        return base.make_result(name, False, notes="moins de 2 creux")

    # On considère les deux creux les plus récents suffisamment espacés
    b2 = minima[-1]
    b1 = None
    for idx in reversed(minima[:-1]):
        if b2 - idx >= p["min_distance_candles"]:
            b1 = idx
            break
    if b1 is None:
        return base.make_result(name, False, notes="creux trop rapprochés")

    low1, low2 = lows[b1], lows[b2]
    diff = abs(base.pct(low2, low1))
    if diff > p["tolerance"]:
        return base.make_result(name, False, depth=round(diff, 3),
                                notes=f"creux trop écartés ({diff*100:.1f}%)")

    # Pic médian (résistance à casser)
    mid_peak = highs[b1:b2 + 1].max()
    last_price = closes[-1]

    second_higher_ok = (low2 >= low1) if p["second_bottom_higher"] else True

    brk_ratio = base.last_breakout_volume_ratio(df, b2 - b1)
    near_breakout = last_price >= mid_peak * 0.97
    breakout = last_price > mid_peak and brk_ratio >= p["breakout_volume_ratio"]

    # profondeur du W = repli du pic médian au creux (pour le scoring)
    w_depth = base.pct(mid_peak, min(low1, low2))

    detected = bool(second_higher_ok and near_breakout)

    return base.make_result(
        name, detected,
        depth=round(min(diff, 0.05), 3), max_depth=p["tolerance"],
        volume_ratio=0.7,
        breakout_volume_ratio=round(brk_ratio, 2),
        breakout=breakout,
        base_candles=b2 - b1,
        notes=("" if detected else "cassure pic médian non confirmée"),
    )
