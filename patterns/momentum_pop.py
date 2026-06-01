"""
patterns/momentum_pop.py — Signal "explosif" (momentum + volume + volatilité).

Issu de l'étude discover.py : la combinaison qui précède le plus souvent un
bond rapide est explosion de volume + momentum récent + volatilité suffisante.
Au backtest (avec stops ATR), c'est le signal le plus rentable.

Différent des figures "base serrée" (VCP, flat base) : ici on cherche au
contraire une valeur NERVEUSE qui accélère. Le stop ATR (géré ailleurs) est
indispensable pour ce type de trade.
"""

from . import base

DEFAULT_PARAMS = {
    "min_vol_ratio": 1.3,     # volume du jour > 1.3x moyenne 20j
    "min_ret_5d": 0.05,       # +5% sur 5 séances
    "min_atr_pct": 0.05,      # volatilité suffisante pour bouger
    "max_rsi": 85,            # éviter le franchement euphorique
}


def detect(df, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    name = "momentum_pop"

    if df is None or len(df) < 25 or "volume" not in df:
        return base.make_result(name, False, notes="données insuffisantes")

    close = df["close"]
    last = close.iloc[-1]
    vol_avg = df["vol_avg20"].iloc[-1] if "vol_avg20" in df else None
    vol_ratio = (df["volume"].iloc[-1] / vol_avg) if vol_avg and vol_avg > 0 else 0.0
    ret_5d = (last - close.iloc[-6]) / close.iloc[-6] if len(close) >= 6 else 0.0
    atr_pct = df["atr_pct"].iloc[-1] if "atr_pct" in df else None
    rsi = df["rsi"].iloc[-1] if "rsi" in df else None

    import pandas as pd
    atr_ok = atr_pct is not None and not pd.isna(atr_pct) and atr_pct >= p["min_atr_pct"]
    rsi_ok = rsi is None or pd.isna(rsi) or rsi <= p["max_rsi"]

    detected = bool(
        vol_ratio >= p["min_vol_ratio"]
        and ret_5d >= p["min_ret_5d"]
        and atr_ok and rsi_ok
    )

    return base.make_result(
        name, detected,
        depth=0.05, max_depth=0.15,        # pas de "correction" ici
        volume_ratio=0.6,                   # composante contraction neutre
        breakout_volume_ratio=round(min(vol_ratio, 5.0), 2),
        breakout=detected,
        pole_gain=round(ret_5d, 3),
        notes="" if detected else f"vol x{vol_ratio:.2f}, ret5 {ret_5d*100:.1f}%, atr {atr_pct}",
    )
