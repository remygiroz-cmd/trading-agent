"""
agents/context_builder.py — Construit le contexte (brief) envoyé aux IA.

Rassemble : données techniques du ticker, figure détectée, contexte marché,
historique du ticker et règles apprises (depuis Supabase si disponible).
"""

import logging

logger = logging.getLogger("context")


def _fmt_history(rows: list[dict]) -> str:
    if not rows:
        return "Aucun signal passé sur ce ticker."
    lines = []
    for r in rows[:5]:
        res = r.get("result_7d")
        res_txt = f"{float(res)*100:+.1f}% à J+7" if res is not None else "en cours"
        lines.append(f"- {r.get('created_at','?')[:10]} {r.get('pattern_name')} "
                     f"(score {r.get('final_score')}/100) -> {res_txt}")
    return "\n".join(lines)


def _fmt_rules(rules: list[dict]) -> str:
    if not rules:
        return "Aucune règle apprise pour l'instant."
    return "\n".join(
        f"- {r['rule_description']} (fiabilité {float(r.get('reliability',0))*100:.0f}%)"
        for r in rules
    )


def _fmt_perf(perf: dict) -> str:
    return (f"Signaux analysés : {perf.get('total',0)}, "
            f"taux de réussite : {perf.get('win_rate',0)*100:.0f}%, "
            f"poids actuel : {perf.get('current_weight',0.33)*100:.0f}%")


def build_context(ticker: str, snapshot: dict, pattern: dict, market: dict,
                  company_name: str = "", sector: str = "", market_cap: str = "n/d",
                  use_memory: bool = True, use_news: bool = True) -> dict:
    """
    Construit le dict de contexte commun aux 3 prompts.

    snapshot : sortie de data_fetcher.latest_snapshot
    pattern  : résultat d'une figure (avec setup_score)
    market   : sortie de market_filter.get_market_status
    """
    ctx = {
        "ticker": ticker,
        "company_name": company_name or ticker,
        "sector": sector or "n/d",
        "market_cap": market_cap,
        "pattern_name": pattern.get("pattern", "n/d"),
        "setup_score": pattern.get("setup_score", "n/d"),
        "price": snapshot.get("price"),
        "pole_gain": round((pattern.get("pole_gain") or 0) * 100, 1) if pattern.get("pole_gain") else "n/d",
        "pole_candles": pattern.get("pole_candles", "n/d"),
        "depth": round(pattern.get("depth", 0) * 100, 1),
        "volume_ratio": pattern.get("breakout_volume_ratio", "n/d"),
        "rsi": round(snapshot["rsi"], 1) if snapshot.get("rsi") is not None else "n/d",
        "macd_signal": snapshot.get("macd_signal_state", "n/d"),
        "ma20": round(snapshot["ma20"], 2) if snapshot.get("ma20") is not None else "n/d",
        "ma50": round(snapshot["ma50"], 2) if snapshot.get("ma50") is not None else "n/d",
        # contexte marché
        "spx_status": "au-dessus MA50" if market.get("spx_above_ma50") else "sous MA50",
        "vix": round(market["vix"], 1) if market.get("vix") is not None else "n/d",
        "sector_trend": "n/d",
        "earnings_season": "n/d",
        "next_earnings": "n/d",
        # mémoire
        "ticker_history": "Aucun historique.",
        "agent_performance": "Pas encore d'historique de performance.",
        "learned_rules": "Aucune règle apprise pour l'instant.",
        # actualités (RAG)
        "news_context": "Actualités non consultées.",
        "news_sentiment": "Sentiment actualités : n/d.",
    }

    if use_memory:
        try:
            from memory import signals, performance
            ctx["ticker_history"] = _fmt_history(signals.get_ticker_history(ticker))
            ctx["learned_rules"] = _fmt_rules(performance.get_relevant_rules(ticker=ticker))
        except Exception as e:  # noqa: BLE001
            logger.warning("Mémoire indisponible pour le contexte : %s", e)

    if use_news:
        try:
            import news
            # mots-clés du setup pour orienter la récupération (RAG)
            terms = {str(pattern.get("pattern", "")).lower(), (sector or "").lower()}
            nc = news.news_context(ticker, company_name=company_name, terms=terms)
            ctx["news_context"] = nc["text"]
            ctx["news_sentiment"] = nc["sentiment_text"]
        except Exception as e:  # noqa: BLE001
            logger.warning("Actualités indisponibles pour le contexte : %s", e)

    return ctx
