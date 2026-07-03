"""
analyse.py — Analyse approfondie d'UNE valeur à la demande (/analyse <valeur>).

Rémy tape /analyse sanofi (ou SAN.PA, ou nvidia…) et reçoit un verdict TRANCHÉ,
toujours l'un des trois :
  🟢 ACHÈTE MAINTENANT — avec plan complet (entrée, stop, objectif)
  🟡 ATTENDS <prix>    — niveau d'achat précis + alerte auto quand on y est
  🔴 N'ACHÈTE PAS      — avec le niveau de reprise qui invaliderait cet avis

Croisement : technique daily (tendance, RSI, MACD, supports) + dynamique court
terme (4h) + fondamentaux + actualités + débat des 3 IA (DeepSeek/Grok/Claude).
Quand le verdict est "ATTENDS", une alerte de prix dynamique est posée : Rémy
est prévenu automatiquement quand le niveau est touché.
"""

import logging

import config
import data_fetcher

logger = logging.getLogger("analyse")


# ─────────────────────────────────────────────────────────────
# RÉSOLUTION DU TICKER (nom courant -> ticker Yahoo)
# ─────────────────────────────────────────────────────────────

EXTRA_ALIASES = {
    "google": "GOOGL", "alphabet": "GOOGL", "apple": "AAPL", "nvidia": "NVDA",
    "amazon": "AMZN", "meta": "META", "netflix": "NFLX", "amd": "AMD",
    "schneider": "SU.PA", "total": "TTE.PA", "totalenergies": "TTE.PA",
    "stm": "STMPA.PA", "stmicro": "STMPA.PA", "stmicroelectronics": "STMPA.PA",
    "vinci": "DG.PA", "loreal": "OR.PA", "l'oreal": "OR.PA", "bnp": "BNP.PA",
    "axa": "CS.PA", "safran": "SAF.PA", "airbus": "AIR.PA", "thales": "HO.PA",
    "capgemini": "CAP.PA", "dassault": "DSY.PA", "kering": "KER.PA",
}


def _aliases() -> dict:
    """Nom courant (minuscule) -> ticker. Watchlist de Rémy + noms fréquents."""
    al = {}
    for s in config.WATCHLIST_MONITOR:
        name = s["name"].lower()
        al[name] = s["ticker"]
        al.setdefault(name.split()[0].strip("()"), s["ticker"])
    for k, v in EXTRA_ALIASES.items():
        al.setdefault(k, v)
    return al


def resolve(query: str) -> tuple[str | None, object]:
    """Résout la saisie de Rémy en ticker Yahoo + données daily 1 an.

    Essais dans l'ordre : alias connu, ticker tel quel, ticker + '.PA' (Euronext).
    Retourne (ticker, df) ou (None, None) si introuvable.
    """
    q = (query or "").strip().lstrip("$").strip()
    if not q:
        return None, None
    tk = _aliases().get(q.lower(), q.upper())
    df = data_fetcher.fetch_ticker(tk, period="1y", interval="1d")
    if df is not None and not df.empty:
        return tk, df
    if "." not in tk:
        tk_pa = tk + ".PA"
        df = data_fetcher.fetch_ticker(tk_pa, period="1y", interval="1d")
        if df is not None and not df.empty:
            return tk_pa, df
    return None, None


# ─────────────────────────────────────────────────────────────
# MOTEUR DE VERDICT (pur, testable)
# ─────────────────────────────────────────────────────────────

def _verdict(price: float, rsi: float | None, ma20: float | None, ma50: float | None,
             ma200: float | None, ma50_rising: bool, macd_bull: bool,
             st_bull: bool) -> tuple[str, float | None, str]:
    """Retourne (code, niveau, raison).

    Codes : BUY_NOW (achète au prix actuel), WAIT_PULLBACK (attends un repli
    vers `niveau`), WAIT_RECLAIM (achète seulement si le prix REPASSE `niveau`),
    NO_BUY (n'achète pas ; `niveau` = reprise à surveiller).
    """
    uptrend = (ma200 is not None and price > ma200) or ma50_rising
    dist50 = (price - ma50) / ma50 if ma50 else None
    pullback_lvl = ma20 if (ma20 is not None and ma20 < price) else ma50

    if uptrend:
        if rsi is not None and rsi < 35:
            return "BUY_NOW", price, (f"survendu (RSI {rsi:.0f}) en tendance haussière — "
                                      "ces creux-là se paient plus cher plus tard")
        if dist50 is not None and abs(dist50) <= 0.03 and (rsi is None or rsi <= 60):
            return "BUY_NOW", price, ("le prix est revenu sur la MA50 en tendance "
                                      "haussière — c'est exactement le repli qu'on attend")
        if rsi is not None and rsi >= 70:
            return "WAIT_PULLBACK", pullback_lvl, (f"suracheté (RSI {rsi:.0f}) — "
                                                   "acheter ici, c'est payer le haut")
        if dist50 is not None and dist50 > 0.08:
            return "WAIT_PULLBACK", pullback_lvl, (f"trop étiré (+{dist50*100:.0f}% "
                                                   "au-dessus de la MA50) — le repli viendra")
        if macd_bull or st_bull:
            return "BUY_NOW", price, ("tendance haussière et momentum sain — "
                                      "pas de raison d'attendre")
        return "WAIT_PULLBACK", ma50, ("tendance haussière mais momentum mou — "
                                       "tu auras un meilleur prix sur la MA50")

    # Tendance baissière / cassée
    if st_bull and ma50 is not None:
        return "WAIT_RECLAIM", ma50, ("un rebond court terme est en cours mais la tendance "
                                      "de fond n'est pas réparée — n'achète que si ça repasse "
                                      "la MA50, sinon c'est un piège")
    return "NO_BUY", ma50, ("tendance baissière — acheter maintenant, c'est rattraper "
                            "un couteau qui tombe")


VERDICT_HEAD = {
    "BUY_NOW":       ("🟢", "ACHÈTE MAINTENANT"),
    "WAIT_PULLBACK": ("🟡", "ATTENDS"),
    "WAIT_RECLAIM":  ("🟡", "ATTENDS"),
    "NO_BUY":        ("🔴", "N'ACHÈTE PAS"),
}


# ─────────────────────────────────────────────────────────────
# MESSAGE
# ─────────────────────────────────────────────────────────────

def _plan(entry: float, atr: float) -> dict:
    import pepites
    return pepites.plan(entry, atr)


def format_analysis(tk: str, name: str, cur: str, price: float, code: str,
                    level: float | None, reason: str, tech: dict,
                    extra_lines: list[str]) -> str:
    emoji, head = VERDICT_HEAD[code]
    lines = [f"🔎 ANALYSE — {name} ({tk}) — {price:.2f}{cur}", ""]

    if code == "BUY_NOW":
        p = _plan(price, tech["atr"])
        lines.append(f"{emoji} VERDICT : {head}")
        lines.append(f"Pourquoi : {reason}.")
        lines.append(f"Plan : entrée ~{price:.2f}{cur} · stop {p['stop']:.2f}{cur} "
                     f"({-p['stop_pct']*100:.0f}%) · objectif {p['target']:.2f}{cur} "
                     f"(+{p['target_pct']*100:.0f}%)")
    elif code == "WAIT_PULLBACK" and level:
        p = _plan(level, tech["atr"])
        lines.append(f"{emoji} VERDICT : {head} — achète vers {level:.2f}{cur} "
                     f"({(level/price-1)*100:+.1f}% sous le cours)")
        lines.append(f"Pourquoi : {reason}.")
        lines.append(f"Plan au repli : entrée {level:.2f}{cur} · stop {p['stop']:.2f}{cur} · "
                     f"objectif {p['target']:.2f}{cur}")
        lines.append("⏰ Je te préviens automatiquement quand on y est.")
    elif code == "WAIT_RECLAIM" and level:
        lines.append(f"{emoji} VERDICT : {head} — achète SEULEMENT si ça repasse "
                     f"{level:.2f}{cur} (MA50)")
        lines.append(f"Pourquoi : {reason}.")
        lines.append("⏰ Je te préviens automatiquement si ça franchit ce niveau.")
    else:  # NO_BUY
        lines.append(f"{emoji} VERDICT : {head}")
        lines.append(f"Pourquoi : {reason}.")
        if level:
            lines.append(f"Niveau qui changerait mon avis : reprise au-dessus de "
                         f"{level:.2f}{cur} (MA50). ⏰ Je te préviens si on y arrive.")

    lines.append("")
    lines.append(f"📊 Technique : {tech['trend_txt']} · RSI {tech['rsi_txt']} · "
                 f"MACD {tech['macd_txt']} · 4h : {tech['st_txt']}")
    lines.append(f"   MA20 {tech['ma20_txt']} · MA50 {tech['ma50_txt']} · "
                 f"support 20j {tech['support_txt']}")
    lines += extra_lines
    lines.append("")
    lines.append("(Analyse à la demande — la dernière décision reste la tienne.)")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# ANALYSE COMPLÈTE
# ─────────────────────────────────────────────────────────────

def run(query: str, send: bool = True) -> dict:
    """Analyse approfondie + verdict tranché. Retourne {"message", "verdict"}."""
    tk, df = resolve(query)
    if tk is None:
        msg = (f"❓ Je ne trouve pas « {query.strip()} ». Donne-moi le ticker Yahoo "
               "(ex. SAN.PA, GOOGL) ou un nom que je connais (ex. sanofi, hermès).")
        if send:
            _send(msg)
        return {"message": msg, "verdict": None}

    d = data_fetcher.add_indicators(df)
    close = d["close"]
    price = float(close.iloc[-1])
    rsi = d["rsi"].iloc[-1]
    rsi = None if rsi != rsi else float(rsi)
    ma20 = float(d["ma20"].iloc[-1]) if d["ma20"].iloc[-1] == d["ma20"].iloc[-1] else None
    ma50_series = close.rolling(50).mean()
    ma50 = float(ma50_series.iloc[-1]) if len(close) >= 50 else None
    ma50_prev = float(ma50_series.iloc[-11]) if len(ma50_series) > 11 else (ma50 or 0)
    ma50_rising = (ma50 or 0) > ma50_prev
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    macd_v, macd_s = d["macd"].iloc[-1], d["macd_signal"].iloc[-1]
    macd_bull = bool(macd_v == macd_v and macd_s == macd_s and macd_v > macd_s)
    atr = float(d["atr"].iloc[-1]) if "atr" in d and d["atr"].iloc[-1] == d["atr"].iloc[-1] \
        else price * 0.03
    support = float(df["low"].rolling(20).min().iloc[-1])

    import monitor
    st_bull = bool(monitor._short_term_bullish(tk, df))

    code, level, reason = _verdict(price, rsi, ma20, ma50, ma200, ma50_rising,
                                   macd_bull, st_bull)

    # Infos valeur (nom, devise) depuis la watchlist de Rémy si connue
    known = next((s for s in config.WATCHLIST_MONITOR if s["ticker"] == tk), None)
    name = known["name"] if known else tk
    cur = known["cur"] if known else ("€" if tk.endswith(".PA") else "$")

    uptrend = (ma200 is not None and price > ma200) or ma50_rising
    tech = {
        "atr": atr,
        "trend_txt": "tendance haussière" if uptrend else "tendance baissière/cassée",
        "rsi_txt": f"{rsi:.0f}" if rsi is not None else "n/d",
        "macd_txt": "haussier" if macd_bull else "baissier",
        "st_txt": "dynamique qui repart" if st_bull else "pas de rebond confirmé",
        "ma20_txt": f"{ma20:.2f}{cur}" if ma20 else "n/d",
        "ma50_txt": f"{ma50:.2f}{cur}" if ma50 else "n/d",
        "support_txt": f"{support:.2f}{cur}",
    }

    # Fondamentaux + actualités + avis des 3 IA (facultatifs : jamais bloquants)
    extra = []
    fund = None
    try:
        import fundamentals
        fund = fundamentals.fundamentals_context(tk, price)
        extra.append(f"🏢 {fund['score_text']} · {fund['market_cap']} · {fund['sector']}")
        extra.append(f"   {fund['analyst_text']}")
    except Exception as e:  # noqa: BLE001
        logger.warning("fondamentaux %s KO : %s", tk, e)
    try:
        import news
        nw = news.news_context(tk, company_name=name, k=3)
        extra.append(f"📰 {nw['sentiment_text']}")
    except Exception as e:  # noqa: BLE001
        logger.warning("news %s KO : %s", tk, e)

    # Débat des 3 IA — peut faire basculer un ACHÈTE en ATTENDS si elles sont contre
    try:
        from agents import debate, context_builder
        snap = data_fetcher.latest_snapshot(df)
        pattern = {"pattern": "analyse à la demande", "setup_score": 0}
        market = monitor._market_status()
        ctx = context_builder.build_context(tk, snap, pattern, market, company_name=name)
        out = debate.run_debate(ctx)
        score = out["result"]["final_score"]
        votes = out["result"]["buy_votes"]
        if score >= 65:
            ia_txt = f"✅ acheteuses ({score:.0f}/100, {votes}/3 ACHETER)"
        elif score < 40:
            ia_txt = f"❌ n'y croient pas ({score:.0f}/100, {votes}/3 ACHETER)"
        else:
            ia_txt = f"🤔 partagées ({score:.0f}/100, {votes}/3 ACHETER)"
        extra.append(f"🤖 IA : {ia_txt}")
        if code == "BUY_NOW" and score < 40:
            code, level = "WAIT_PULLBACK", (ma50 or price * 0.95)
            reason = ("techniquement achetable MAIS les 3 IA n'y croient pas "
                      f"({score:.0f}/100) — j'exige un meilleur prix pour compenser le risque")
    except Exception as e:  # noqa: BLE001
        logger.warning("débat IA %s KO : %s", tk, e)

    msg = format_analysis(tk, name, cur, price, code, level, reason, tech, extra)

    # Alerte de prix automatique sur le niveau donné (repli ou reprise)
    try:
        if code in ("WAIT_PULLBACK", "WAIT_RECLAIM", "NO_BUY") and level:
            from alerts import price_alerts
            direction = "below" if code == "WAIT_PULLBACK" else "above"
            what = ("touche le prix d'achat visé" if direction == "below"
                    else "franchit le niveau de reprise")
            price_alerts.add_dynamic(
                name=name, ticker=tk, level=round(level, 2), direction=direction, cur=cur,
                msg=f"{what} ({level:.2f}{cur}) — re-lance /analyse {tk} pour confirmer l'achat")
    except Exception as e:  # noqa: BLE001
        logger.warning("alerte dynamique %s KO : %s", tk, e)

    if send:
        _send(msg)
    return {"message": msg, "verdict": code}


def _send(msg: str) -> None:
    try:
        from alerts import telegram_bot
        telegram_bot.send_message(msg)
    except Exception as e:  # noqa: BLE001
        logger.warning("Envoi analyse échoué : %s", e)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    q = " ".join(sys.argv[1:]) or "sanofi"
    print(run(q, send=False)["message"])
