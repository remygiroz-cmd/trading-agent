"""
scheduler.py — Planification des scans et tâches récurrentes.

Deux modes d'utilisation :
  1. Déclenchement externe (recommandé en serverless / cron Supabase) :
     appeler les fonctions trigger_* depuis un cron qui passe l'heure/label.
  2. Boucle continue (VM/PC) : run_loop() vérifie l'heure chaque minute et
     déclenche les scans aux horaires de config.SCAN_SCHEDULE.

Horaires en Europe/Paris, jours ouvrés uniquement.
Suspension automatique si le filtre marché est défavorable (géré dans main).
"""

import time
import logging
import datetime as dt

import config
import main as agent_main

logger = logging.getLogger("scheduler")

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo(config.TIMEZONE)
except Exception:  # noqa: BLE001
    PARIS = None


def now_paris() -> dt.datetime:
    return dt.datetime.now(PARIS) if PARIS else dt.datetime.now()


def is_trading_day(d: dt.date | None = None) -> bool:
    d = d or now_paris().date()
    return d.weekday() < 5  # lundi=0 .. vendredi=4


# ─────────────────────────────────────────────────────────────
# DÉCLENCHEURS (utilisables par un cron externe)
# ─────────────────────────────────────────────────────────────

def trigger_scan(label: str, markets: list[str]) -> dict:
    if not is_trading_day():
        logger.info("Jour non ouvré — scan '%s' ignoré.", label)
        return {"skipped": "week-end"}
    return agent_main.run_scan(label=label, markets=markets)


def send_daily_report_now() -> None:
    """Bilan quotidien (22h30) : MAJ des résultats + apprentissage + envoi du bilan."""
    from alerts import daily_report
    from memory import signals, weights

    # 1. Boucle d'apprentissage quotidienne (résultats J+1/3/7, perf ticker)
    adjustments = "(aucun)"
    try:
        from memory import learning
        res = learning.run_daily_learning()
        cl = res.get("closures", {})
        adjustments = (f"{res['updated']} signaux mis à jour, "
                       f"{cl.get('closed', 0)} position(s) vendue(s) "
                       f"{cl.get('by_reason', {})}.")
    except Exception as e:  # noqa: BLE001
        logger.warning("Apprentissage quotidien échoué : %s", e)

    # 1ter. Mémoire actualités : ingestion quotidienne de la watchlist dynamique
    # (la mémoire s'accumule au-delà des seuls finalistes des scans).
    try:
        import news, watchlist
        wl = watchlist.load_dynamic_watchlist() or watchlist.get_full_watchlist()
        news.refresh_watchlist_news(wl)
    except Exception as e:  # noqa: BLE001
        logger.warning("Refresh news quotidien échoué : %s", e)

    # 1bis. Synchronisation Google Sheets (résultats mis à jour)
    try:
        from alerts import sheets
        if sheets.enabled():
            from memory import database
            recent = (database.table("trading_signals").select("*")
                      .order("created_at", desc=True).limit(100).execute()).data or []
            sheets.sync_signals(recent)
    except Exception as e:  # noqa: BLE001
        logger.warning("Sync Sheets échouée : %s", e)

    # 2. Bilan Telegram
    today = now_paris().date().isoformat()
    sigs = signals.get_today_signals(today)
    w = weights.get_current_weights()
    best_agent = max(w, key=w.get) if w else "n/d"
    perf = {"week_win_rate": _week_win_rate(), "best_agent": best_agent}
    daily_report.send_daily_report(today, sigs, perf, adjustments=adjustments)

    # 3. Bilan du soir du radar buzz (picks du jour simulés)
    try:
        if config.BUZZ["enabled"]:
            import buzz
            buzz.daily_buzz_check(now_paris().date())
    except Exception as e:  # noqa: BLE001
        logger.warning("Bilan buzz du soir échoué : %s", e)

    # 4. Simulation des seuils CHAQUE SOIR (70 / 65 / 60)
    try:
        import thresholds
        thresholds.run(send=True, levels=(70, 65, 60))
    except Exception as e:  # noqa: BLE001
        logger.warning("Simulation seuils du soir échouée : %s", e)

    # 4bis. Simulation budget réel (1500 €) — chaque soir
    try:
        import budget_sim
        budget_sim.run(send=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("Simulation budget du soir échouée : %s", e)

    # 5. Récap GLOBAL de la semaine — le vendredi soir
    try:
        if now_paris().weekday() == 4:  # vendredi
            _send_weekly_recap()
    except Exception as e:  # noqa: BLE001
        logger.warning("Récap hebdo échoué : %s", e)


def _send_weekly_recap() -> None:
    """Récap global de la semaine (perf + simulation des seuils + buzz)."""
    from alerts import telegram_bot
    parts = ["📅 RÉCAP DE LA SEMAINE", "━━━━━━━━━━━━━━━━━━━━━"]
    try:
        import dashboard
        parts.append(dashboard.build_text_summary())
    except Exception as e:  # noqa: BLE001
        logger.warning("Perf hebdo indisponible : %s", e)
    try:
        import thresholds
        parts.append("\n" + thresholds.format_report(thresholds.simulate((70, 65, 60))))
    except Exception:  # noqa: BLE001
        pass
    try:
        import budget_sim
        parts.append("\n" + budget_sim.format_report(budget_sim.simulate()))
    except Exception:  # noqa: BLE001
        pass
    try:
        from memory import state
        t = state.get_state("buzz_daily_tally", default=None)
        if t and t.get("trades"):
            wr = t["wins"] / t["trades"] * 100
            parts.append(f"\n📡 Buzz (cumul essai) : {t['wins']}/{t['trades']} gagnants "
                         f"({wr:.0f}%), {t['pnl']:+,.0f} €")
    except Exception:  # noqa: BLE001
        pass
    telegram_bot.send_message("\n".join(parts))


def trigger_weekly_tasks() -> None:
    """Tâches du lundi matin : watchlist dynamique + règles apprises + recalcul poids."""
    try:
        from memory import performance
        bl = performance.get_blacklisted_tickers()
    except Exception:  # noqa: BLE001
        bl = set()
    import watchlist
    watchlist.rebuild_dynamic_watchlist(blacklist=bl)
    try:
        from memory import learning
        res = learning.run_weekly_learning()
        logger.info("Hebdo : %s règles créées, poids %s",
                    res["rules_created"], res["weights"])
    except Exception as e:  # noqa: BLE001
        logger.warning("Apprentissage hebdo échoué : %s", e)


def _week_win_rate() -> float:
    """Taux de réussite des signaux RÉSOLUS des 7 derniers jours.

    NB : l'ancienne version lisait result_7d sur les signaux *ouverts* (qui par
    définition n'en ont pas) -> affichait toujours 0%.
    """
    try:
        from memory import database
        week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
        rows = (database.table("trading_signals")
                .select("result_7d, created_at")
                .gte("created_at", week_ago)
                .execute()).data or []
        done = [float(r["result_7d"]) for r in rows if r.get("result_7d") is not None]
        if not done:
            return 0.0
        return sum(1 for r in done if r > 0) / len(done)
    except Exception:  # noqa: BLE001
        return 0.0


def run_due(tolerance_min: int = 8) -> dict:
    """
    Dispatcher pour cron externe : exécute la tâche dont l'horaire correspond à
    l'instant présent (à `tolerance_min` minutes près). Conçu pour être appelé
    par un cron (GitHub Actions, etc.) aux horaires prévus.
    """
    # Interrupteur général : si l'agent est désactivé, on ne fait STRICTEMENT rien
    # (aucun scan, aucun appel IA, aucun buzz, aucun bilan) -> zéro coût.
    if not getattr(config, "AGENT_ENABLED", True):
        logger.info("Agent désactivé (AGENT_ENABLED=False) — aucune tâche exécutée.")
        return {"paused": True}

    # Toujours traiter les commandes/clics Telegram en attente (même le week-end)
    try:
        from alerts import daily_report
        daily_report.poll_and_respond()
    except Exception as e:  # noqa: BLE001
        logger.warning("poll_and_respond échoué : %s", e)

    # File du suivi de portefeuille (suivre / unfollow / tweet / liste déposés par
    # le webhook Telegram) — traitée à CHAQUE passage, TOUS LES JOURS (y compris le
    # week-end), sinon les commandes restent bloquées les jours non ouvrés.
    if getattr(config, "MODE", "scan") == "monitor":
        try:
            import monitor
            monitor.process_commands()
        except Exception as e:  # noqa: BLE001
            logger.warning("Traitement file monitor échoué : %s", e)

    n = now_paris()

    # Radar buzz : récap de fin d'essai (peut tomber un week-end) — toujours vérifié
    try:
        if config.BUZZ["enabled"]:
            import buzz
            st = buzz._get_state()
            if st.get("active") and not st.get("recap_sent") and buzz.is_expired(n.date()):
                buzz.send_recap(n.date())
    except Exception as e:  # noqa: BLE001
        logger.warning("Récap buzz échoué : %s", e)

    # Suivi Bitcoin (MVRV Z-Score + calendrier halving) — 1x/jour, tous les jours
    # (la crypto se traite 24/7, donc avant le filtre jour ouvré).
    try:
        from memory import state as _st
        if _st.get_state("btc_last_check", default="") != n.date().isoformat():
            if config.BTC_MVRV["enabled"]:
                import btc_mvrv
                btc_mvrv.check()
            if config.HALVING["enabled"]:
                import halving
                halving.check(today=n.date())
            _st.set_state("btc_last_check", n.date().isoformat())
    except Exception as e:  # noqa: BLE001
        logger.warning("Suivi Bitcoin échoué : %s", e)

    if not is_trading_day(n.date()):
        logger.info("Jour non ouvré — commandes traitées, pas de scan.")
        return {"skipped": "week-end"}

    nowmin = n.hour * 60 + n.minute
    today = n.date().isoformat()

    # Logique de RATTRAPAGE : GitHub Actions déclenche souvent ses crons en retard
    # (ou les saute). Une tâche est "due" dès qu'on dépasse son heure prévue, dans
    # une fenêtre de rattrapage (et tant qu'elle n'a pas déjà tourné aujourd'hui).
    def due(hhmm: str, window_min: int) -> bool:
        h, m = map(int, hhmm.split(":"))
        delta = nowmin - (h * 60 + m)
        return 0 <= delta <= window_min

    def already_done(task: str) -> bool:
        try:
            from memory import state
            runs = state.get_state("last_runs", default={}) or {}
            return task in runs.get(today, [])
        except Exception:  # noqa: BLE001
            return False

    def mark_done(task: str) -> None:
        try:
            from memory import state
            runs = state.get_state("last_runs", default={}) or {}
            runs = {today: list(set(runs.get(today, []) + [task]))}  # ne garde qu'aujourd'hui
            state.set_state("last_runs", runs)
        except Exception:  # noqa: BLE001
            pass

    # ── MODE SUIVI DE PORTEFEUILLE ──
    if getattr(config, "MODE", "scan") == "monitor":
        try:
            import monitor
            # (Les commandes en attente sont déjà traitées en tête de run_due,
            # tous les jours — voir plus haut.)
            times = config.MONITOR["check_times"]
            for i, t in enumerate(times):
                task = "monitor_" + t
                if due(t, 150) and not already_done(task):
                    mark_done(task)
                    if i == 0:                       # 1er créneau du jour = bulletin complet
                        monitor.run_bulletin(send=True)
                    else:                            # créneaux suivants = alertes ponctuelles
                        monitor.check_and_alert(send=True)
                    return {"ran": "monitor", "slot": t}
            logger.info("Monitor : aucun créneau dû à %s.", n.strftime("%H:%M"))
            return {"ran": None}
        except Exception as e:  # noqa: BLE001
            logger.error("Mode monitor échoué : %s", e)
            return {"error": str(e)[:120]}

    # Radar buzz : récaps avant ouverture EU / US (fenêtre de rattrapage 2h)
    try:
        if config.BUZZ["enabled"]:
            import buzz
            if buzz.is_running(n.date()):
                if due(config.BUZZ["eu_time"], 120) and not already_done("buzz_EU"):
                    buzz.run_digest("EU", n.date()); mark_done("buzz_EU")
                if due(config.BUZZ["us_time"], 120) and not already_done("buzz_US"):
                    buzz.run_digest("US", n.date()); mark_done("buzz_US")
    except Exception as e:  # noqa: BLE001
        logger.warning("Récap buzz quotidien échoué : %s", e)

    # Auto-réglage des sorties — ~1x/mois, en semaine, fenêtre de rattrapage 3h.
    # Gros calcul (watchlist complète sur 2 ans) : on l'isole des autres tâches
    # lourdes et on le gate par intervalle (autotune.due) pour ne pas le rejouer.
    if config.AUTOTUNE["enabled"] and due(config.AUTOTUNE["time"], 180) \
            and not already_done("autotune"):
        try:
            import autotune
            if autotune.due(n.date()):
                mark_done("autotune")  # marqué avant : calcul long, on évite les doublons
                res = autotune.run_autotune()
                return {"ran": "autotune", "result": res}
        except Exception as e:  # noqa: BLE001
            logger.warning("Auto-tuning échoué : %s", e)

    # Tâches hebdo (lundi matin) — rattrapage 4h
    if n.weekday() == 0 and due(config.WATCHLIST_REBUILD_TIME, 240) and not already_done("weekly"):
        trigger_weekly_tasks()
        mark_done("weekly")
        return {"ran": "weekly"}

    # Bilan quotidien — rattrapage 90 min
    if due(config.DAILY_REPORT_TIME, 90) and not already_done("report"):
        send_daily_report_now()
        mark_done("report")
        return {"ran": "report"}

    # Scans — rattrapage 2h30 (un scan plus tardif vaut mieux que pas de scan)
    for s in config.SCAN_SCHEDULE:
        task = "scan_" + s["label"]
        if due(s["time"], 150) and not already_done(task):
            mark_done(task)   # marqué avant : un scan est lourd, on évite les doublons concurrents
            return {"ran": "scan", "label": s["label"],
                    "result": trigger_scan(s["label"], s["markets"])}

    logger.info("Aucune tâche due à %s (Paris) — commandes traitées.", n.strftime("%H:%M"))
    return {"ran": None}


# ─────────────────────────────────────────────────────────────
# BOUCLE CONTINUE (mode VM/PC)
# ─────────────────────────────────────────────────────────────

def run_loop(poll_seconds: int = 30):
    """
    Boucle infinie : déclenche les scans/bilans aux horaires prévus.
    Anti-doublon : mémorise les déclenchements déjà faits dans la journée.
    """
    logger.info("Scheduler démarré (timezone %s). Horaires : %s",
                config.TIMEZONE, [s["time"] for s in config.SCAN_SCHEDULE])
    done = set()  # (date, clé)

    while True:
        n = now_paris()
        today = n.date().isoformat()
        hhmm = n.strftime("%H:%M")

        # Nettoyage des marqueurs des jours précédents
        done = {(d, k) for (d, k) in done if d == today}

        if is_trading_day(n.date()):
            for s in config.SCAN_SCHEDULE:
                key = (today, "scan_" + s["label"])
                if hhmm == s["time"] and key not in done:
                    done.add(key)
                    logger.info("Déclenchement scan '%s'", s["label"])
                    try:
                        trigger_scan(s["label"], s["markets"])
                    except Exception as e:  # noqa: BLE001
                        logger.error("Scan '%s' échoué : %s", s["label"], e)

            # Bilan quotidien
            key = (today, "report")
            if hhmm == config.DAILY_REPORT_TIME and key not in done:
                done.add(key)
                try:
                    send_daily_report_now()
                except Exception as e:  # noqa: BLE001
                    logger.error("Bilan échoué : %s", e)

            # Tâches hebdo (lundi)
            key = (today, "weekly")
            if n.weekday() == 0 and hhmm == config.WATCHLIST_REBUILD_TIME and key not in done:
                done.add(key)
                try:
                    trigger_weekly_tasks()
                except Exception as e:  # noqa: BLE001
                    logger.error("Tâches hebdo échouées : %s", e)

        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_loop()
