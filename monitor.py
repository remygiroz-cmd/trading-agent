"""
monitor.py — Suivi du portefeuille de Rémy (signaux achat / vente).

Le bot ne CHERCHE plus des valeurs sur le marché : il SURVEILLE la liste de Rémy
(config.WATCHLIST_MONITOR) et lui dit quand acheter/renforcer et quand vendre.

Deux profils par valeur :
  - "conviction" (long terme) : signaux pour RENFORCER sur repli (acheter le creux),
    et seulement une suggestion d'ALLÉGER si c'est TRÈS suracheté.
  - "spec" (spéculatif) : signaux d'ENTRÉE (survente/rebond) et de SORTIE actifs
    (objectif de gain atteint, suracheté, ou cassure de tendance).

Anti-spam : une alerte ponctuelle n'est envoyée qu'au MOMENT où une valeur ENTRE
dans une zone (achat/vente) — pas tous les jours. Le bulletin du matin, lui,
récapitule TOUT l'état du portefeuille.

Signaux basés sur des règles techniques claires (RSI, moyennes mobiles, distance
à la MA50, P&L depuis le prix d'achat). Pas d'appel IA : fiable et gratuit.
"""

import logging

import config
import data_fetcher

logger = logging.getLogger("monitor")

STATE_KEY = "monitor_state"

# Codes de signal -> (emoji, libellé court, actionnable ?)
SIGNALS = {
    "BUY_STRONG": ("🟢🟢", "ACHAT FORT", True),
    "BUY":        ("🟢", "ACHAT / RENFORCER", True),
    "SELL":       ("🔴", "VENTE", True),
    "TRIM":       ("🟠", "ALLÉGER", True),
    "HOLD":       ("⚪", "CONSERVER", False),
}


# ─────────────────────────────────────────────────────────────
# MOTEUR DE SIGNAL (pur, testable)
# ─────────────────────────────────────────────────────────────

def _signal(typ: str, price: float, entry: float | None, rsi: float | None,
            ma20: float | None, ma50: float | None, ma200: float | None,
            ma50_rising: bool) -> tuple[str, str]:
    """Retourne (code_signal, raison). Logique différente conviction vs spec."""
    c = config.MONITOR
    pnl = ((price - entry) / entry) if entry else None
    dist50 = ((price - ma50) / ma50) if ma50 else None
    uptrend = (ma200 is not None and price > ma200) or ma50_rising
    near50 = (dist50 is not None and abs(dist50) <= c["near_ma_pct"])

    if typ == "conviction":
        # SORTIES — vendre haut pour tenter de racheter plus bas (le bot signalera le rachat)
        if rsi is not None and rsi >= c["rsi_overbought"]:
            return "SELL", f"suracheté (RSI {rsi:.0f}) — vendre pour tenter de racheter plus bas (je te signalerai le rachat)"
        if dist50 is not None and dist50 >= c["conviction_trim_above_ma"]:
            return "SELL", f"très étiré (+{dist50*100:.0f}% au-dessus de la MA50) — alléger pour racheter plus bas"
        # ENTRÉES / renforcement sur repli en tendance haussière
        if rsi is not None and rsi < 30 and uptrend:
            return "BUY_STRONG", f"RSI {rsi:.0f} (fortement survendu) en tendance haussière — bon moment pour (re)acheter / renforcer"
        if uptrend and near50 and (dist50 is not None and dist50 <= 0.01):
            return "BUY", "repli sur la MA50 en tendance haussière — bon point pour renforcer"
        if rsi is not None and rsi < c["rsi_oversold"] and uptrend:
            return "BUY", f"RSI {rsi:.0f} (survendu) en tendance haussière — occasion de renforcer"
        # Vraie cassure de tendance (sous MA50 ET MA200) -> vendre, rachat plus bas
        if (ma50 is not None and price < ma50 and not ma50_rising
                and ma200 is not None and price < ma200):
            return "SELL", "tendance cassée (sous MA50 et MA200) — vendre, je te signalerai quand racheter"
        return "HOLD", "rien à signaler — on garde"

    # typ == "spec" : entrer / sortir
    # 1) Sorties (priorité : protéger / réaliser)
    if pnl is not None and pnl >= c["spec_take_profit"]:
        return "SELL", f"objectif atteint ({pnl*100:+.0f}% depuis ton achat) — prendre les bénéfices"
    if rsi is not None and rsi >= c["rsi_overbought"]:
        return "SELL", f"suracheté (RSI {rsi:.0f}) — alléger / sortir"
    if ma50 is not None and price < ma50 and not ma50_rising:
        return "SELL", "cassure sous la MA50 en tendance baissière — la dynamique se retourne, envisager de sortir"
    # 2) Entrées
    if rsi is not None and rsi < c["rsi_oversold"]:
        return "BUY", f"survendu (RSI {rsi:.0f}) — rebond possible, point d'entrée"
    if (ma20 is not None and ma50 is not None and price > ma20 > ma50
            and rsi is not None and 50 <= rsi <= 68):
        return "BUY", "reprise au-dessus des moyennes mobiles — momentum qui repart"
    return "HOLD", "rien à signaler"


# ─────────────────────────────────────────────────────────────
# ANALYSE D'UNE VALEUR
# ─────────────────────────────────────────────────────────────

def analyze(stock: dict) -> dict:
    """Analyse une valeur : récupère les cours, calcule le signal."""
    tk = stock["ticker"]
    out = {**stock, "ok": False}
    try:
        df = data_fetcher.fetch_ticker(tk, period="1y", interval="1d")
        if df is None or df.empty or len(df) < 60:
            out["reason"] = "données indisponibles"
            return out
        df = data_fetcher.add_indicators(df)
        close = df["close"]
        price = float(close.iloc[-1])
        rsi = df["rsi"].iloc[-1]
        rsi = None if rsi != rsi else float(rsi)   # NaN -> None
        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma50_series = close.rolling(50).mean()
        ma50 = float(ma50_series.iloc[-1])
        ma50_prev = float(ma50_series.iloc[-11]) if len(ma50_series) > 11 else ma50
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
        ma50_rising = ma50 > ma50_prev
        entry = stock.get("entry")

        code, reason = _signal(stock["type"], price, entry, rsi, ma20, ma50, ma200, ma50_rising)
        out.update({
            "ok": True, "price": price, "rsi": rsi, "ma50": ma50, "ma200": ma200,
            "pnl": ((price - entry) / entry) if entry else None,
            "signal": code, "reason": reason,
            "snapshot": data_fetcher.latest_snapshot(df),
        })
    except Exception as e:  # noqa: BLE001
        out["reason"] = f"erreur : {str(e)[:60]}"
    return out


def analyze_all() -> list[dict]:
    return [analyze(s) for s in config.WATCHLIST_MONITOR]


# ─────────────────────────────────────────────────────────────
# AVIS DES 3 IA (DeepSeek / Grok / Claude) sur un signal
# Réutilise le débat existant : les IA évaluent l'intérêt d'être ACHETEUR
# maintenant (en croisant graphique, news, fondamentaux, sentiment). On
# interprète leur avis par rapport au signal technique (achat ou vente).
# ─────────────────────────────────────────────────────────────

def _interpret(signal_code: str, final_score: float, buy_votes: int) -> str:
    """Texte court : les IA confirment-elles le signal technique ?"""
    bullish = final_score >= 65
    bearish = final_score < 45
    is_buy = signal_code.startswith("BUY")
    if is_buy:
        if bullish:
            verdict = "✅ confirment l'achat"
        elif bearish:
            verdict = "⚠️ prudentes — le creux est peut-être piégé"
        else:
            verdict = "🤔 avis partagé"
    else:  # signal de vente
        if bearish:
            verdict = "✅ confirment (peu d'intérêt à l'achat)"
        elif bullish:
            verdict = "⚠️ y voient une occasion d'achat malgré le signal — réévalue"
        else:
            verdict = "🤔 avis partagé"
    return f"{verdict} ({final_score:.0f}/100, {buy_votes}/3 ACHETER)"


def ai_opinion(stock: dict, analysis: dict, market: dict) -> str | None:
    """Lance le débat des 3 IA sur la valeur et retourne un avis court (ou None)."""
    try:
        from agents import debate, context_builder
        snap = analysis.get("snapshot") or {}
        pattern = {"pattern": SIGNALS.get(analysis.get("signal", "HOLD"))[1],
                   "setup_score": 0}
        ctx = context_builder.build_context(stock["ticker"], snap, pattern, market,
                                            company_name=stock.get("name", ""))
        out = debate.run_debate(ctx)
        res = out["result"]
        votes = out["final_votes"]
        per = " · ".join(
            f"{a.capitalize()} {v.get('verdict', '?')[:4].lower()} {v.get('score', '?')}/10"
            for a, v in votes.items())
        head = _interpret(analysis["signal"], res["final_score"], res["buy_votes"])
        return f"🤖 IA : {head}\n   {per}"
    except Exception as e:  # noqa: BLE001
        logger.warning("ai_opinion %s KO : %s", stock.get("ticker"), e)
        return None


def _market_status() -> dict:
    try:
        import market_filter
        return market_filter.get_market_status()
    except Exception:  # noqa: BLE001
        return {"spx_above_ma50": True, "vix": None, "bullish": True}


# ─────────────────────────────────────────────────────────────
# ALERTES PONCTUELLES (au moment où une valeur entre en zone)
# ─────────────────────────────────────────────────────────────

def _fmt_line(r: dict) -> str:
    emoji, label, _ = SIGNALS.get(r.get("signal", "HOLD"), SIGNALS["HOLD"])
    cur = r.get("cur", "")
    pnl = r.get("pnl")
    pnl_txt = f" · ta PV {pnl*100:+.0f}%" if pnl is not None else ""
    price = r.get("price")
    price_txt = f" ({price:.2f}{cur})" if price is not None else ""
    return f"{emoji} {r['name']}{price_txt} — {r['reason']}{pnl_txt}"


def _is_actionable(code: str) -> bool:
    return SIGNALS.get(code, SIGNALS["HOLD"])[2]


def _refresh_state(results: list[dict]) -> dict:
    """Met à jour l'état (dernier signal par valeur) et retourne l'état précédent."""
    from memory import state
    prev = state.get_state(STATE_KEY, default={}) or {}
    new = {}
    for r in results:
        new[r["ticker"]] = r["signal"] if r.get("ok") else prev.get(r["ticker"], "HOLD")
    state.set_state(STATE_KEY, new)
    return prev


def _enrich_ai(results: list[dict], market: dict, only: set | None = None) -> None:
    """Ajoute l'avis des 3 IA (r['ai']) sur les signaux actionnables (plafonné)."""
    if not config.MONITOR.get("ai_confirm"):
        return
    cap = config.MONITOR.get("ai_max_per_run", 6)
    n = 0
    for r in results:
        if not r.get("ok") or not _is_actionable(r["signal"]):
            continue
        if only is not None and r["ticker"] not in only:
            continue
        if n >= cap:
            break
        r["ai"] = ai_opinion(r, r, market)
        n += 1


def check_and_alert(send: bool = True) -> dict:
    """Détecte les valeurs qui ENTRENT dans une zone actionnable et alerte."""
    results = analyze_all()
    prev = _refresh_state(results)
    changed = {r["ticker"] for r in results if r.get("ok")
               and _is_actionable(r["signal"]) and prev.get(r["ticker"]) != r["signal"]}
    if changed:
        _enrich_ai(results, _market_status(), only=changed)

    alerts = []
    for r in results:
        if r.get("ticker") in changed:
            tag = "ACHAT" if r["signal"].startswith("BUY") else "VENTE/ALLÉGER"
            msg = f"⚡ SIGNAL {tag}\n{_fmt_line(r)}"
            if r.get("ai"):
                msg += "\n" + r["ai"]
            alerts.append(msg)

    if send and alerts:
        try:
            from alerts import telegram_bot
            for a in alerts:
                telegram_bot.send_message(a)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi alerte monitor échoué : %s", e)
    logger.info("Monitor : %s alerte(s) ponctuelle(s)", len(alerts))
    return {"alerts": len(alerts), "results": results}


# ─────────────────────────────────────────────────────────────
# BULLETIN DU MATIN (état complet du portefeuille)
# ─────────────────────────────────────────────────────────────

def format_bulletin(results: list[dict]) -> str:
    import datetime as dt
    today = dt.date.today().isoformat()
    buys = [r for r in results if r.get("signal", "").startswith("BUY")]
    sells = [r for r in results if r.get("signal") in ("SELL", "TRIM")]
    holds = [r for r in results if r.get("signal") == "HOLD"]
    errs = [r for r in results if not r.get("ok")]

    def block(rows):
        out = []
        for r in rows:
            out.append(f"  {_fmt_line(r)}")
            if r.get("ai"):
                out.append("  " + r["ai"].replace("\n", "\n  "))
        return out

    lines = [f"📋 SUIVI PORTEFEUILLE — {today}", ""]
    if buys:
        lines.append("🟢 À ACHETER / RENFORCER :")
        lines += block(buys)
        lines.append("")
    if sells:
        lines.append("🔴 À VENDRE / ALLÉGER :")
        lines += block(sells)
        lines.append("")
    if not buys and not sells:
        lines.append("Rien à faire aujourd'hui — aucune valeur en zone d'achat ou de vente.")
        lines.append("")
    if holds:
        held = ", ".join(
            f"{r['name']} ({r['pnl']*100:+.0f}%)" if r.get("pnl") is not None else r["name"]
            for r in holds)
        lines.append(f"⚪ À conserver : {held}")
    if errs:
        lines.append(f"\n⚠️ Données indisponibles : {', '.join(r['name'] for r in errs)}")
    lines.append("\n(Signaux indicatifs — tu gardes la décision finale.)")
    return "\n".join(lines)


def run_bulletin(send: bool = True) -> str:
    """Bulletin complet du matin (avec avis des 3 IA sur les signaux actionnables)."""
    res = analyze_all()
    _refresh_state(res)
    _enrich_ai(res, _market_status())
    msg = format_bulletin(res)
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi bulletin échoué : %s", e)
    return msg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_bulletin(send=False))
