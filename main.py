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
  python main.py autotune [--apply]  # ré-optimise objectifs/stops/horizon (auto-réglage)
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
                    debate_out: dict, timeframe: str = "1d", is_paper: bool = True,
                    ctx: dict | None = None, regime_mult: float = 1.0) -> dict:
    """Construit l'enregistrement de signal + les champs d'affichage de l'alerte."""
    votes = debate_out["final_votes"]
    ds, gk, cl = votes.get("deepseek", {}), votes.get("grok", {}), votes.get("claude", {})
    result = debate_out["result"]
    ctx = ctx or {}

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

    # Conviction composite (technique + fondamental + sentiment) + dimensionnement
    import conviction as conv_mod
    senti = ctx.get("news_sentiment_score")
    fund = ctx.get("fundamental_score_value")
    conv = conv_mod.evaluate(final_score=result["final_score"], fundamental_score=fund,
                             sentiment_score=senti, downside_pct=downside, ai_max_pct=max_pos,
                             regime_mult=regime_mult)

    # Enregistrement base (colonnes trading_signals) + colonnes analytiques (migration 005)
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
        # — colonnes analytiques (best-effort : ignorées si migration 005 non passée) —
        "news_sentiment": round(float(senti), 3) if senti is not None else None,
        "fundamental_score": int(fund) if fund is not None else None,
        "conviction": conv["conviction"],
        "divergence": conv["divergence"],
        "suggested_position_pct": conv["suggested_position_pct"],
        "sector": ctx.get("sector") if ctx.get("sector") not in (None, "n/d") else None,
        "cap_bucket": ctx.get("cap_bucket"),
    }

    # Champs d'affichage de l'alerte
    display = {
        **record,
        "price": price, "target": target, "stop": stop,
        "upside": upside, "downside": downside, "max_position_pct": max_pos,
        "conviction_text": conv["conviction_text"],
        "divergence_text": conv["divergence_text"],
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

    # 1bis. Régime de marché : adapte seuil d'alerte, sélectivité et taille des positions
    import market_regime
    try:
        regime = market_regime.detect_regime()
    except Exception as e:  # noqa: BLE001
        logger.warning("Détection régime échouée (%s) — réglages haussier par défaut.", e)
        regime = market_regime._build("haussier", "régime indéterminé", {})
    eff_min_score = regime["min_final_score"]
    eff_max_finalists = min(max_finalists, regime["max_finalists"]) if max_finalists else regime["max_finalists"]
    summary["regime"] = regime["regime"]
    logger.info("Régime %s — seuil %s/100, finalistes max %s, taille x%s (%s)",
                regime["label"], eff_min_score, eff_max_finalists, regime["size_mult"], regime["details"])

    # Clustering sectoriel : on part des signaux déjà émis aujourd'hui (scans
    # précédents) et on incrémente au fil de ce scan pour annoter les alertes.
    import sector_cluster
    sector_today = sector_cluster.todays_counts()

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
        if not snap.get("price"):
            # sans prix d'entrée, le signal serait inexploitable (P&L incalculable)
            logger.warning("%s écarté : prix indisponible.", tk)
            continue
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
        if eff_max_finalists and finalists > eff_max_finalists:
            logger.info("Plafond finalistes atteint (%s, régime %s)", eff_max_finalists, regime["regime"])
            break

        logger.info("Finaliste %s : %s (%.1f/50, RS +%.1f%%) -> débat", tk, best["pattern"],
                    best["setup_score"], (rs.get("outperformance") or 0) * 100)
        ctx = context_builder.build_context(tk, snap, best, market)
        # enrichir le contexte IA avec RS et résultats
        ctx["sector_trend"] = (f"force relative {(rs.get('outperformance') or 0)*100:+.1f}% vs marché")
        ctx["next_earnings"] = f"dans {days_e} jours" if days_e is not None else "n/d"
        # Méta-apprentissage : poids adaptés au segment (secteur / taille de capi)
        seg_weights, seg_src = ai_weights, "global"
        try:
            from memory import weights as weights_mod
            seg_weights, seg_src = weights_mod.get_weights_for(
                sector=ctx.get("sector"), cap_bucket=ctx.get("cap_bucket"),
                global_weights=ai_weights)
            if seg_src != "global":
                logger.info("%s : poids par segment (%s)", tk, seg_src)
        except Exception as e:  # noqa: BLE001
            logger.debug("get_weights_for KO : %s", e)
        debate_out = debate.run_debate(ctx, weights=seg_weights, min_final_score=eff_min_score)

        res = debate_out["result"]
        detail = {"ticker": tk, "pattern": best["pattern"],
                  "setup_score": best["setup_score"], "final_score": res["final_score"],
                  "buy_votes": res["buy_votes"], "alert": res["send_alert"]}
        summary["details"].append(detail)

        if res["send_alert"]:
            assembled = assemble_signal(tk, snap, best, debate_out, is_paper=paper, ctx=ctx,
                                        regime_mult=regime["size_mult"])
            # Gestionnaire de portefeuille : contrôle de l'exposition globale
            try:
                import portfolio
                pcheck = portfolio.evaluate(assembled["record"].get("sector"),
                                            assembled["record"].get("suggested_position_pct") or 0)
                if not pcheck["allowed"]:
                    logger.info("%s : alerte bloquée par le portefeuille (%s)", tk, pcheck["reason"])
                    detail["alert"] = False
                    detail["blocked"] = pcheck["reason"]
                    continue
                if pcheck["pos_pct"] != (assembled["record"].get("suggested_position_pct") or 0):
                    assembled["record"]["suggested_position_pct"] = pcheck["pos_pct"]
                    assembled["display"]["suggested_position_pct"] = pcheck["pos_pct"]
                    assembled["display"]["portfolio_note"] = pcheck["reason"]
            except Exception as e:  # noqa: BLE001
                logger.warning("Contrôle portefeuille échoué : %s", e)
            assembled["display"]["regime_label"] = regime["label"]
            # Clustering sectoriel : compte ce secteur sur la journée (scans inclus)
            sec = assembled["record"].get("sector")
            if sec:
                sector_today[sec] = sector_today.get(sec, 0) + 1
                note = sector_cluster.cluster_note(sector_today[sec], sec)
                if note:
                    assembled["display"]["sector_note"] = note
                    logger.info("Cluster sectoriel : %s", note)
            persist_and_alert(assembled, debate_out, send=send_alerts)
            summary["alerts"] += 1

    summary["finalists"] = finalists
    summary["best_score"] = max((d["final_score"] for d in summary["details"]), default=0)
    logger.info("Scan terminé : %s candidats, %s finalistes, %s alertes",
                summary["candidates"], finalists, summary["alerts"])
    _record_activity(summary)

    # Récap auto si aucune alerte : visibilité même les jours calmes (mode actif seul)
    if (send_alerts and summary["alerts"] == 0 and not summary.get("suspended")
            and config.ALERT_RULES.get("recap_when_no_alert", True)):
        try:
            from alerts import daily_report, telegram_bot
            if daily_report.get_alert_mode() == "actif":
                telegram_bot.send_message(_scan_recap_message(summary))
        except Exception as e:  # noqa: BLE001
            logger.warning("Récap sans-alerte échoué : %s", e)
    return summary


def _scan_recap_message(summary: dict) -> str:
    """Récap court d'un scan sans alerte : actions étudiées + scores."""
    seuil = config.ALERT_RULES["min_final_score"]
    lines = [f"🔍 Scan {summary.get('label', '')} — rien au-dessus du seuil ({seuil}/100)",
             f"{summary.get('candidates', 0)} candidats · {summary.get('finalists', 0)} "
             f"étudiés par les IA · meilleur {summary.get('best_score', 0)}/100"]
    details = sorted(summary.get("details", []), key=lambda d: -(d.get("final_score") or 0))
    if details:
        lines.append("\n🧠 Actions étudiées :")
        for d in details[:10]:
            pat = f" ({d['pattern']})" if d.get("pattern") else ""
            lines.append(f"  • {d.get('ticker')}{pat} : {d.get('final_score')}/100")
    else:
        lines.append("Aucun setup assez propre pour être étudié ce scan.")
    return "\n".join(lines)


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
            "regime": summary.get("regime"),
            "suspended": summary.get("suspended"),
            # détail des actions passées au débat des IA (pour /diag)
            "details": [{"ticker": d.get("ticker"), "pattern": d.get("pattern"),
                         "final_score": d.get("final_score"), "alert": d.get("alert")}
                        for d in summary.get("details", [])],
        })
        # On conserve 14 jours d'historique (pour la simulation des seuils),
        # au lieu d'écraser chaque jour.
        log[today] = day
        cutoff = (dt.date.today() - dt.timedelta(days=14)).isoformat()
        log = {d: v for d, v in log.items() if d >= cutoff}
        state.set_state("activity", log)
    except Exception as e:  # noqa: BLE001
        logger.warning("Enregistrement activité échoué : %s", e)


def debate_out_weights():
    try:
        from memory import weights
        return weights.get_current_weights()
    except Exception:  # noqa: BLE001
        return dict(config.INITIAL_WEIGHTS)


# ─────────────────────────────────────────────────────────────
# SCREEN D'UNE LISTE DE TICKERS (sans IA) — momentum / RS / fondamentaux
# ─────────────────────────────────────────────────────────────

def run_screen(tickers: list[str], send: bool = True) -> str:
    """Analyse rapide (sans IA) d'une liste de tickers et envoie le classement."""
    import market_context
    import fundamentals as fund
    market = data_fetcher.fetch_ticker("^FCHI", period="1y", interval="1d")  # CAC40 (réf France)

    rows = []
    for tk in tickers:
        tk = tk.strip().upper()
        if not tk:
            continue
        try:
            df = data_fetcher.fetch_ticker(tk, period="1y", interval="1d")
            if df is None or df.empty or len(df) < 70:
                rows.append({"tk": tk, "ok": False})
                continue
            df = data_fetcher.add_indicators(df)
            snap = data_fetcher.latest_snapshot(df)
            price = snap.get("price")
            closes = df["close"].values
            mom3 = (closes[-1] / closes[-63] - 1) if len(closes) > 63 else None
            rs = market_context.relative_strength(df, market)
            fc = fund.fundamentals_context(tk, price=price)
            ma50 = snap.get("ma50")
            rows.append({
                "tk": tk, "ok": True, "price": price, "mom3": mom3,
                "rs": rs.get("outperformance"), "rsi": snap.get("rsi"),
                "above_ma50": (price >= ma50) if (price and ma50) else None,
                "fond": fc.get("score"), "cap": fc.get("cap_bucket"),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("screen %s KO : %s", tk, e)
            rows.append({"tk": tk, "ok": False})

    ok = [r for r in rows if r.get("ok")]
    ko = [r for r in rows if not r.get("ok")]
    ok.sort(key=lambda r: (r.get("mom3") if r.get("mom3") is not None else -9), reverse=True)

    def fond_lbl(s):
        if s is None:
            return "n/d"
        return "solide" if s >= 70 else "correct" if s >= 45 else "fragile"

    lines = [f"🔎 SCREEN — {len(tickers)} valeurs (sans IA)",
             "3M=perf 3 mois · RS=vs CAC40 · 🔥>MA50 · ⚠️RSI>75 (déjà tendu)", ""]
    for i, r in enumerate(ok, 1):
        mom = f"{r['mom3']*100:+.0f}%" if r.get("mom3") is not None else "n/d"
        rsv = f"{r['rs']*100:+.0f}%" if r.get("rs") is not None else "n/d"
        rsi = f"{r['rsi']:.0f}" if r.get("rsi") is not None else "?"
        trend = "🔥" if r.get("above_ma50") else "·"
        hot = " ⚠️" if (r.get("rsi") or 0) > 75 else ""
        lines.append(f"{i}. {r['tk']}  3M {mom} · RS {rsv} · RSI {rsi}{trend}{hot} · "
                     f"fond:{fond_lbl(r.get('fond'))} · {r.get('cap') or '?'}")
    if ko:
        lines.append("\n✖ Données indisponibles : " + ", ".join(r["tk"] for r in ko))
    lines.append("\nℹ️ Lecture rapide, pas une reco. 🔥+RS positif = vrai leader ; "
                 "⚠️RSI>75 = risque d'acheter trop tard.")
    msg = "\n".join(lines)

    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi screen échoué : %s", e)
    return msg


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

    # Normalisation : un déclencheur externe peut passer toute la commande en un
    # seul argument entre guillemets (ex. "screen SOI.PA XFAB.PA"). On re-découpe.
    if len(argv) == 1 and " " in argv[0]:
        argv = argv[0].split()
        cmd = argv[0]

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
    elif cmd == "buzz":
        # python main.py buzz EU|US|recap
        import buzz
        sub = argv[1] if len(argv) > 1 else "EU"
        if sub == "recap":
            buzz.send_recap()
        else:
            print(buzz.run_digest(sub.upper()))
    elif cmd == "dashboard":
        # python main.py dashboard [chemin] [--send]
        import dashboard
        path = next((a for a in argv[1:] if not a.startswith("-")), "dashboard.html")
        sigs = dashboard.fetch_signals()
        print(dashboard.build_text_summary(sigs))
        dashboard.write_html(path, sigs)
        print(f"\nDashboard HTML écrit : {path}")
        if "--send" in argv:
            from alerts import telegram_bot
            telegram_bot.send_document(path, caption="📊 Tableau de bord")
            print("Envoyé sur Telegram.")
    elif cmd == "regime":
        # python main.py regime — affiche le régime de marché actuel
        import market_regime
        r = market_regime.detect_regime()
        print(f"\n=== RÉGIME : {r['label']} ({r['regime']}) ===")
        print(r["details"])
        print(f"Seuil alerte : {r['min_final_score']}/100 | finalistes max : "
              f"{r['max_finalists']} | taille x{r['size_mult']}")
        print("Mesures :", r["metrics"])
    elif cmd == "news":
        # python main.py news TICKER  — affiche la mémoire actualités d'un ticker
        import news
        tk = argv[1].upper() if len(argv) > 1 else "AAPL"
        out = news.news_context(tk)
        print(f"\n=== ACTUALITÉS {tk} ===")
        print(out["sentiment_text"])
        print(out["text"])
    elif cmd == "fundamentals":
        # python main.py fundamentals TICKER — santé financière + consensus
        import fundamentals
        tk = argv[1].upper() if len(argv) > 1 else "AAPL"
        out = fundamentals.fundamentals_context(tk)
        print(f"\n=== FONDAMENTAUX {tk} ===")
        print(out["score_text"])
        print(out["text"])
        print(out["analyst_view"] if "analyst_view" in out else out["analyst_text"])
        print(f"Secteur : {out['sector']} — capi {out['market_cap']}")
    elif cmd == "autotune":
        # python main.py autotune [annees] [--apply]
        import autotune
        yrs = next((int(a) for a in argv[1:] if a.isdigit()), None)
        apply = "--apply" in argv
        out = autotune.run_autotune(years=yrs, apply=apply, notify=apply)
        for k, v in out.items():
            print(f"{k}: {v}")
        if not apply:
            print("(simulation — ajoute --apply pour écrire le réglage)")
    elif cmd == "mvrv":
        # python main.py mvrv [--send]  — vérifie le MVRV Z-Score Bitcoin
        import btc_mvrv
        print(btc_mvrv.check(send="--send" in argv))
    elif cmd == "halving":
        # python main.py halving [--send]  — vérifie le calendrier 500j halving
        import halving
        print(halving.check(send="--send" in argv))
    elif cmd == "thresholds":
        # python main.py thresholds  — simule "et si le seuil avait été 65/60/55"
        import thresholds
        thresholds.run(send="--send" in argv)
    elif cmd == "simdetail":
        # python main.py simdetail  — détail trade par trade des simulations
        import thresholds
        thresholds.detail(send="--send" in argv)
    elif cmd == "backtest-report":
        # python main.py backtest-report [annees] [neutral|watchlist] [--send]
        import backtest_report
        yrs = next((int(a) for a in argv[1:] if a.isdigit()), 3)
        univ = "watchlist" if "watchlist" in argv else "neutral"
        backtest_report.run_report(yrs, universe=univ, send="--send" in argv)
    elif cmd == "budget":
        # python main.py budget  — simule "si j'avais investi 1500€ en suivant le bot"
        import budget_sim
        budget_sim.run(send="--send" in argv)
    elif cmd == "budget-detail":
        # python main.py budget-detail  — journal trade par trade + cumul (seuils 65/60)
        import budget_sim
        budget_sim.detail(send="--send" in argv)
    elif cmd == "bilan-complet":
        # python main.py bilan-complet  — bilan global consolidé du paper trading
        import bilan
        bilan.global_report(send="--send" in argv)
    elif cmd == "screen":
        # python main.py screen TICKER1 TICKER2 ...  (analyse sans IA + envoi Telegram)
        run_screen(argv[1:])
    elif cmd == "setup-telegram":
        # Déclare le menu de commandes du bot à Telegram (menu '/')
        from alerts import telegram_bot
        ok = telegram_bot.set_my_commands()
        print("Commandes Telegram déclarées." if ok else "Échec (vérifier le token).")
    elif cmd == "set-webhook":
        # python main.py set-webhook <URL_fonction> <SECRET>  (réponses instantanées)
        from alerts import telegram_bot
        if len(argv) < 3:
            print("Usage: python main.py set-webhook <URL> <SECRET>")
        else:
            ok = telegram_bot.set_webhook(argv[1], argv[2])
            print("Webhook activé." if ok else "Échec (vérifier URL/token).")
    elif cmd == "delete-webhook":
        from alerts import telegram_bot
        print("Webhook désactivé." if telegram_bot.delete_webhook() else "Échec.")
    elif cmd == "monitor":
        # python main.py monitor [--send]  — bulletin de suivi du portefeuille
        import monitor
        monitor.run_bulletin(send="--send" in argv)
    elif cmd == "tweet":
        # python main.py tweet <texte du tweet>  — analyse par les 3 IA
        import tweet
        text = " ".join(a for a in argv[1:] if a != "--send")
        tweet.analyze_tweet(text, send="--send" in argv)
    elif cmd == "tweet-image":
        # python main.py tweet-image <url_image> [--send]  — analyse une capture de tweet
        import tweet
        url = next((a for a in argv[1:] if a != "--send"), "")
        tweet.analyze_image(url, send="--send" in argv)
    elif cmd == "follow":
        # python main.py follow <ticker|nom> [spec|conviction]
        import monitor
        arg = next((a for a in argv[1:] if a not in ("spec", "conviction", "--send")), "")
        typ = "conviction" if "conviction" in argv else "spec"
        print(monitor.follow(arg, typ)["msg"])
    elif cmd == "unfollow":
        import monitor
        print(monitor.unfollow(" ".join(argv[1:]))["msg"])
    elif cmd in ("liste", "watchlist"):
        import monitor
        print(monitor.format_watchlist())
    elif cmd in ("portefeuille", "portfolio", "pf"):
        # python main.py portefeuille [--send]  — valeur temps réel CTO + PEA
        import holdings
        holdings.run(send="--send" in argv)
    elif cmd in ("transaction", "tx"):
        # python main.py transaction <url_capture> [--send]  — lit une capture TR
        import transactions
        url = next((a for a in argv[1:] if a != "--send"), "")
        print(transactions.handle_screenshot(url, send="--send" in argv))
    elif cmd in ("transactions", "journal"):
        import transactions
        print(transactions.format_journal())
    elif cmd in ("annuler", "undo"):
        import transactions
        print(transactions.undo_last())
    elif cmd == "process-queue":
        import monitor
        print(monitor.process_commands(send="--send" in argv))
    elif cmd == "selftest":
        run_selftest()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
