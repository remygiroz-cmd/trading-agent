"""
btc_mvrv.py — Suivi du MVRV Z-Score de Bitcoin + alertes de franchissement de seuil.

Le MVRV Z-Score mesure si Bitcoin est sur/sous-évalué vs le coût moyen des holders.
On vérifie sa valeur une fois par jour et on alerte UNIQUEMENT au franchissement
d'un seuil (pour ne pas spammer) :

  - passe SOUS 1.0  -> "zone d'achat qui approche"
  - passe SOUS 0.5  -> "tu approches de la zone d'achat"
  - passe SOUS 0.0  -> "ZONE D'ACHAT FORTE"
  - repasse AU-DESSUS de 3.0 -> "tu sors de la zone d'achat"

Source : API publique bitcoin-data.com (gratuite). Parsing défensif.
"""

import logging
import datetime as dt

import requests

import config

logger = logging.getLogger("btc_mvrv")

STATE_KEY = "btc_mvrv_state"

try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001
    _PARIS = None


def _now_str() -> str:
    n = dt.datetime.now(_PARIS) if _PARIS else dt.datetime.now()
    return n.strftime("%Y-%m-%d %H:%M")


# ─────────────────────────────────────────────────────────────
# RÉCUPÉRATION DE LA VALEUR
# ─────────────────────────────────────────────────────────────

def fetch_mvrv() -> float | None:
    """Dernière valeur du MVRV Z-Score (ou None si indisponible)."""
    url = config.BTC_MVRV["api_url"]
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "trading-agent"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("MVRV indisponible : %s", str(e)[:120])
        return None

    if isinstance(data, list) and data:
        data = data[-1]
    if isinstance(data, dict):
        for k in ("mvrvZscore", "mvrv_zscore", "mvrvzscore", "value", "mvrv", "y", "v"):
            if data.get(k) is not None:
                try:
                    return float(data[k])
                except (TypeError, ValueError):
                    continue
    try:
        return float(data)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────
# MESSAGES (textes fournis par Rémy)
# ─────────────────────────────────────────────────────────────

def _msg_1(v, ts):
    return (f"📊 *BITCOIN — Zone d'achat qui approche*\n\n"
            f"Le MVRV Z-Score vient de passer sous 1.0 (valeur actuelle : `{v:.2f}`).\n\n"
            "Cet indicateur mesure si Bitcoin est sur ou sous-évalué par rapport au prix "
            "moyen d'achat de tous les holders. Plus il est bas, plus le marché est "
            "\"bon marché\" historiquement.\n\n"
            "👉 Tu n'es pas encore en zone d'achat forte, mais c'est le moment de te "
            f"tenir prêt.\n\n_{ts}_")


def _msg_05(v, ts):
    return (f"🟡 *BITCOIN — Tu approches de la zone d'achat*\n\n"
            f"MVRV Z-Score : `{v:.2f}` (sous 0.5)\n\n"
            "Historiquement, ce niveau précède les zones de bottom de cycle. Bitcoin est "
            "significativement sous-évalué par rapport au coût moyen des holders.\n\n"
            f"👉 Commence à réfléchir à une entrée progressive (DCA).\n\n_{ts}_")


def _msg_0(v, ts):
    return (f"🟢 *BITCOIN — ZONE D'ACHAT FORTE*\n\n"
            f"MVRV Z-Score : `{v:.2f}` (négatif !)\n\n"
            "C'est le signal que tu attendais. Historiquement, chaque fois que cet "
            "indicateur est passé négatif, c'était un bottom de cycle majeur "
            "(2015, 2019, fin 2022).\n\n"
            "👉 C'est la zone d'accumulation maximale selon ta stratégie. Croise avec la "
            f"stratégie 500 jours halving (prochain signal achat : novembre 2026).\n\n_{ts}_")


def _msg_sell(v, ts):
    return (f"🔴 *BITCOIN — Tu sors de la zone d'achat*\n\n"
            f"MVRV Z-Score : `{v:.2f}` (au-dessus de 3.0)\n\n"
            "Le marché redevient surévalué. Si tu as accumulé pendant la zone basse, c'est "
            "le moment de surveiller tes seuils de vente (3.0 / 3.5 / 4.0 / 4.5 / 5.0).\n\n"
            f"👉 Reste vigilant, consulte ton plan de sortie progressif.\n\n_{ts}_")


def _zone_label(v: float) -> str:
    if v < 0:
        return "🟢 Zone d'achat FORTE (négatif)."
    if v < 0.5:
        return "🟡 Proche de la zone d'achat (sous 0.5)."
    if v < 1.0:
        return "📊 Tu peux te tenir prêt (sous 1.0)."
    if v > 3.0:
        return "🔴 Marché surévalué (au-dessus de 3.0) — zone de surveillance de vente."
    return "⚪ Zone neutre."


def _status_message(v, ts):
    return (f"📡 *BITCOIN — Suivi MVRV Z-Score activé*\n\n"
            f"Valeur actuelle : `{v:.2f}`\n{_zone_label(v)}\n\n"
            "Je te préviendrai à chaque franchissement de seuil "
            f"(1.0 / 0.5 / 0 à l'achat · 3.0 à la sortie).\n\n_{ts}_")


# ─────────────────────────────────────────────────────────────
# VÉRIFICATION (1x/jour)
# ─────────────────────────────────────────────────────────────

def check(send: bool = True) -> dict:
    """Lit le MVRV, détecte les franchissements depuis la dernière valeur, alerte."""
    if not config.BTC_MVRV.get("enabled"):
        return {"skip": True}
    v = fetch_mvrv()
    if v is None:
        return {"error": "valeur indisponible"}

    from memory import state
    st = state.get_state(STATE_KEY, default={}) or {}
    prev = st.get("prev")
    ts = _now_str()

    messages = []
    if prev is None:
        messages.append(_status_message(v, ts))   # 1er passage : statut actuel
    else:
        if prev >= 1.0 > v:
            messages.append(_msg_1(v, ts))
        if prev >= 0.5 > v:
            messages.append(_msg_05(v, ts))
        if prev >= 0.0 > v:
            messages.append(_msg_0(v, ts))
        if prev <= 3.0 < v:
            messages.append(_msg_sell(v, ts))

    if send:
        try:
            from alerts import telegram_bot
            for m in messages:
                telegram_bot.send_message(m, parse_mode="Markdown")
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi MVRV échoué : %s", e)

    state.set_state(STATE_KEY, {"prev": v, "updated": ts})
    logger.info("MVRV = %.2f (prev=%s), %s alerte(s)", v, prev, len(messages))
    return {"value": v, "prev": prev, "alerts": len(messages)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(check(send=False))
