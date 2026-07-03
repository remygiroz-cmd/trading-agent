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
import datetime as dt

import config
import data_fetcher

logger = logging.getLogger("price_alerts")

STATE_KEY = "price_alerts_state"
DYN_KEY = "price_alerts_dynamic"
DYN_EXPIRY_DAYS = 30   # une alerte dynamique jamais touchée expire au bout d'un mois


def _alert_id(a: dict) -> str:
    return f"{a['ticker']}@{a['level']}{a['dir']}"


def _crossed(price: float, level: float, direction: str) -> bool:
    return price >= level if direction == "above" else price <= level


def _format(a: dict, price: float) -> str:
    arrow = "🔼" if a["dir"] == "above" else "🔽"
    cur = a.get("cur", "")
    return (f"{arrow} ALERTE PRIX — {a['name']} ({price:.2f}{cur})\n"
            f"{a['name']} {a['msg']}")


# ─────────────────────────────────────────────────────────────
# ALERTES DYNAMIQUES (posées par /analyse : "je te préviens à tel prix")
# Une alerte dynamique est à USAGE UNIQUE : déclenchée -> supprimée.
# ─────────────────────────────────────────────────────────────

def _load_dynamic() -> list[dict]:
    from memory import state
    return state.get_state(DYN_KEY, default=[]) or []


def _save_dynamic(rules: list[dict]) -> None:
    from memory import state
    state.set_state(DYN_KEY, rules)


def add_dynamic(name: str, ticker: str, level: float, direction: str,
                cur: str, msg: str) -> None:
    """Pose une alerte de prix à usage unique. Remplace toute alerte existante
    sur le même ticker + sens (la plus récente fait foi)."""
    rules = [r for r in _load_dynamic()
             if not (r["ticker"] == ticker and r["dir"] == direction)]
    rules.append({"name": name, "ticker": ticker, "level": level, "dir": direction,
                  "cur": cur, "msg": msg, "created": dt.date.today().isoformat()})
    _save_dynamic(rules)
    logger.info("Alerte dynamique posée : %s %s %.2f", ticker, direction, level)


def _dynamic_expired(r: dict, today: dt.date) -> bool:
    try:
        return (today - dt.date.fromisoformat(r.get("created", ""))).days > DYN_EXPIRY_DAYS
    except Exception:  # noqa: BLE001
        return False


def check(send: bool = True) -> dict:
    """Vérifie tous les niveaux (config + dynamiques) et alerte sur franchissement."""
    static_rules = getattr(config, "PRICE_ALERTS", []) or []
    dynamic_rules = _load_dynamic()
    if not static_rules and not dynamic_rules:
        return {"alerts": 0, "messages": []}

    from memory import state
    prev = state.get_state(STATE_KEY, default={}) or {}
    new_state = {}
    messages = []

    for a in static_rules:
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

    # Alertes dynamiques : usage unique (déclenchée -> supprimée), expiration 30j
    if dynamic_rules:
        today = dt.date.today()
        remaining = []
        for a in dynamic_rules:
            if _dynamic_expired(a, today):
                continue
            price = None
            try:
                price = data_fetcher.fetch_current_price(a["ticker"])
            except Exception as e:  # noqa: BLE001
                logger.warning("prix %s indisponible : %s", a["ticker"], e)
            if price is not None and _crossed(price, a["level"], a["dir"]):
                messages.append(_format(a, price))
            else:
                remaining.append(a)
        if len(remaining) != len(dynamic_rules):
            _save_dynamic(remaining)

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
