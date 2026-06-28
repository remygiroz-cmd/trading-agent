"""
alerts/price_alerts.py — Alertes de franchissement de niveaux de prix.

Prévient Rémy AU MOMENT où une valeur franchit un niveau clé défini dans
config.PRICE_ALERTS (par ex. Sanofi > 76€ = sortie de canal baissier, Hermès >
1690€ = neckline du W cassée).

Anti-doublon : on mémorise dans memory/state si le niveau est déjà franchi.
L'alerte ne part qu'à la TRANSITION (non franchi -> franchi). Le marqueur se
réarme tout seul quand le prix repasse de l'autre côté du niveau : ainsi un
aller-retour autour du seuil ne spamme pas, mais un nouveau franchissement plus
tard réalerte bien.
"""

import logging

import config
import data_fetcher

logger = logging.getLogger("price_alerts")

STATE_KEY = "price_alerts_state"


def _alert_id(a: dict) -> str:
    return f"{a['ticker']}@{a['level']}{a['dir']}"


def _crossed(price: float, level: float, direction: str) -> bool:
    return price >= level if direction == "above" else price <= level


def _format(a: dict, price: float) -> str:
    arrow = "🔼" if a["dir"] == "above" else "🔽"
    cur = a.get("cur", "")
    return (f"{arrow} ALERTE PRIX — {a['name']} ({price:.2f}{cur})\n"
            f"{a['name']} {a['msg']}")


def check(send: bool = True) -> dict:
    """Vérifie tous les niveaux configurés et alerte sur les nouveaux franchissements."""
    rules = getattr(config, "PRICE_ALERTS", []) or []
    if not rules:
        return {"alerts": 0, "messages": []}

    from memory import state
    prev = state.get_state(STATE_KEY, default={}) or {}
    new_state = {}
    messages = []

    for a in rules:
        aid = _alert_id(a)
        price = None
        try:
            price = data_fetcher.fetch_current_price(a["ticker"])
        except Exception as e:  # noqa: BLE001
            logger.warning("prix %s indisponible : %s", a["ticker"], e)

        if price is None:
            # On garde l'état précédent pour ne pas réarmer à tort sur un trou de données.
            new_state[aid] = prev.get(aid, False)
            continue

        crossed = _crossed(price, a["level"], a["dir"])
        new_state[aid] = crossed
        if crossed and not prev.get(aid, False):
            messages.append(_format(a, price))

    state.set_state(STATE_KEY, new_state)

    if send and messages:
        try:
            from alerts import telegram_bot
            for m in messages:
                telegram_bot.send_message(m)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi alerte prix échoué : %s", e)

    logger.info("Alertes prix : %s franchissement(s)", len(messages))
    return {"alerts": len(messages), "messages": messages}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(check(send=False))
