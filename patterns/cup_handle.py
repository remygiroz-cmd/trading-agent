"""
patterns/cup_handle.py — Cup & Handle (tasse avec anse).

Base arrondie en U (la tasse) suivie d'une petite consolidation près du bord
droit (l'anse), puis cassure du bord de la tasse en volume.

Détection sur données daily : les durées en semaines des specs sont converties
en séances (5/semaine). Sur 90 jours, on couvre jusqu'à ~13 semaines de tasse.
"""

import numpy as np

from . import base

DEFAULT_PARAMS = {
    "cup_min_candles": 20,    # ~4 semaines
    "cup_max_candles": 130,   # plafonné par l'historique daily dispo
    "cup_max_depth": 0.50,
    "cup_rounding_score": 0.6,
    "handle_max_depth": 0.15,
    "handle_max_candles": 25, # ~5 semaines
    "breakout_volume_ratio": 1.5,
}


def _rounding_score(segment: np.ndarray) -> float:
    """
    Mesure à quel point un creux est « arrondi » (vs en V).
    Compare le creux réel à une parabole ajustée. Retourne 0-1.
    """
    n = len(segment)
    if n < 5:
        return 0.0
    x = np.arange(n)
    # ajustement parabolique
    coeffs = np.polyfit(x, segment, 2)
    fit = np.polyval(coeffs, x)
    ss_res = np.sum((segment - fit) ** 2)
    ss_tot = np.sum((segment - segment.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    # parabole ouverte vers le haut (a>0) = forme de tasse
    shape = 1.0 if coeffs[0] > 0 else 0.0
    return max(0.0, min(1.0, r2 * shape))


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "cup_handle"

    if df is None or len(df) < p["cup_min_candles"] + 5:
        return base.make_result(name, False, notes="données insuffisantes")

    closes = df["close"].values
    highs = df["high"].values if "high" in df else closes
    lows = df["low"].values if "low" in df else closes
    n = len(df)

    # Bord gauche = plus haut sur la fenêtre tasse ; creux = plus bas ; bord droit = récent
    cup_window = min(p["cup_max_candles"], n - 1)
    seg_start = n - cup_window
    seg_close = closes[seg_start:]
    seg_low = lows[seg_start:]

    left_peak = seg_close[0]
    trough_idx_local = int(np.argmin(seg_low))
    trough = seg_low[trough_idx_local]
    # bord droit = sommet de la 2e moitié (avant l'anse)
    right_half = seg_close[trough_idx_local:]
    right_peak = right_half.max() if len(right_half) else left_peak

    cup_depth = base.pct(max(left_peak, right_peak), trough)
    if cup_depth > p["cup_max_depth"] or cup_depth < 0.08:
        return base.make_result(name, False, depth=round(cup_depth, 3),
                                max_depth=p["cup_max_depth"], notes="profondeur tasse hors plage")

    # symétrie des bords (les deux bords proches)
    rim_symmetry = 1 - abs(base.pct(right_peak, left_peak))
    rounding = _rounding_score(seg_low[:trough_idx_local + max(3, trough_idx_local)] if trough_idx_local > 2 else seg_low)

    # Anse : repli depuis le bord droit, peu profond
    rim = max(left_peak, right_peak)
    last_price = closes[-1]
    handle_low = lows[-p["handle_max_candles"]:].min()
    handle_depth = base.pct(rim, handle_low) if handle_low < rim else 0.0

    brk_ratio = base.last_breakout_volume_ratio(df, p["handle_max_candles"])
    near_breakout = last_price >= rim * 0.97
    breakout = last_price > rim and brk_ratio >= p["breakout_volume_ratio"]

    detected = (
        rounding >= p["cup_rounding_score"]
        and rim_symmetry >= 0.85
        and handle_depth <= p["handle_max_depth"]
        and near_breakout
    )

    return base.make_result(
        name, detected,
        depth=round(handle_depth, 3), max_depth=p["handle_max_depth"],
        volume_ratio=0.7,
        breakout_volume_ratio=round(brk_ratio, 2),
        breakout=breakout,
        base_candles=cup_window,
        notes=("" if detected else
               f"rounding={rounding:.2f} sym={rim_symmetry:.2f} anse={handle_depth:.2f}"),
    )
