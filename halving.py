"""
halving.py — Alerte calendaire "stratégie 500 jours halving".

Stratégie simple validée sur 3 cycles : acheter 500 jours AVANT le halving,
vendre 500 jours APRÈS. On calcule chaque jour le nombre de jours restants avant
chaque signal et on alerte à J-30, J-7 et J-0.

Anti-spam : chaque jalon (achat_30, achat_7, achat_0, vente_30, vente_7, vente_0)
n'est envoyé qu'UNE fois (mémorisé dans agent_state, persistant côté Supabase).
Robuste aux jours sautés : on déclenche dès que `jours_restants <= jalon` et que
le jalon n'a pas encore été envoyé.
"""

import logging
import datetime as dt

import config

logger = logging.getLogger("halving")

STATE_KEY = "halving_sent"


def _dates() -> tuple[dt.date, dt.date]:
    """(date signal ACHAT, date signal VENTE) = halving -/+ offset jours."""
    h = dt.date.fromisoformat(config.HALVING["halving_date"])
    off = dt.timedelta(days=config.HALVING["offset_days"])
    return h - off, h + off


# ─────────────────────────────────────────────────────────────
# MESSAGES (textes fournis par Rémy)
# ─────────────────────────────────────────────────────────────

def _msg(type_alerte: str, milestone: int) -> str | None:
    if type_alerte == "achat":
        if milestone == 30:
            return ("📅 *BITCOIN — Signal d'achat dans 30 jours*\n\n"
                    "Dans 30 jours, tu entreras dans la fenêtre d'achat de la stratégie "
                    "\"500 jours avant le halving\".\n\n"
                    "Cette stratégie simple a fonctionné sur les 3 derniers cycles : acheter "
                    "500 jours avant le halving, vendre 500 jours après.\n\n"
                    "👉 Prépare ta trésorerie. Commence à surveiller le MVRV Z-Score en "
                    "parallèle pour confirmer l'entrée.")
        if milestone == 7:
            return ("⏳ *BITCOIN — Signal d'achat dans 7 jours*\n\n"
                    "Dans 7 jours : fenêtre d'achat \"500 jours halving\".\n\n"
                    "👉 Dernière ligne droite. Vérifie le MVRV Z-Score (idéalement sous 1). "
                    "Si les deux indicateurs sont alignés, c'est le meilleur signal d'entrée "
                    "selon ta stratégie.")
        if milestone == 0:
            return ("🟢 *BITCOIN — AUJOURD'HUI : Signal d'achat \"500 jours halving\"*\n\n"
                    "On est exactement à 500 jours du prochain halving (avril 2028).\n\n"
                    "Historiquement c'est le meilleur point d'entrée sur Bitcoin selon cette "
                    "stratégie de cycle.\n\n"
                    "👉 Croise avec le MVRV Z-Score avant d'agir. Si MVRV < 1 : signal fort. "
                    "Si MVRV > 2 : rester prudent malgré le calendrier.")
    else:  # vente
        if milestone == 30:
            return ("📅 *BITCOIN — Signal de vente dans 30 jours*\n\n"
                    "Dans 30 jours, tu entreras dans la fenêtre de vente \"500 jours après "
                    "le halving\".\n\n"
                    "👉 Prépare ton plan de sortie progressif. Commence à surveiller tes "
                    "seuils MVRV (3.0 / 3.5 / 4.0 / 4.5 / 5.0).")
        if milestone == 7:
            return ("⏳ *BITCOIN — Signal de vente dans 7 jours*\n\n"
                    "Dans 7 jours : fenêtre de vente \"500 jours après le halving\".\n\n"
                    "👉 Finalise ton plan de sortie progressif. Surveille le MVRV "
                    "(vente progressive recommandée si > 3.5).")
        if milestone == 0:
            return ("🔴 *BITCOIN — AUJOURD'HUI : Signal de vente \"500 jours halving\"*\n\n"
                    "On est exactement à 500 jours après le halving d'avril 2028.\n\n"
                    "👉 Zone de vente selon la stratégie de cycle. Croise avec le MVRV "
                    "Z-Score. Si MVRV > 3.5 : vente progressive recommandée selon ton plan.")
    return None


# ─────────────────────────────────────────────────────────────
# VÉRIFICATION (1x/jour)
# ─────────────────────────────────────────────────────────────

def check(send: bool = True, today: dt.date | None = None) -> dict:
    if not config.HALVING.get("enabled"):
        return {"skip": True}
    today = today or dt.date.today()
    buy_date, sell_date = _dates()

    from memory import state
    sent = state.get_state(STATE_KEY, default={}) or {}

    fired = []
    for type_alerte, sdate in (("achat", buy_date), ("vente", sell_date)):
        days = (sdate - today).days
        for milestone in config.HALVING["milestones"]:
            key = f"{type_alerte}_{milestone}"
            if days <= milestone and not sent.get(key):
                msg = _msg(type_alerte, milestone)
                if not msg:
                    continue
                if send:
                    try:
                        from alerts import telegram_bot
                        telegram_bot.send_message(msg, parse_mode="Markdown")
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Envoi halving %s échoué : %s", key, e)
                        continue
                sent[key] = True
                fired.append(key)

    if fired:
        state.set_state(STATE_KEY, sent)
    logger.info("Halving : achat %s, vente %s, alertes %s",
                (buy_date - today).days, (sell_date - today).days, fired)
    return {"buy_in_days": (buy_date - today).days,
            "sell_in_days": (sell_date - today).days, "fired": fired}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(check(send=False))
