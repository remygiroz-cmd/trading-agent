"""
Package patterns — détection des 7 figures chartistes haussières.

Expose :
  - PATTERNS : registre {nom: fonction detect}
  - detect_all(df) : applique toutes les figures sur un DataFrame
  - scan_ticker(df, ticker_data, market_bullish) : détecte + calcule le score
    de qualité, et renvoie la meilleure figure
  - calculate_setup_score : ré-export depuis base
"""

from . import base
from .base import calculate_setup_score

from . import bull_flag
from . import cup_handle
from . import vcp
from . import high_tight_flag
from . import pocket_pivot
from . import flat_base
from . import double_bottom
from . import momentum_pop

PATTERNS = {
    "bull_flag": bull_flag.detect,
    "cup_handle": cup_handle.detect,
    "vcp": vcp.detect,
    "high_tight_flag": high_tight_flag.detect,
    "pocket_pivot": pocket_pivot.detect,
    "flat_base": flat_base.detect,
    "double_bottom": double_bottom.detect,
    "momentum_pop": momentum_pop.detect,
}


def detect_all(df) -> list[dict]:
    """Applique les figures ACTIVÉES (config.ENABLED_PATTERNS) sur un DataFrame."""
    try:
        import config
        enabled = set(config.ENABLED_PATTERNS)
    except Exception:  # noqa: BLE001
        enabled = set(PATTERNS.keys())

    results = []
    for nom, fn in PATTERNS.items():
        if nom not in enabled:
            continue
        try:
            results.append(fn(df))
        except Exception as e:  # noqa: BLE001
            results.append(base.make_result(nom, False, notes=f"erreur: {e}"))
    return results


def scan_ticker(df, ticker_data: dict, market_bullish: bool = True) -> dict:
    """
    Détecte les figures sur un ticker et calcule le score de qualité de chacune.

    ticker_data : {"price": float, "ma50": float, ...}

    Retourne :
      {
        "detected": [résultats détectés avec setup_score],
        "best": meilleur résultat détecté (ou None),
        "all": tous les résultats (debug),
      }
    """
    all_results = detect_all(df)
    detected = []
    for r in all_results:
        if r["detected"]:
            r["setup_score"] = calculate_setup_score(ticker_data, r, market_bullish)
            detected.append(r)

    detected.sort(key=lambda r: r["setup_score"], reverse=True)
    best = detected[0] if detected else None

    return {"detected": detected, "best": best, "all": all_results}
