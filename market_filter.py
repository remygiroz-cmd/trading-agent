"""
market_filter.py — Filtre marché global (SPX + VIX).

Règle métier non négociable : aucun scan ni alerte si :
  - SPX (S&P 500) sous sa MA50  → tendance défavorable
  - VIX > 30                     → volatilité trop élevée

Ce filtre est vérifié EN PREMIER avant tout scan.
"""

import logging

import data_fetcher
import config

logger = logging.getLogger("market_filter")


def get_market_status() -> dict:
    """
    Évalue les conditions de marché.

    Retourne un dict :
      {
        "ok": bool,                 # True si scan autorisé
        "bullish": bool,            # marché globalement haussier
        "spx_price": float|None,
        "spx_ma50": float|None,
        "spx_above_ma50": bool,
        "vix": float|None,
        "vix_ok": bool,
        "reason": str,              # explication lisible
      }
    """
    cfg = config.MARKET_FILTER

    spx = data_fetcher.fetch_ticker(cfg["spx_ticker"], period="120d", interval="1d")
    vix = data_fetcher.fetch_ticker(cfg["vix_ticker"], period="10d", interval="1d")

    status = {
        "ok": False,
        "bullish": False,
        "spx_price": None,
        "spx_ma50": None,
        "spx_above_ma50": False,
        "vix": None,
        "vix_ok": False,
        "reason": "",
    }

    if spx.empty or len(spx) < cfg["spx_ma_period"]:
        status["reason"] = "Données SPX indisponibles ou insuffisantes — scan suspendu par sécurité."
        return status

    spx_price = float(spx["close"].iloc[-1])
    spx_ma = float(spx["close"].rolling(cfg["spx_ma_period"]).mean().iloc[-1])
    status["spx_price"] = spx_price
    status["spx_ma50"] = spx_ma
    status["spx_above_ma50"] = spx_price >= spx_ma

    if vix.empty:
        # Le VIX manquant n'est pas bloquant en soi, mais on le signale
        logger.warning("VIX indisponible — on poursuit en se basant sur le SPX seul.")
        status["vix_ok"] = True
    else:
        vix_current = float(vix["close"].iloc[-1])
        status["vix"] = vix_current
        status["vix_ok"] = vix_current <= cfg["vix_max"]

    # Décision
    if not status["spx_above_ma50"]:
        status["reason"] = (
            f"⚠️ SPX sous MA50 ({spx_price:.0f} < {spx_ma:.0f}) — "
            "scans suspendus. Marché défavorable."
        )
        return status

    if not status["vix_ok"]:
        status["reason"] = (
            f"⚠️ VIX > {cfg['vix_max']:.0f} (actuel {status['vix']:.1f}) — "
            "scans suspendus. Volatilité trop élevée."
        )
        return status

    status["ok"] = True
    status["bullish"] = True
    vix_txt = f"{status['vix']:.1f}" if status["vix"] is not None else "n/d"
    status["reason"] = (
        f"✅ Marché favorable — SPX {spx_price:.0f} > MA50 {spx_ma:.0f}, VIX {vix_txt}."
    )
    return status


def check_market_conditions(notifier=None) -> bool:
    """
    Vérifie les conditions de marché. Renvoie True si le scan peut avoir lieu.

    `notifier` : fonction optionnelle (ex. send_telegram) appelée avec le message
    d'avertissement si le marché est défavorable. Évite un couplage dur à Telegram.
    """
    status = get_market_status()
    logger.info(status["reason"])

    if not status["ok"] and notifier is not None:
        try:
            notifier(status["reason"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Notification filtre marché échouée : %s", e)

    return status["ok"]


def market_is_bullish() -> bool:
    """Raccourci booléen pour le scoring des setups."""
    return get_market_status()["bullish"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    st = get_market_status()
    for k, v in st.items():
        print(f"{k:18} : {v}")
