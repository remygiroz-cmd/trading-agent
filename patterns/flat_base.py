"""
patterns/flat_base.py — Flat Base (base plate).

Consolidation latérale serrée (amplitude <= 15%) sur >= 5 semaines, à volume
calme, suivie d'une cassure du haut de la base en volume.
"""

from . import base

DEFAULT_PARAMS = {
    "min_candles": 25,        # ~5 semaines
    "max_depth": 0.15,        # amplitude max de la base
    "volume_quiet": 0.8,      # volume base < 0.8x volume précédent
    "breakout_volume_ratio": 1.4,
}


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "flat_base"

    win = p["min_candles"]
    if df is None or len(df) < win + 5:
        return base.make_result(name, False, notes="données insuffisantes")

    closes = df["close"].values
    highs = df["high"].values if "high" in df else closes
    lows = df["low"].values if "low" in df else closes

    # La base = les `win` bougies précédant la dernière (qui peut être la cassure)
    base_high = highs[-(win + 1):-1].max()
    base_low = lows[-(win + 1):-1].min()
    amplitude = base.pct(base_high, base_low) if base_low > 0 else 1.0

    # Volume calme pendant la base vs avant la base
    if "volume" in df and len(df) >= 2 * win:
        base_vol = df["volume"].iloc[-(win + 1):-1].mean()
        prior_vol = df["volume"].iloc[-(2 * win):-(win + 1)].mean()
        vol_quiet = (base_vol / prior_vol) if prior_vol else 1.0
    else:
        vol_quiet = 1.0

    brk_ratio = base.last_breakout_volume_ratio(df, win)
    last_price = closes[-1]
    near_breakout = last_price >= base_high * 0.98
    breakout = last_price > base_high and brk_ratio >= p["breakout_volume_ratio"]

    detected = (
        amplitude <= p["max_depth"]
        and vol_quiet <= p["volume_quiet"] * 1.3
        and near_breakout
    )

    return base.make_result(
        name, detected,
        depth=round(amplitude, 3), max_depth=p["max_depth"],
        volume_ratio=round(vol_quiet, 3),
        breakout_volume_ratio=round(brk_ratio, 2),
        breakout=breakout,
        base_candles=win,
        notes="" if detected else "base non conforme",
    )
