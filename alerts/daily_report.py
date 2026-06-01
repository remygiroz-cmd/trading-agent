"""
alerts/daily_report.py — Bilan quotidien (22h30) et commandes Telegram.

- format_daily_report : synthèse des signaux du jour + performance + ajustements
- handle_command : traite les commandes (/pause, /actif, /digest, /bilan, /stats, /status)
- handle_callback : traite les clics boutons (Pris / Ignoré / Surveille)
- poll_and_respond : draine les messages/clics en attente et répond (appelé à
  chaque exécution cron + dans la boucle continue)
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

    # Bloc santé : permet de distinguer "rien à signaler" d'un "bug"
    msg += "\n\n" + build_health_block()
    return msg


def build_health_block(date_iso: str | None = None) -> str:
    """
    Résumé de l'activité des scans du jour : permet de savoir si l'absence
    d'alerte est NORMALE (aucun setup au-dessus du seuil) ou suspecte (bug/infra).
    """
    import config
    try:
        from memory import state
        import datetime as dt
        today = date_iso or dt.datetime.now().strftime("%Y-%m-%d")
        log = state.get_state("activity", default={}) or {}
        runs = log.get(today, [])
    except Exception as e:  # noqa: BLE001
        return f"🩺 Santé : impossible de lire l'activité ({e})."

    if not runs:
        return ("🩺 Santé : ⚠️ AUCUN scan enregistré aujourd'hui.\n"
                "Si on est un jour de bourse, c'est anormal (vérifier GitHub Actions).")

    suspended = [r for r in runs if r.get("suspended")]
    if suspended and len(suspended) == len(runs):
        return f"🩺 Santé : marché défavorable toute la journée — scans suspendus.\n{suspended[0]['suspended']}"

    scans = len(runs)
    tickers = max((r.get("tickers", 0) for r in runs), default=0)
    candidates = sum(r.get("candidates", 0) for r in runs)
    finalists = sum(r.get("finalists", 0) for r in runs)
    alerts = sum(r.get("alerts", 0) for r in runs)
    best = max((r.get("best_score", 0) for r in runs), default=0)
    seuil = config.ALERT_RULES["min_final_score"]

    health = (f"🩺 Santé du jour : {scans} scan(s), {tickers} tickers analysés, "
              f"{candidates} candidats, {finalists} étudiés par les IA.")
    if alerts == 0:
        if tickers == 0:
            health += ("\n⚠️ 0 ticker analysé — possible souci de données (Yahoo). "
                       "À surveiller.")
        elif finalists == 0:
            health += ("\n✅ Aucun setup assez propre aujourd'hui pour mériter une analyse IA. "
                       "Pas d'alerte = NORMAL.")
        else:
            health += (f"\n✅ Meilleur score du jour : {best:.0f}/100 (seuil {seuil}). "
                       "En dessous du seuil → pas d'alerte. NORMAL.")
    else:
        health += f"\n🔔 {alerts} alerte(s) envoyée(s) aujourd'hui."
    return health


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

    if cmd == "/diag":
        return build_health_block()

    if cmd in ("/buzz_on", "/buzz_off", "/buzz"):
        try:
            import buzz
            if cmd == "/buzz_on":
                buzz.restart()
                return "📡 Radar buzz relancé pour 7 jours."
            if cmd == "/buzz_off":
                s = buzz._get_state(); s["active"] = False; s["recap_sent"] = True; buzz._set_state(s)
                return "🛑 Radar buzz arrêté."
            # /buzz : état actuel
            from memory import state as _st
            log = _st.get_state("buzz_log", default=[]) or []
            s = buzz._get_state()
            return (f"📡 Radar buzz : {'actif' if s.get('active') and not s.get('recap_sent') else 'inactif'}\n"
                    f"Picks enregistrés : {len(log)} depuis {s.get('start_date','n/a')}")
        except Exception as e:  # noqa: BLE001
            return f"Erreur buzz : {e}"

    if cmd == "/paper":
        return _paper_recap()

    if cmd == "/stop_paper":
        return _stop_paper()

    if cmd == "/reprendre_paper":
        try:
            import paper_trading
            paper_trading.resume_paper()
            return "▶️ Paper trading réactivé."
        except Exception as e:  # noqa: BLE001
            return f"Erreur : {e}"

    if cmd in ("/start", "/help"):
        return ("👋 Agent boursier connecté.\n"
                "Commandes :\n"
                "/paper — récap du portefeuille virtuel (1000 €/trade)\n"
                "/diag — santé du jour (scans, candidats, meilleur score)\n"
                "/stats — poids des IA\n"
                "/status — état du système\n"
                "/bilan — signaux du jour\n"
                "/pause /actif /digest — mode d'alerte\n"
                "/stop_paper — arrêter le paper trading (passage réel)")

    return "Commande inconnue. Tape /help."


def _load_offset() -> int | None:
    from memory import state
    return (state.get_state("telegram_offset", default={}) or {}).get("offset")


def _save_offset(offset: int) -> None:
    from memory import state
    state.set_state("telegram_offset", {"offset": offset})


def poll_and_respond(timeout: int = 0) -> int:
    """
    Draine les updates Telegram en attente : commandes texte + clics boutons.
    Mémorise l'offset pour ne traiter chaque update qu'une fois.
    Retourne le nombre d'updates traités.
    """
    offset = _load_offset()
    updates = telegram_bot.get_updates(offset=offset, timeout=timeout)
    handled = 0
    for u in updates:
        _save_offset(u["update_id"] + 1)
        try:
            cq = u.get("callback_query")
            if cq:
                reply = handle_callback(cq.get("data", ""))
                telegram_bot.answer_callback(cq["id"], reply)
                telegram_bot.send_message(reply)
                handled += 1
                continue
            msg = u.get("message") or u.get("edited_message") or {}
            text = msg.get("text", "")
            if text:
                reply = handle_command(text)
                telegram_bot.send_message(reply)
                handled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("Traitement update échoué : %s", e)
    if handled:
        logger.info("%s commande(s)/clic(s) Telegram traités", handled)
    return handled


def _paper_recap() -> str:
    try:
        import paper_trading
        p = paper_trading.compute_portfolio(live=True)
        return paper_trading.format_portfolio(p)
    except Exception as e:  # noqa: BLE001
        return f"Récap paper indisponible : {e}"


def _stop_paper() -> str:
    try:
        import paper_trading
        p = paper_trading.compute_portfolio(live=True)
        paper_trading.stop_paper()
        return ("🛑 Paper trading ARRÊTÉ.\n"
                f"Bilan final : {p['pnl_eur']:+.0f} € sur {p['n_closed']} trades clôturés "
                f"({p['win_rate']*100:.0f}% de réussite).\n"
                "Les prochaines alertes seront en mode RÉEL (is_paper=false).\n"
                "Pour revenir en arrière : /reprendre_paper")
    except Exception as e:  # noqa: BLE001
        return f"Erreur arrêt paper : {e}"


def _set_mode(cmd: str) -> None:
    """Persiste le mode d'alerte dans l'état (Supabase)."""
    mode = {"/pause": "pause", "/actif": "actif", "/digest": "digest"}[cmd]
    from memory import state
    state.set_state("alert_mode", {"mode": mode})


def get_alert_mode() -> str:
    from memory import state
    return (state.get_state("alert_mode", default={}) or {}).get("mode", "actif")


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
