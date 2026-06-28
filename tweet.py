"""
tweet.py — Analyse de tweets d'investisseurs (X) par les 3 IA.

Rémy colle le texte d'un tweet qui recommande des actions. Le bot :
  1. extrait les tickers cités ($NVDA, $AMD…) ;
  2. pour chacun, fait débattre DeepSeek / Grok / Claude (graphique + news +
     fondamentaux + sentiment) ;
  3. décide s'il faut SUIVRE l'action ou l'IGNORER, et te le dit.

Réutilise le débat existant. Usage : python main.py tweet "<texte du tweet>"
"""

import re
import logging

import data_fetcher

logger = logging.getLogger("tweet")


def extract_tickers(text: str) -> list[str]:
    """Tickers cités au format $XXX, dédupliqués en conservant l'ordre."""
    out = []
    for t in re.findall(r"\$([A-Za-z][A-Za-z.\-]{0,6})", text or ""):
        u = t.upper().rstrip(".-")
        if u and u not in out:
            out.append(u)
    return out


def analyze_ticker(tk: str) -> dict:
    """Fait débattre les 3 IA sur un ticker et décide suivre / ignorer."""
    try:
        df = data_fetcher.fetch_ticker(tk, period="1y", interval="1d")
        if df is None or df.empty or len(df) < 60:
            return {"ticker": tk, "ok": False, "reason": "données indisponibles (ticker inconnu chez Yahoo ?)"}
        df = data_fetcher.add_indicators(df)
        snap = data_fetcher.latest_snapshot(df)
        import market_filter
        from agents import debate, context_builder
        market = market_filter.get_market_status()
        ctx = context_builder.build_context(tk, snap, {"pattern": "signalée sur X", "setup_score": 0}, market)
        out = debate.run_debate(ctx)
        res, votes = out["result"], out["final_votes"]
        follow = res["final_score"] >= 65 and res["buy_votes"] >= 2
        return {"ticker": tk, "ok": True, "price": snap.get("price"),
                "score": res["final_score"], "buys": res["buy_votes"],
                "follow": follow, "votes": votes}
    except Exception as e:  # noqa: BLE001
        logger.warning("analyze_ticker %s KO : %s", tk, e)
        return {"ticker": tk, "ok": False, "reason": f"erreur : {str(e)[:60]}"}


def analyze_tweet(text: str, send: bool = True, max_tickers: int = 6) -> str:
    tickers = extract_tickers(text)
    if not tickers:
        msg = ("📨 Analyse du tweet : aucun ticker détecté.\n"
               "Astuce : les tickers doivent être au format $NVDA, $AMD…")
        print(msg)
        if send:
            _send(msg)
        return msg

    results = [analyze_ticker(tk) for tk in tickers[:max_tickers]]
    lines = ["📨 ANALYSE DU TWEET", f"Actions citées : {', '.join(tickers)}", ""]
    for r in results:
        if not r.get("ok"):
            lines.append(f"❓ {r['ticker']} : {r['reason']}")
            continue
        decision = "✅ À SUIVRE" if r["follow"] else "🚫 à ignorer pour l'instant"
        per = " · ".join(
            f"{a.capitalize()} {v.get('verdict', '?')[:4].lower()} {v.get('score', '?')}/10"
            for a, v in r["votes"].items())
        price = f" ({r['price']:.2f})" if r.get("price") else ""
        lines.append(f"{decision} — {r['ticker']}{price}\n"
                     f"   Débat IA : {r['score']:.0f}/100, {r['buys']}/3 ACHETER\n"
                     f"   {per}")
    lines.append("\n(Les IA ont analysé graphique, news, fondamentaux et sentiment. "
                 "Avis indicatif — tu gardes la décision.)")
    msg = "\n".join(lines)
    print(msg)
    if send:
        _send(msg)
    return msg


def _send(msg: str) -> None:
    try:
        from alerts import telegram_bot
        telegram_bot.send_message(msg)
    except Exception as e:  # noqa: BLE001
        logger.warning("Envoi analyse tweet échoué : %s", e)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    analyze_tweet(" ".join(sys.argv[1:]), send=False)
