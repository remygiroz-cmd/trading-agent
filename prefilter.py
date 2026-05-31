"""
prefilter.py — Pré-filtre algorithmique (Python pur, sans IA).

Appliqué sur l'ensemble des tickers de la watchlist. Ne garde que les
candidats qui passent TOUS les critères (cf. config.PREFILTER_CRITERIA) :
  - variation 5 jours >= +2%
  - volume du jour > 1.3x la moyenne 20j
  - prix au-dessus de la MA20
  - prix >= 1$ (pas de penny stocks)
  - volume moyen >= 100k actions/jour

Objectif : réduire 340 tickers à 15-40 candidats avant d'appeler les figures
chartistes et les IA (coûteuses).
"""

import time
import logging

import pandas as pd

import config
import data_fetcher

logger = logging.getLogger("prefilter")


def evaluate_ticker(ticker: str, df: pd.DataFrame | None = None) -> dict:
    """
    Évalue un ticker contre les critères du pré-filtre.

    Retourne un dict détaillé :
      {
        "ticker": str,
        "passed": bool,
        "reasons": [str],         # critères échoués (vide si passed)
        "metrics": {...},         # valeurs calculées
      }
    """
    crit = config.PREFILTER_CRITERIA
    result = {"ticker": ticker, "passed": False, "reasons": [], "metrics": {}}

    if df is None:
        df = data_fetcher.fetch_ticker(ticker, period="90d", interval="1d")

    if df.empty or len(df) < 21:
        result["reasons"].append("données insuffisantes")
        return result

    df = data_fetcher.add_indicators(df)
    close = df["close"]
    volume = df["volume"]

    price = float(close.iloc[-1])
    ma20 = df["ma20"].iloc[-1]
    vol_today = float(volume.iloc[-1])
    vol_avg20 = df["vol_avg20"].iloc[-1]

    # Variation sur 5 jours (5 séances)
    if len(close) >= 6:
        var_5d = (price - float(close.iloc[-6])) / float(close.iloc[-6])
    else:
        var_5d = 0.0

    vol_ratio = (vol_today / vol_avg20) if vol_avg20 and vol_avg20 > 0 else 0.0

    metrics = {
        "price": round(price, 4),
        "var_5d": round(var_5d, 4),
        "vol_ratio": round(vol_ratio, 2),
        "vol_avg20": int(vol_avg20) if pd.notna(vol_avg20) else 0,
        "ma20": round(float(ma20), 4) if pd.notna(ma20) else None,
        "rsi": round(float(df["rsi"].iloc[-1]), 1) if pd.notna(df["rsi"].iloc[-1]) else None,
    }
    result["metrics"] = metrics

    # Application des critères
    reasons = result["reasons"]

    if price < crit["min_price"]:
        reasons.append(f"prix {price:.2f} < {crit['min_price']}")

    if var_5d < crit["min_variation_5d"]:
        reasons.append(f"var5j {var_5d*100:.1f}% < {crit['min_variation_5d']*100:.0f}%")

    if vol_ratio < crit["min_volume_ratio"]:
        reasons.append(f"volratio {vol_ratio:.2f} < {crit['min_volume_ratio']}")

    if crit["price_above_ma20"] and (pd.isna(ma20) or price < ma20):
        reasons.append("prix sous MA20")

    if pd.isna(vol_avg20) or vol_avg20 < crit["min_avg_volume"]:
        reasons.append(f"volmoy {metrics['vol_avg20']} < {crit['min_avg_volume']}")

    result["passed"] = len(reasons) == 0
    return result


def _quality_key(res: dict) -> float:
    """Score de tri momentum : variation 5j pondérée par la poussée de volume."""
    m = res["metrics"]
    return m.get("var_5d", 0) * min(m.get("vol_ratio", 0), 5.0)


def run_prefilter(tickers: list[str], pause: float = 0.0, verbose: bool = False,
                  batch: bool = True, max_candidates: int | None = None) -> list[dict]:
    """
    Exécute le pré-filtre sur une liste de tickers.
    Retourne la liste des candidats RETENUS (passed=True), triés par qualité momentum.

    batch=True : télécharge les données en requêtes groupées (rapide, recommandé
    pour les gros scans). batch=False : un téléchargement par ticker.

    max_candidates : plafond du nombre de candidats retournés (défaut :
    config.PREFILTER_MAX_CANDIDATES). Passer 0 pour ne pas plafonner.
    """
    if max_candidates is None:
        max_candidates = config.PREFILTER_MAX_CANDIDATES

    candidates = []
    total = len(tickers)

    prefetched = data_fetcher.fetch_batch(tickers, period="90d", interval="1d") if batch else {}

    for i, tk in enumerate(tickers, 1):
        try:
            res = evaluate_ticker(tk, df=prefetched.get(tk) if batch else None)
        except Exception as e:  # noqa: BLE001
            logger.warning("Erreur pré-filtre %s : %s", tk, e)
            continue

        if res["passed"]:
            candidates.append(res)
            if verbose:
                m = res["metrics"]
                logger.info("  ✓ %s var5j=%.1f%% vol=x%.2f", tk, m["var_5d"] * 100, m["vol_ratio"])
        if pause:
            time.sleep(pause)

    candidates.sort(key=_quality_key, reverse=True)
    retenus = len(candidates)

    if max_candidates and len(candidates) > max_candidates:
        logger.info("Pré-filtre : %s candidats éligibles, plafonnés au top %s",
                    retenus, max_candidates)
        candidates = candidates[:max_candidates]
    else:
        logger.info("Pré-filtre : %s candidats retenus sur %s tickers", retenus, total)

    return candidates


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import watchlist

    tickers = watchlist.get_fixed_watchlist()
    print(f"Pré-filtre sur {len(tickers)} tickers fixes...\n")
    cands = run_prefilter(tickers, verbose=True)
    print(f"\n{len(cands)} candidats retenus :")
    for c in cands:
        m = c["metrics"]
        print(f"  {c['ticker']:10} prix={m['price']:.2f} var5j={m['var_5d']*100:+.1f}% "
              f"vol=x{m['vol_ratio']:.2f} RSI={m['rsi']}")
