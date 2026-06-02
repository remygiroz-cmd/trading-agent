"""
market_regime.py — Détection du régime de marché et adaptation de la stratégie.

Au lieu du binaire "marché favorable / défavorable", on classe l'état du marché
et on adapte la sélectivité + la prise de risque :

  📈 HAUSSIER    : SPX au-dessus de ses MA50 et MA200, MA50 qui monte, VIX serein
                   -> on joue normalement (seuil 75, taille pleine).
  ⚠️ PRUDENT     : au-dessus de la MA50 mais signaux mitigés (sous la MA200, MA50
                   qui faiblit, ou VIX élevé) -> on exige plus de conviction et on
                   réduit la taille.
  🛑 DÉFAVORABLE : repli (normalement déjà bloqué en amont par market_filter).

Le filtre dur (SPX < MA50 ou VIX > 30 -> aucun scan) reste géré par market_filter
et n'est pas remis en cause ici. market_regime affine la zone autorisée.
"""

import logging

import data_fetcher
import config

logger = logging.getLogger("market_regime")


def _vix_value() -> float | None:
    vix = data_fetcher.fetch_ticker(config.MARKET_FILTER["vix_ticker"], period="10d", interval="1d")
    if vix is None or vix.empty:
        return None
    return float(vix["close"].iloc[-1])


def detect_regime() -> dict:
    """
    Analyse le marché et retourne le régime + ses paramètres d'adaptation.

    Retourne :
      {
        "regime": "haussier" | "prudent" | "defavorable",
        "label": str,                 # libellé lisible
        "min_final_score": int,       # seuil d'alerte adapté
        "max_finalists": int,         # sélectivité adaptée
        "size_mult": float,           # multiplicateur de taille de position
        "details": str,               # explication
        "metrics": {...},             # valeurs brutes (SPX, MA, VIX…)
      }
    """
    p = config.REGIME_PARAMS
    spx = data_fetcher.fetch_ticker(config.MARKET_FILTER["spx_ticker"],
                                    period="320d", interval="1d")

    if spx is None or spx.empty or len(spx) < p["ma_trend"]:
        # Données insuffisantes : on retombe sur "prudent" par sécurité
        return _build("prudent", "Données SPX insuffisantes — prudence par défaut.", {})

    close = spx["close"]
    price = float(close.iloc[-1])
    ma50 = float(close.rolling(p["ma_trend"]).mean().iloc[-1])
    ma200 = float(close.rolling(p["ma_long"]).mean().iloc[-1]) if len(close) >= p["ma_long"] else None

    # Pente de la MA50 sur slope_lookback séances
    lb = p["slope_lookback"]
    ma50_series = close.rolling(p["ma_trend"]).mean()
    ma50_prev = float(ma50_series.iloc[-1 - lb]) if len(ma50_series) > lb else ma50
    ma50_rising = ma50 > ma50_prev

    vix = _vix_value()

    above50 = price >= ma50
    above200 = (ma200 is None) or (price >= ma200)
    golden = (ma200 is None) or (ma50 >= ma200)
    vix_calm = (vix is None) or (vix <= p["vix_calm"])

    metrics = {
        "spx": round(price, 1), "ma50": round(ma50, 1),
        "ma200": round(ma200, 1) if ma200 is not None else None,
        "ma50_rising": ma50_rising, "vix": round(vix, 1) if vix is not None else None,
    }

    # Classification
    if not above50 or (vix is not None and vix > config.MARKET_FILTER["vix_max"]):
        return _build("defavorable", "SPX sous MA50 ou VIX extrême — repli.", metrics)

    if above200 and golden and ma50_rising and vix_calm:
        return _build("haussier",
                      f"SPX {price:.0f} > MA50 {ma50:.0f} > MA200, MA50 en hausse, "
                      f"VIX {metrics['vix']} serein.", metrics)

    # au-dessus de la MA50 mais quelque chose cloche -> prudent
    raisons = []
    if not above200:
        raisons.append("sous la MA200")
    if not ma50_rising:
        raisons.append("MA50 qui faiblit")
    if not vix_calm:
        raisons.append(f"VIX élevé ({metrics['vix']})")
    return _build("prudent", "Marché mitigé : " + ", ".join(raisons) + ".", metrics)


def _build(regime: str, details: str, metrics: dict) -> dict:
    cfg = config.REGIMES[regime]
    return {
        "regime": regime,
        "label": cfg["label"],
        "min_final_score": cfg["min_final_score"],
        "max_finalists": cfg["max_finalists"],
        "size_mult": cfg["size_mult"],
        "details": details,
        "metrics": metrics,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = detect_regime()
    print(f"\n=== RÉGIME : {r['label']} ({r['regime']}) ===")
    print(r["details"])
    print(f"Seuil alerte : {r['min_final_score']}/100 | finalistes max : {r['max_finalists']} "
          f"| taille x{r['size_mult']}")
    print("Mesures :", r["metrics"])
