"""
alerts/daily_report.py — Bilan quotidien (22h30) et commandes Telegram.

- format_daily_report : synthèse des signaux du jour + performance + ajustements
- handle_command : traite les commandes (/pause, /actif, /digest, /bilan, /stats, /status)
- handle_callback : traite les clics boutons (Pris / Ignoré / Surveille)
"""

import logging

from . import telegram_bot

logger = logging.getLogger("daily_report")


TELEGRAM_COMMANDS = {
    "/pause":   "⏸️ Alertes suspendues. Tape /actif pour reprendre.",
    "/digest":  "📥 Mode résumé activé. Une seule alerte à 22h.",
    "/actif":   "🔔 Alertes en temps réel activées.",
    "/bilan":   "Génère le bilan de la semaine en cours.",
    "/stats":   "Affiche les performances globales du système.",
    "/status":  "État actuel du système et prochain scan.",
}


# ─────────────────────────────────────────────────────────────
# BILAN QUOTIDIEN
# ─────────────────────────────────────────────────────────────

def format_daily_report(date: str, signals: list[dict], perf: dict,
                        adjustments: str = "") -> str:
    msg = f"""📊 BILAN DU {date}
━━━━━━━━━━━━━━━━━━━━━━━

Signaux envoyés : {len(signals)}
"""
    for s in signals:
        r1 = s.get("result_1d")
        if r1 is None:
            emoji, val = "⏳", "en cours"
        else:
            r1 = float(r1)
            emoji = "✅" if r1 > 0 else "❌" if r1 < 0 else "➖"
            val = f"{r1*100:+.1f}%"
        msg += f"{emoji} {s.get('ticker')} : {val}\n"

    msg += f"""
Taux réussite semaine : {perf.get('week_win_rate', 0)*100:.0f}%
Meilleure IA semaine  : {perf.get('best_agent', 'n/d')}
"""
    if adjustments:
        msg += f"\n🔧 Ajustements automatiques :\n{adjustments}"
    return msg


def send_daily_report(date: str, signals: list[dict], perf: dict, adjustments: str = "") -> None:
    telegram_bot.send_message(format_daily_report(date, signals, perf, adjustments))


# ─────────────────────────────────────────────────────────────
# COMMANDES
# ─────────────────────────────────────────────────────────────

def handle_command(text: str) -> str:
    """Traite une commande texte et renvoie la réponse à envoyer."""
    cmd = text.strip().split()[0].lower() if text.strip() else ""

    if cmd in ("/pause", "/digest", "/actif"):
        _set_mode(cmd)
        return TELEGRAM_COMMANDS[cmd]

    if cmd == "/status":
        return _status_message()

    if cmd == "/stats":
        return _stats_message()

    if cmd == "/bilan":
        return _week_summary()

    if cmd == "/start":
        return ("👋 Agent boursier connecté.\n"
                "Commandes : /status /stats /bilan /pause /actif /digest")

    return "Commande inconnue. Essaie /status, /stats, /bilan, /pause, /actif."


def _set_mode(cmd: str) -> None:
    """Persiste le mode d'alerte dans un petit fichier d'état local."""
    import json, os
    mode = {"/pause": "pause", "/actif": "actif", "/digest": "digest"}[cmd]
    os.makedirs("data_cache", exist_ok=True)
    with open("data_cache/alert_mode.json", "w", encoding="utf-8") as f:
        json.dump({"mode": mode}, f)


def get_alert_mode() -> str:
    import json, os
    path = "data_cache/alert_mode.json"
    if not os.path.exists(path):
        return "actif"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("mode", "actif")
    except Exception:  # noqa: BLE001
        return "actif"


def _status_message() -> str:
    try:
        import market_filter
        st = market_filter.get_market_status()
        return f"📡 Système actif.\nMode : {get_alert_mode()}\n{st['reason']}"
    except Exception as e:  # noqa: BLE001
        return f"📡 Système actif. Mode : {get_alert_mode()}. (marché indisponible : {e})"


def _stats_message() -> str:
    try:
        from memory import weights
        w = weights.get_current_weights()
        lines = "\n".join(f"  {a} : {v*100:.0f}%" for a, v in w.items())
        return f"📈 Poids actuels des IA :\n{lines}"
    except Exception as e:  # noqa: BLE001
        return f"Stats indisponibles : {e}"


def _week_summary() -> str:
    try:
        from memory import signals as sigmod
        sigs = sigmod.get_today_signals()
        return f"🗓️ {len(sigs)} signal(aux) aujourd'hui. (Bilan hebdo complet à venir Session 8.)"
    except Exception as e:  # noqa: BLE001
        return f"Bilan indisponible : {e}"


# ─────────────────────────────────────────────────────────────
# CALLBACKS (boutons)
# ─────────────────────────────────────────────────────────────

def handle_callback(callback_data: str) -> str:
    """
    Traite un clic bouton. callback_data : 'action_taken:<signal_id>' etc.
    Met à jour user_action en base si un signal_id est présent.
    """
    action_map = {
        "action_taken": ("pris", "✅ Noté : position prise. Je suivrai le résultat."),
        "action_ignored": ("ignore", "❌ Noté : signal ignoré."),
        "action_watching": ("surveille", "⏳ Noté : tu surveilles."),
    }
    parts = callback_data.split(":", 1)
    action_key = parts[0]
    signal_id = parts[1] if len(parts) > 1 else None

    if action_key not in action_map:
        return "Action inconnue."

    user_action, reply = action_map[action_key]
    if signal_id:
        try:
            from memory import signals as sigmod
            sigmod.set_user_action(signal_id, user_action)
        except Exception as e:  # noqa: BLE001
            logger.warning("set_user_action échec : %s", e)
    return reply
