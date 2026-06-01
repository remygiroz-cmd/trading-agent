"""
main.py — Point d'entrée principal de l'agent de surveillance boursière.

Cycle complet d'un scan :
  1. Filtre marché global (SPX/VIX) — sinon scan suspendu
  2. Watchlist (fixe + dynamique) filtrée par marché, hors blacklist
  3. Pré-filtre algorithmique -> candidats
  4. Détection des figures + score de qualité (>= 30/50 -> finaliste)
  5. Débat 3 IA -> vote final pondéré
  6. Si alerte (>=75/100 et >=2 ACHETER) : enregistrement en base + alerte Telegram
     + position paper trading

Utilisation :
  python main.py scan [label]        # lance un scan (label : ouverture/midi/...)
  python main.py report              # envoie le bilan quotidien
  python main.py rebuild-watchlist   # reconstruit la watchlist dynamique
  python main.py test-cycle          # cycle complet en mode simulation (sans alerte réelle)
"""

import sys
import logging
import datetime as dt

import config
import data_fetcher
import market_filter
import watchlist
import prefilter
import patterns
import paper_trading
from agents import debate, context_builder

logger = logging.getLogger("main")


# ─────────────────────────────────────────────────────────────
# ASSEMBLAGE D'UN SIGNAL À PARTIR DU DÉBAT
# ─────────────────────────────────────────────────────────────

def _f(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def assemble_signal(ticker: str, snapshot: dict, pattern: dict,
                    debate_out: dict, timeframe: str = "1d", is_paper: bool = True) -> dict:
    """Construit l'enregistrement de signal + les champs d'affichage de l'alerte."""
    votes = debate_out["final_votes"]
    ds, gk, cl = votes.get("deepseek", {}), votes.get("grok", {}), votes.get("claude", {})
    result = debate_out["result"]

    price = snapshot.get("price")
    # Objectif / stop : calés sur la volatilité (ATR) — bien plus efficaces que des
    # % fixes d'après le backtest. L'horizon vient de DeepSeek si disponible.
    import market_context
    levels = market_context.compute_levels(price, snapshot.get("atr_pct")) if price else {}
    target = levels.get("target") or _f(ds.get("objectif_prix"))
    stop = levels.get("stop") or _f(ds.get("stop_loss"))
    horizon = int(_f(ds.get("horizon_jours"), levels.get("horizon", 10)) or levels.get("horizon", 10))
    max_pos = int(_f(cl.get("taille_position_max_pct"), 5) or 5)

    upside = ((target - price) / price * 100) if (price and target) else 0.0
    downside = ((price - stop) / price * 100) if (price and stop) else 0.0

    # Enregistrement base (colonnes trading_signals)
    record = {
        "ticker": ticker,
        "pattern_name": pattern.get("pattern"),
        "timeframe": timeframe,
        "entry_price": price,
        "target_price": target,
        "stop_loss": stop,
        "setup_score": int(pattern.get("setup_score", 0)),
        "final_score": int(result["final_score"]),
        "buy_votes": result["buy_votes"],
        "horizon_days": horizon,
        "is_paper": is_paper,
    }

    # Champs d'affichage de l'alerte
    display = {
        **record,
        "price": price, "target": target, "stop": stop,
        "upside": upside, "downside": downside, "max_position_pct": max_pos,
        "deepseek_verdict": ds.get("verdict", "?"), "deepseek_score": ds.get("score", "?"),
        "grok_verdict": gk.get("verdict", "?"), "grok_score": gk.get("score", "?"),
        "claude_verdict": cl.get("verdict", "?"), "claude_score": cl.get("score", "?"),
        "deepseek_reason": ds.get("raison_principale", ""),
        "grok_reason": gk.get("raison_principale", ""),
        "claude_reason": cl.get("raison_principale", ""),
        "claude_warning": cl.get("risque_macro") or cl.get("risque_fondamental"),
    }
    return {"record": record, "display": display}


def persist_and_alert(assembled: dict, debate_out: dict, send: bool = True) -> str | None:
    """Enregistre le signal + les votes en base, puis envoie l'alerte Telegram."""
    signal_id = None
    try:
        from memory import signals as sigmod
        row = sigmod.insert_signal(assembled["record"])
        if row:
            signal_id = row["id"]
            weights = debate_out.get("weights", {})
            for tour_name, tour_votes in [("round1", debate_out.get("round1")),
                                          ("round2", debate_out.get("round2"))]:
                if not tour_votes:
                    continue
                tour_num = 1 if tour_name == "round1" else 2
                for agent, vote in tour_votes.items():
                    sigmod.insert_vote(signal_id, agent, tour_num, vote, weights.get(agent))
    except Exception as e:  # noqa: BLE001
        logger.error("Persistance signal échouée : %s", e)

    # Export Google Sheets (si configuré)
    if signal_id:
        try:
            from alerts import sheets
            row = dict(assembled["record"], id=signal_id)
            sheets.export_signal(row)
        except Exception as e:  # noqa: BLE001
            logger.warning("Export Sheets échoué : %s", e)

    if send:
        try:
            from alerts import telegram_bot, daily_report
            mode = daily_report.get_alert_mode()
            if mode == "pause":
                logger.info("Mode pause — alerte non envoyée (%s).", assembled["record"]["ticker"])
            else:
                telegram_bot.send_alert(assembled["display"], signal_id=signal_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Envoi alerte échoué : %s", e)

    return signal_id


# ─────────────────────────────────────────────────────────────
# CYCLE DE SCAN
# ─────────────────────────────────────────────────────────────

def run_scan(label: str = "manuel", markets: list[str] | None = None,
             send_alerts: bool = True, max_finalists: int | None = None) -> dict:
    """Exécute un cycle de scan complet. Retourne un résumé."""
    markets = markets or ["EU", "US"]
    # Plafond de débats IA par scan (coût + temps d'exécution borné)
    if max_finalists is None:
        max_finalists = config.ALERT_RULES.get("max_finalists_per_scan", 8)
    logging.info("===== SCAN '%s' (marchés %s) =====", label, markets)

    summary = {"label": label, "candidates": 0, "finalists": 0, "alerts": 0, "details": []}

    # 1. Filtre marché
    def notifier(msg):
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception:  # noqa: BLE001
            pass

    market = market_filter.get_market_status()
    if not market["ok"]:
        logger.warning("Scan suspendu : %s", market["reason"])
        if send_alerts:
            notifier(market["reason"])
        summary["suspended"] = market["reason"]
        _record_activity(summary)
        return summary

    # 2. Watchlist filtrée
    try:
        from memory import performance
        blacklist = performance.get_blacklisted_tickers()
    except Exception:  # noqa: BLE001
        blacklist = set()

    # Sécurité : si la watchlist dynamique est vide (1er run, ou rebuild du lundi
    # raté/retardé par GitHub), on la reconstruit avant de scanner.
    if not watchlist.load_dynamic_watchlist():
        logger.warning("Watchlist dynamique vide — reconstruction de secours.")
        try:
            watchlist.rebuild_dynamic_watchlist(blacklist=blacklist)
        except Exception as e:  # noqa: BLE001
            logger.error("Reconstruction de secours échouée : %s", e)

    full = watchlist.get_full_watchlist(blacklist=blacklist)
    tickers = watchlist.filter_by_markets(full, markets)
    summary["tickers"] = len(tickers)
    logger.info("Watchlist : %s tickers (%s marchés)", len(tickers), markets)

    # 3. Pré-filtre
    candidates = prefilter.run_prefilter(tickers, batch=True)
    summary["candidates"] = len(candidates)
    cand_tickers = [c["ticker"] for c in candidates]
    logger.info("Pré-filtre : %s candidats", len(cand_tickers))
    if not cand_tickers:
        _record_activity(summary)
        return summary

    # 4. Figures + filtres qualité + débat sur les finalistes
    data = data_fetcher.fetch_batch(cand_tickers, period="200d", interval="1d")
    paper = paper_trading.is_paper_active()
    ai_weights = debate_out_weights()

    # Référence marché pour la force relative (#3)
    import market_context
    spx_df = data_fetcher.fetch_ticker(config.RELATIVE_STRENGTH["market_ticker"],
                                       period="200d", interval="1d")

    finalists = 0
    for tk in cand_tickers:
        df = data.get(tk)
        if df is None or df.empty:
            continue
        df = data_fetcher.add_indicators(df)
        snap = data_fetcher.latest_snapshot(df)
        scan = patterns.scan_ticker(df, {"price": snap.get("price"), "ma50": snap.get("ma50")},
                                    market["bullish"])
        best = scan["best"]
        if not best or best.get("setup_score", 0) < config.ALERT_RULES["min_setup_score"]:
            continue

        # #3 Force relative : le titre doit surperformer le marché
        rs_ok, rs = market_context.passes_relative_strength(df, spx_df)
        if not rs_ok:
            logger.info("%s écarté : force relative négative (%.1f%% vs marché)",
                        tk, (rs.get("outperformance") or 0) * 100)
            continue

        # #2 Filtre résultats : pas de signal si résultats pendant la détention
        horizon_guess = int(best.get("base_candles") or 10)
        earn_soon, days_e = market_context.earnings_in_horizon(tk, max(horizon_guess, 10))
        if earn_soon:
            logger.info("%s écarté : résultats dans %s jours (risque de gap)", tk, days_e)
            continue

        finalists += 1
        if max_finalists and finalists > max_finalists:
            logger.info("Plafond finalistes atteint (%s)", max_finalists)
            break

        logger.info("Finaliste %s : %s (%.1f/50, RS +%.1f%%) -> débat", tk, best["pattern"],
                    best["setup_score"], (rs.get("outperformance") or 0) * 100)
        ctx = context_builder.build_context(tk, snap, best, market)
        # enrichir le contexte IA avec RS et résultats
        ctx["sector_trend"] = (f"force relative {(rs.get('outperformance') or 0)*100:+.1f}% vs marché")
        ctx["next_earnings"] = f"dans {days_e} jours" if days_e is not None else "n/d"
        debate_out = debate.run_debate(ctx, weights=ai_weights)

        res = debate_out["result"]
        detail = {"ticker": tk, "pattern": best["pattern"],
                  "setup_score": best["setup_score"], "final_score": res["final_score"],
                  "buy_votes": res["buy_votes"], "alert": res["send_alert"]}
        summary["details"].append(detail)

        if res["send_alert"]:
            assembled = assemble_signal(tk, snap, best, debate_out, is_paper=paper)
            persist_and_alert(assembled, debate_out, send=send_alerts)
            summary["alerts"] += 1

    summary["finalists"] = finalists
    summary["best_score"] = max((d["final_score"] for d in summary["details"]), default=0)
    logger.info("Scan terminé : %s candidats, %s finalistes, %s alertes",
                summary["candidates"], finalists, summary["alerts"])
    _record_activity(summary)
    return summary


def _record_activity(summary: dict) -> None:
    """Enregistre l'activité du scan (pour le bilan santé du soir)."""
    try:
        from memory import state
        today = dt.datetime.now().strftime("%Y-%m-%d")
        log = state.get_state("activity", default={}) or {}
        day = log.get(today, [])
        day.append({
            "label": summary.get("label"),
            "tickers": summary.get("tickers", 0),
            "candidates": summary.get("candidates", 0),
            "finalists": summary.get("finalists", 0),
            "alerts": summary.get("alerts", 0),
            "best_score": summary.get("best_score", 0),
            "suspended": summary.get("suspended"),
        })
        state.set_state("activity", {today: day})  # ne conserve qu'aujourd'hui
    except Exception as e:  # noqa: BLE001
        logger.warning("Enregistrement activité échoué : %s", e)


def debate_out_weights():
    try:
        from memory import weights
        return weights.get_current_weights()
    except Exception:  # noqa: BLE001
        return dict(config.INITIAL_WEIGHTS)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def run_selftest() -> None:
    """Vérifie l'environnement (clés, Supabase, Telegram) — utile pour valider le cloud."""
    checks = config.validate_config()
    present = [k for k, v in checks.items() if v]
    missing = [k for k, v in checks.items() if not v]
    logger.info("Clés présentes : %s", ", ".join(present) or "aucune")
    if missing:
        logger.warning("Clés manquantes : %s", ", ".join(missing))

    db_ok = False
    try:
        from memory import database
        db_ok = database.ping()
    except Exception as e:  # noqa: BLE001
        logger.error("Supabase : %s", e)
    logger.info("Supabase : %s", "OK" if db_ok else "ÉCHEC")

    market = "n/d"
    try:
        import market_filter
        market = market_filter.get_market_status()["reason"]
    except Exception as e:  # noqa: BLE001
        logger.warning("Marché : %s", e)

    try:
        from alerts import telegram_bot
        telegram_bot.send_message(
            "🤖 Selftest cloud OK\n"
            f"• Clés : {len(present)}/8 présentes\n"
            f"• Supabase : {'OK' if db_ok else 'ÉCHEC'}\n"
            f"• Marché : {market}"
        )
        logger.info("Message Telegram envoyé.")
    except Exception as e:  # noqa: BLE001
        logger.error("Telegram : %s", e)


def main(argv: list[str]):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("data_fetcher").setLevel(logging.WARNING)

    cmd = argv[0] if argv else "scan"

    if cmd == "scan":
        label = argv[1] if len(argv) > 1 else "manuel"
        run_scan(label=label)
    elif cmd == "test-cycle":
        # cycle complet sans envoi d'alerte, plafonné pour limiter le coût IA
        s = run_scan(label="test", send_alerts=False, max_finalists=2)
        print("\nRésumé test-cycle :", s)
    elif cmd == "rebuild-watchlist":
        try:
            from memory import performance
            bl = performance.get_blacklisted_tickers()
        except Exception:  # noqa: BLE001
            bl = set()
        n = watchlist.rebuild_dynamic_watchlist(blacklist=bl)
        print(f"Watchlist dynamique reconstruite : {len(n)} tickers")
    elif cmd == "report":
        from scheduler import send_daily_report_now
        send_daily_report_now()
    elif cmd == "cron":
        # Dispatcher horaire (appelé par GitHub Actions / cron externe)
        import scheduler
        print(scheduler.run_due())
    elif cmd == "poll":
        # Traite uniquement les commandes/clics Telegram en attente (pas de scan)
        from alerts import daily_report
        n = daily_report.poll_and_respond()
        print(f"{n} commande(s)/clic(s) traités")
    elif cmd == "selftest":
        run_selftest()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
