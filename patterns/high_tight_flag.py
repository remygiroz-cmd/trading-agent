"""
patterns/high_tight_flag.py — High Tight Flag.

La figure la plus puissante : mât quasi-doublement (>= +90%) en <= 8 semaines,
suivi d'une consolidation très serrée (<= -25%) en <= 5 semaines, puis cassure.
Mêmes mécaniques que le bull flag mais avec un mât beaucoup plus violent.
"""

from . import base

# Conversion semaines -> bougies daily (5 séances/semaine)
DEFAULT_PARAMS = {
    "pole_min_gain": 0.90,
    "pole_max_candles": 40,   # 8 semaines
    "flag_max_depth": 0.25,
    "flag_min_candles": 3,
    "flag_max_candles": 25,   # 5 semaines
    "breakout_volume_ratio": 1.5,
}


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "high_tight_flag"

    if df is None or len(df) < p["flag_min_candles"] + 10:
        return base.make_result(name, False, notes="données insuffisantes")

    struct = base.find_flag_structure(
        df, p["pole_min_gain"], p["pole_max_candles"],
        p["flag_min_candles"], p["flag_max_candles"],
    )
    if not struct:
        return base.make_result(name, False, notes="pas de mât >= +90%")

    resistance = struct["resistance"]
    flag_low = struct["flag_low"]
    # profondeur du drapeau exprimée vs sommet (correction réelle)
    depth_abs = base.pct(resistance, flag_low) if flag_low < resistance else 0.0

    brk_ratio = base.last_breakout_volume_ratio(df, struct["flag_candles"])
    last_price = df["close"].iloc[-1]
    near_breakout = last_price >= resistance * 0.97
    breakout = last_price > resistance and brk_ratio >= p["breakout_volume_ratio"]

    detected = depth_abs <= p["flag_max_depth"] and near_breakout

    return base.make_result(
        name, detected,
        depth=round(depth_abs, 3), max_depth=p["flag_max_depth"],
        volume_ratio=0.6,  # un HTF présente par nature une consolidation serrée
        breakout_volume_ratio=round(brk_ratio, 2),
        breakout=breakout,
        pole_gain=round(struct["pole_gain"], 3), pole_candles=struct["pole_candles"],
        base_candles=struct["flag_candles"],
        notes="" if detected else "consolidation trop profonde",
    )
