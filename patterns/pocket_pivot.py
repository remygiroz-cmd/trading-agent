"""
patterns/pocket_pivot.py — Pocket Pivot.

Signal d'entrée intra-base : une bougie haussière dont le volume dépasse le
volume du plus fort jour BAISSIER des 10 dernières séances, avec prix au-dessus
des MA10 et MA50.
"""

import pandas as pd

from . import base

DEFAULT_PARAMS = {
    "lookback_down_days": 10,
    "min_volume_vs_down_days": 1.0,
    "price_above_ma10": True,
    "price_above_ma50": True,
    # Garde-fou : un vrai pocket pivot se déclenche PRÈS de la MA10, pas après
    # une envolée parabolique. On rejette les valeurs trop étendues.
    "max_extension_above_ma10": 0.08,   # clôture <= MA10 +8%
    "max_rsi": 80,                       # pas de signal sur RSI sur-acheté
}


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "pocket_pivot"

    look = p["lookback_down_days"]
    if df is None or len(df) < max(50, look + 2) or "volume" not in df:
        return base.make_result(name, False, notes="données insuffisantes")

    closes = df["close"]
    volumes = df["volume"]

    # Dernière séance haussière ?
    last_close = closes.iloc[-1]
    prev_close = closes.iloc[-2]
    is_up_day = last_close > prev_close
    last_vol = volumes.iloc[-1]

    # Volume max des jours BAISSIERS parmi les `look` séances précédant la dernière.
    # Jour baissier = clôture < clôture de la veille.
    max_down_vol = 0.0
    for i in range(len(df) - look - 1, len(df) - 1):
        if i < 1:
            continue
        if closes.iloc[i] < closes.iloc[i - 1]:
            max_down_vol = max(max_down_vol, float(volumes.iloc[i]))

    vol_ok = max_down_vol > 0 and last_vol >= max_down_vol * p["min_volume_vs_down_days"]

    # Position vs moyennes mobiles
    ma10 = df["ma10"].iloc[-1] if "ma10" in df else None
    ma50 = df["ma50"].iloc[-1] if "ma50" in df else None
    above_ma10 = (ma10 is not None and pd.notna(ma10) and last_close > ma10) or not p["price_above_ma10"]
    above_ma50 = (ma50 is not None and pd.notna(ma50) and last_close > ma50) or not p["price_above_ma50"]

    # Garde-fous anti-extension : proche de la MA10 et pas sur-acheté
    not_extended = True
    if ma10 is not None and pd.notna(ma10) and ma10 > 0:
        not_extended = last_close <= ma10 * (1 + p["max_extension_above_ma10"])
    rsi = df["rsi"].iloc[-1] if "rsi" in df else None
    rsi_ok = rsi is None or pd.isna(rsi) or rsi <= p["max_rsi"]

    detected = bool(is_up_day and vol_ok and above_ma10 and above_ma50
                    and not_extended and rsi_ok)
    vol_ratio_vs_down = (last_vol / max_down_vol) if max_down_vol else 0.0

    return base.make_result(
        name, detected,
        depth=0.05, max_depth=0.15,  # pocket pivot = base serrée par nature
        volume_ratio=0.6,
        breakout_volume_ratio=round(min(vol_ratio_vs_down, 5.0), 2),
        breakout=detected,
        notes="" if detected else "pas de pivot valide (volume/extension/RSI)",
    )
