"""
market_context.py — Filtres de qualité supplémentaires (issus du backtest).

#2 Filtre résultats : éviter les signaux quand des résultats d'entreprise
   tombent pendant la durée de détention (risque de gap surprise).
#3 Force relative : ne garder que les actions qui surperforment le marché
   (meilleur prédicteur des gagnants — O'Neil / Minervini).

Les deux échouent "ouvert" (si la donnée manque, on ne bloque pas) pour ne pas
rater une opportunité à cause d'une donnée indisponible.
"""

import logging
import datetime as dt

import pandas as pd

import config

logger = logging.getLogger("market_context")


# ─────────────────────────────────────────────────────────────
# #3 — FORCE RELATIVE
# ─────────────────────────────────────────────────────────────

def relative_strength(stock_df: pd.DataFrame, market_df: pd.DataFrame,
                      lookback: int | None = None) -> dict:
    """
    Compare la performance du titre à celle du marché sur `lookback` séances.
    Retourne {stock_return, market_return, outperformance}.
    """
    lookback = lookback or config.RELATIVE_STRENGTH["lookback_days"]
    out = {"stock_return": None, "market_return": None, "outperformance": None}
    if stock_df is None or stock_df.empty or len(stock_df) <= lookback:
        return out
    if market_df is None or market_df.empty or len(market_df) <= lookback:
        return out

    s = stock_df["close"].values
    m = market_df["close"].values
    s_ret = (s[-1] - s[-1 - lookback]) / s[-1 - lookback]
    m_ret = (m[-1] - m[-1 - lookback]) / m[-1 - lookback]
    out.update({"stock_return": s_ret, "market_return": m_ret,
                "outperformance": s_ret - m_ret})
    return out


def passes_relative_strength(stock_df: pd.DataFrame, market_df: pd.DataFrame) -> tuple[bool, dict]:
    """True si le titre surperforme le marché (selon config). Fail-open si données absentes."""
    if not config.RELATIVE_STRENGTH["enabled"]:
        return True, {}
    rs = relative_strength(stock_df, market_df)
    if rs["outperformance"] is None:
        return True, rs  # donnée absente -> on ne bloque pas
    return rs["outperformance"] >= config.RELATIVE_STRENGTH["min_outperformance"], rs


# ─────────────────────────────────────────────────────────────
# NIVEAUX DE SORTIE ADAPTÉS À LA VOLATILITÉ (ATR)
# ─────────────────────────────────────────────────────────────

def compute_levels(entry: float, atr_pct: float | None) -> dict:
    """
    Calcule objectif / stop / horizon à partir de la volatilité (ATR).
    Stop calé sur l'ATR (borné), bien plus efficace que des % fixes sur les
    valeurs nerveuses (cf. backtest). Repli en % fixes si ATR absent.
    """
    r = config.RISK
    if r["mode"] == "atr" and atr_pct and atr_pct > 0:
        stop_pct = min(max(r["atr_stop_mult"] * atr_pct, r["min_stop_pct"]), r["max_stop_pct"])
        target_pct = min(r["atr_target_mult"] * atr_pct, r["max_target_pct"])
    else:
        stop_pct = r["fixed_stop_pct"]
        target_pct = r["fixed_target_pct"]

    return {
        "stop": round(entry * (1 - stop_pct), 4),
        "target": round(entry * (1 + target_pct), 4),
        "stop_pct": round(stop_pct, 4),
        "target_pct": round(target_pct, 4),
        "horizon": r["default_horizon"],
    }


# ─────────────────────────────────────────────────────────────
# #2 — FILTRE RÉSULTATS
# ─────────────────────────────────────────────────────────────

def next_earnings_date(ticker: str) -> dt.date | None:
    """Prochaine date de résultats (ou None si indisponible)."""
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            future = [d for d in dates if isinstance(d, dt.date)]
            if future:
                return min(future)
    except Exception as e:  # noqa: BLE001
        logger.debug("earnings %s indisponible : %s", ticker, e)
    return None


def days_until_earnings(ticker: str, today: dt.date | None = None) -> int | None:
    today = today or dt.date.today()
    d = next_earnings_date(ticker)
    if d is None:
        return None
    return (d - today).days


def earnings_in_horizon(ticker: str, horizon_days: int, today: dt.date | None = None) -> tuple[bool, int | None]:
    """
    True si des résultats tombent pendant la détention (horizon + buffer).
    Fail-open : si la date est inconnue, retourne (False, None) -> on ne bloque pas.
    """
    if not config.EARNINGS_FILTER["enabled"]:
        return False, None
    days = days_until_earnings(ticker, today)
    if days is None:
        return False, None
    buffer = config.EARNINGS_FILTER["buffer_days"]
    in_window = 0 <= days <= (horizon_days + buffer)
    return in_window, days
