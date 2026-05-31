"""
patterns/bull_flag.py — Détection du Bull Flag (drapeau haussier).

Structure : un « mât » (forte hausse) suivi d'un « drapeau » (consolidation
en repli léger à volume décroissant), puis cassure en volume.
"""

from . import base

DEFAULT_PARAMS = {
    "pole_min_gain": 0.10,
    "pole_max_candles": 15,
    "flag_max_depth": 0.50,
    "flag_min_candles": 3,
    "flag_max_candles": 20,
    "volume_contraction_ratio": 0.7,
    "breakout_volume_ratio": 1.5,
}


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "bull_flag"

    if df is None or len(df) < p["pole_max_candles"] + p["flag_min_candles"]:
        return base.make_result(name, False, notes="données insuffisantes")

    struct = base.find_flag_structure(
        df, p["pole_min_gain"], p["pole_max_candles"],
        p["flag_min_candles"], p["flag_max_candles"],
    )
    if not struct:
        return base.make_result(name, False, notes="pas de structure mât+drapeau")

    res_idx = struct["resistance_idx"]
    resistance = struct["resistance"]
    pole_range = resistance - struct["pole_low"]
    flag_low = struct["flag_low"]
    depth_frac = (resistance - flag_low) / pole_range if pole_range > 0 else 1.0

    # Contraction du volume : drapeau vs mât
    if "volume" in df:
        pole_lo_idx = res_idx - struct["pole_candles"]
        pole_vol = df["volume"].iloc[pole_lo_idx:res_idx + 1].mean()
        flag_vol = df["volume"].iloc[res_idx + 1:].mean()
        vol_contraction = (flag_vol / pole_vol) if pole_vol else 1.0
    else:
        vol_contraction = 1.0

    brk_ratio = base.last_breakout_volume_ratio(df, struct["flag_candles"])
    last_price = df["close"].iloc[-1]
    near_breakout = last_price >= resistance * 0.97
    breakout = last_price > resistance and brk_ratio >= p["breakout_volume_ratio"]

    detected = (
        depth_frac <= p["flag_max_depth"]
        and vol_contraction <= p["volume_contraction_ratio"] * 1.3  # tolérance
        and near_breakout
    )

    return base.make_result(
        name, detected,
        depth=round(depth_frac, 3), max_depth=p["flag_max_depth"],
        volume_ratio=round(vol_contraction, 3),
        breakout_volume_ratio=round(brk_ratio, 2),
        breakout=breakout,
        pole_gain=round(struct["pole_gain"], 3), pole_candles=struct["pole_candles"],
        base_candles=struct["flag_candles"],
        notes="" if detected else "structure incomplète",
    )
