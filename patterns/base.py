"""
patterns/base.py — Outils communs à toutes les figures chartistes.

Fournit :
  - un format de résultat standardisé (PatternResult)
  - des helpers (swings, contraction de volume, cassure)
  - le score de qualité du setup (0-50) — cf. SPECS 2.9
"""

from __future__ import annotations

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────────────────────
# RÉSULTAT STANDARDISÉ
# ─────────────────────────────────────────────────────────────

def make_result(pattern: str, detected: bool, **kwargs) -> dict:
    """
    Construit un résultat de détection homogène.

    Champs clés attendus par le scoring :
      depth, max_depth, volume_ratio, breakout_volume_ratio
    Champs informatifs : pole_gain, pole_candles, base_candles, breakout, notes...
    """
    base = {
        "pattern": pattern,
        "detected": detected,
        # valeurs neutres par défaut (utiles si la figure n'a pas ce concept)
        "depth": 0.0,
        "max_depth": 1.0,
        "volume_ratio": 1.0,
        "breakout_volume_ratio": 1.0,
        "breakout": False,
        "pole_gain": None,
        "pole_candles": None,
        "base_candles": None,
        "notes": "",
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def pct(a: float, b: float) -> float:
    """Variation relative de b à a : (a-b)/b."""
    if b == 0:
        return 0.0
    return (a - b) / b


def avg_volume(df: pd.DataFrame, lookback: int = 20) -> float:
    if "volume" not in df or df.empty:
        return 0.0
    v = df["volume"].tail(lookback).mean()
    return float(v) if pd.notna(v) else 0.0


def last_breakout_volume_ratio(df: pd.DataFrame, base_window: int) -> float:
    """Ratio volume dernière bougie / volume moyen sur la base précédente."""
    if "volume" not in df or len(df) < base_window + 1:
        return 1.0
    base_vol = df["volume"].iloc[-(base_window + 1):-1].mean()
    last_vol = df["volume"].iloc[-1]
    if not base_vol or pd.isna(base_vol) or base_vol == 0:
        return 1.0
    return float(last_vol / base_vol)


def find_pole(df: pd.DataFrame, min_gain: float, max_candles: int):
    """
    Cherche le « mât » haussier le plus récent : une montée >= min_gain
    réalisée en <= max_candles bougies, se terminant sur un sommet local.

    Retourne (start_idx, end_idx, gain) en indices positionnels, ou None.
    """
    closes = df["close"].values
    n = len(closes)
    if n < 3:
        return None

    best = None
    # On cherche en partant de la fin pour privilégier le mât le plus récent.
    for end in range(n - 1, max(1, n - max_candles - 30), -1):
        lo = max(0, end - max_candles)
        for start in range(end - 1, lo - 1, -1):
            gain = pct(closes[end], closes[start])
            if gain >= min_gain:
                # le sommet du mât doit être un point haut local (peu de bougies au-dessus après)
                best = (start, end, gain)
                break
        if best:
            break
    return best


def find_flag_structure(df: pd.DataFrame, pole_min_gain: float, pole_max_candles: int,
                        flag_min_candles: int, flag_max_candles: int):
    """
    Détecte une structure mât + drapeau (commune au bull flag et au high tight flag).

    Principe : la « résistance » du drapeau est le plus haut sur la fenêtre récente
    EN EXCLUANT la dernière bougie (qui peut être la cassure). Le drapeau s'étend
    de ce sommet jusqu'à la fin ; le mât est la montée qui précède le sommet.

    Retourne un dict ou None :
      {resistance, resistance_idx, pole_low, pole_gain, pole_candles,
       flag_candles, flag_low}
    """
    n = len(df)
    if n < pole_min_gain_min_len(flag_min_candles):
        return None

    highs = df["high"].values if "high" in df else df["close"].values
    lows = df["low"].values if "low" in df else df["close"].values

    # Fenêtre de recherche du sommet : on exclut la dernière bougie.
    search_lo = max(0, n - 1 - (pole_max_candles + flag_max_candles))
    if n - 1 - search_lo < flag_min_candles + 2:
        return None

    # Sommet = plus haut sur [search_lo, n-2] situé de façon à laisser un drapeau valide.
    valid_peak_hi = n - 1 - flag_min_candles      # le sommet doit précéder >= flag_min bougies
    valid_peak_lo = max(search_lo, n - 1 - flag_max_candles)
    if valid_peak_lo > valid_peak_hi:
        return None

    seg = highs[valid_peak_lo:valid_peak_hi + 1]
    resistance_idx = valid_peak_lo + int(seg.argmax())
    resistance = highs[resistance_idx]

    flag_candles = n - 1 - resistance_idx
    if not (flag_min_candles <= flag_candles <= flag_max_candles):
        return None

    # Mât : plus bas sur les pole_max_candles précédant le sommet
    pole_lo_idx = max(0, resistance_idx - pole_max_candles)
    pole_low = lows[pole_lo_idx:resistance_idx + 1].min()
    pole_gain = pct(resistance, pole_low)
    if pole_gain < pole_min_gain:
        return None

    flag_low = lows[resistance_idx + 1:].min()

    return {
        "resistance": float(resistance),
        "resistance_idx": resistance_idx,
        "pole_low": float(pole_low),
        "pole_gain": float(pole_gain),
        "pole_candles": resistance_idx - pole_lo_idx,
        "flag_candles": flag_candles,
        "flag_low": float(flag_low),
    }


def pole_min_gain_min_len(flag_min_candles: int) -> int:
    """Longueur minimale de DataFrame requise pour une détection mât+drapeau."""
    return flag_min_candles + 5


def max_drawdown_since(df: pd.DataFrame, peak_idx: int) -> float:
    """Repli max (fraction) depuis le sommet à peak_idx jusqu'à la fin."""
    highs = df["high"].values if "high" in df else df["close"].values
    lows = df["low"].values if "low" in df else df["close"].values
    peak = highs[peak_idx]
    if peak_idx >= len(lows) - 1:
        return 0.0
    trough = lows[peak_idx + 1:].min()
    return float(pct(peak, trough)) * -1 if trough < peak else 0.0


# ─────────────────────────────────────────────────────────────
# SCORE DE QUALITÉ DU SETUP (0-50)
# ─────────────────────────────────────────────────────────────

def calculate_setup_score(ticker_data: dict, pattern_data: dict,
                          market_bullish: bool = True) -> float:
    """
    Score objectif du setup avant appel aux IA (cf. SPECS 2.9).

    ticker_data : {"price": float, "ma50": float}
    pattern_data : résultat make_result (depth, max_depth, volume_ratio, breakout_volume_ratio)

    Retourne un score /50. Envoyer aux IA si >= 30/50.
    """
    score = 0.0

    depth = pattern_data.get("depth", 0.0)
    max_depth = pattern_data.get("max_depth", 1.0) or 1.0
    vol_ratio = pattern_data.get("volume_ratio", 1.0)
    brk_ratio = pattern_data.get("breakout_volume_ratio", 1.0)

    # Profondeur de la correction (0-10) — plus c'est peu profond, mieux c'est
    score += max(0.0, min(10.0, (1 - depth / max_depth) * 10))

    # Contraction du volume (0-10) — plus le volume sèche, mieux c'est
    score += max(0.0, min(10.0, (1 - vol_ratio) * 10))

    # Propreté de la cassure (0-10)
    score += max(0.0, min(10.0, brk_ratio * 3.5))

    # Alignement tendance (0-10)
    price = ticker_data.get("price")
    ma50 = ticker_data.get("ma50")
    if price is not None and ma50 is not None and price > ma50:
        score += 10

    # Contexte marché (0-10)
    score += 10 if market_bullish else 5

    return round(score, 1)
