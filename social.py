"""
social.py — Sentiment des réseaux sociaux financiers (StockTwits).

Complète le sentiment des actualités : StockTwits expose une API publique où les
messages sont taggés "Bullish"/"Bearish" par leurs auteurs. On compte ces tags
sur les messages récents d'un ticker -> un score de sentiment retail [-1, +1],
moins manipulable qu'une seule source.

Gratuit, sans clé. Dégradation gracieuse : si l'API ne répond pas (limite de
débit, indisponible), on renvoie un sentiment neutre/None sans bloquer.

NB : StockTwits utilise les tickers US bruts (ex. "NVDA"). Pour une valeur
européenne au format Yahoo ("STMPA.PA"), on retire le suffixe ; le sentiment
StockTwits reste surtout pertinent pour les valeurs américaines.
"""

import logging

import requests

logger = logging.getLogger("social")

_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"


def _symbol(ticker: str) -> str:
    return ticker.split(".")[0].upper()


def stocktwits_sentiment(ticker: str) -> dict:
    """
    Sentiment StockTwits d'un ticker. Retourne
    {"score": float|-None, "bull": int, "bear": int, "n": int}.
    score dans [-1, +1] (None si pas de données exploitables).
    """
    sym = _symbol(ticker)
    try:
        r = requests.get(_URL.format(symbol=sym), timeout=15,
                         headers={"User-Agent": "trading-agent"})
        if r.status_code != 200:
            return {"score": None, "bull": 0, "bear": 0, "n": 0}
        messages = (r.json() or {}).get("messages", []) or []
    except Exception as e:  # noqa: BLE001
        logger.debug("StockTwits %s KO : %s", sym, str(e)[:80])
        return {"score": None, "bull": 0, "bear": 0, "n": 0}

    bull = bear = 0
    for m in messages:
        ent = (m.get("entities") or {}).get("sentiment") or {}
        basic = ent.get("basic")
        if basic == "Bullish":
            bull += 1
        elif basic == "Bearish":
            bear += 1
    tagged = bull + bear
    if tagged == 0:
        return {"score": None, "bull": 0, "bear": 0, "n": len(messages)}
    score = (bull - bear) / tagged
    return {"score": round(score, 3), "bull": bull, "bear": bear, "n": len(messages)}


def sentiment_text(s: dict) -> str:
    if s.get("score") is None:
        return ""
    label = "haussier" if s["score"] > 0.15 else "baissier" if s["score"] < -0.15 else "mitigé"
    return (f"Sentiment StockTwits : {label} (score {s['score']:+.2f}, "
            f"{s['bull']} haussiers / {s['bear']} baissiers)")
