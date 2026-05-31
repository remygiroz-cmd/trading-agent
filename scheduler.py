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
        adjustments = (f"{res['updated']} signaux mis à jour, "
                       f"{res['targets']} objectifs atteints, {res['stops']} stops touchés.")
    except Exception as e:  # noqa: BLE001
        logger.warning("Apprentissage quotidien échoué : %s", e)

    # 2. Bilan Telegram
    today = now_paris().date().isoformat()
    sigs = signals.get_today_signals(today)
    w = weights.get_current_weights()
    best_agent = max(w, key=w.get) if w else "n/d"
    perf = {"week_win_rate": _week_win_rate(), "best_agent": best_agent}
    daily_report.send_daily_report(today, sigs, perf, adjustments=adjustments)


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
    try:
        from memory import signals
        sigs = signals.get_open_signals()  # approximation : derniers signaux
        done = [float(s["result_7d"]) for s in sigs if s.get("result_7d") is not None]
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
    n = now_paris()
    if not is_trading_day(n.date()):
        logger.info("Jour non ouvré — rien à faire.")
        return {"skipped": "week-end"}

    nowmin = n.hour * 60 + n.minute

    def near(hhmm: str) -> bool:
        h, m = map(int, hhmm.split(":"))
        return abs(nowmin - (h * 60 + m)) <= tolerance_min

    # Tâches hebdo (lundi matin)
    if n.weekday() == 0 and near(config.WATCHLIST_REBUILD_TIME):
        trigger_weekly_tasks()
        return {"ran": "weekly"}

    # Bilan quotidien
    if near(config.DAILY_REPORT_TIME):
        send_daily_report_now()
        return {"ran": "report"}

    # Scans
    for s in config.SCAN_SCHEDULE:
        if near(s["time"]):
            return {"ran": "scan", "label": s["label"],
                    "result": trigger_scan(s["label"], s["markets"])}

    logger.info("Aucune tâche planifiée à %s (Paris).", n.strftime("%H:%M"))
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
