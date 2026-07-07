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

import re
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
    "WAIT":       ("🟡", "ATTENDRE — surveiller", True),  # cassure daily MAIS rebond court terme
    "HOLD":       ("⚪", "CONSERVER", False),
}

# Ordre net en tête de chaque ligne — Rémy veut des avis tranchés, pas des nuances.
ORDERS = {
    "BUY_STRONG": "ACHÈTE MAINTENANT",
    "BUY":        "ACHÈTE",
    "SELL":       "VENDS",
    "TRIM":       "ALLÈGE",
    "WAIT":       "ATTENDS",
    "HOLD":       "GARDE",
}


# ─────────────────────────────────────────────────────────────
# MOTEUR DE SIGNAL (pur, testable)
# ─────────────────────────────────────────────────────────────

def _signal(typ: str, price: float, entry: float | None, rsi: float | None,
            ma20: float | None, ma50: float | None, ma200: float | None,
            ma50_rising: bool, st_bull: bool = False) -> tuple[str, str]:
    """Retourne (code_signal, raison). Logique différente conviction vs spec.

    st_bull : la dynamique COURT TERME (4h) repart à la hausse. Quand c'est le cas,
    une cassure de tendance en daily ne déclenche PAS une vente sèche : on renvoie
    "WAIT" (attendre la confirmation) pour ne pas vendre dans un rebond. Les sorties
    pour prise de bénéfices ou surchauffe (RSI) restent prioritaires, elles.
    """
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
            if st_bull:
                return "WAIT", "tendance cassée en daily MAIS rebond court terme (4h) en cours — on attend la confirmation avant de vendre"
            return "SELL", "tendance cassée (sous MA50 et MA200) — vendre, je te signalerai quand racheter"
        return "HOLD", "rien à signaler — on garde"

    # typ == "spec" : entrer / sortir
    # 1) Sorties (priorité : protéger / réaliser)
    if pnl is not None and pnl >= c["spec_take_profit"]:
        return "SELL", f"objectif atteint ({pnl*100:+.0f}% depuis ton achat) — prendre les bénéfices"
    if rsi is not None and rsi >= c["rsi_overbought"]:
        return "SELL", f"suracheté (RSI {rsi:.0f}) — alléger / sortir"
    if ma50 is not None and price < ma50 and not ma50_rising:
        if st_bull:
            return "WAIT", "cassure sous la MA50 en daily MAIS la dynamique court terme (4h) repart — on attend la confirmation avant de sortir"
        return "SELL", "cassure sous la MA50 en tendance baissière — la dynamique se retourne, envisager de sortir"
    # 2) Entrées
    if rsi is not None and rsi < c["rsi_oversold"]:
        return "BUY", f"survendu (RSI {rsi:.0f}) — rebond possible, point d'entrée"
    if (ma20 is not None and ma50 is not None and price > ma20 > ma50
            and rsi is not None and 50 <= rsi <= 68):
        return "BUY", "reprise au-dessus des moyennes mobiles — momentum qui repart"
    return "HOLD", "rien à signaler"


# ─────────────────────────────────────────────────────────────
# DYNAMIQUE COURT TERME (pour ne pas vendre dans un rebond)
# ─────────────────────────────────────────────────────────────

def _momentum_bullish(df) -> bool | None:
    """La dynamique récente repart-elle à la hausse ?

    On regarde 3 signes simples sur la dernière bougie du timeframe fourni :
      - RSI qui remonte (vs il y a 3 bougies)
      - histogramme MACD qui se retourne (devient moins négatif / positif)
      - prix qui repasse au-dessus de sa MA20
    Reversal haussier confirmé si au moins 2 des 3 sont vrais.
    Retourne None si pas assez de données (l'appelant gère le repli).
    """
    try:
        if df is None or df.empty or len(df) < 35:
            return None
        d = data_fetcher.add_indicators(df)
        rsi_s, hist_s, ma20_s, close_s = d["rsi"], d["macd_hist"], d["ma20"], d["close"]
        rsi_now, rsi_prev = rsi_s.iloc[-1], rsi_s.iloc[-3]
        h_now, h_prev = hist_s.iloc[-1], hist_s.iloc[-3]
        ma20_now, price = ma20_s.iloc[-1], close_s.iloc[-1]

        def ok(x):  # NaN -> False
            return x == x

        rsi_rising = ok(rsi_now) and ok(rsi_prev) and rsi_now > rsi_prev
        macd_turning = ok(h_now) and ok(h_prev) and h_now > h_prev
        reclaim = ok(ma20_now) and price > ma20_now
        return sum([bool(rsi_rising), bool(macd_turning), bool(reclaim)]) >= 2
    except Exception as e:  # noqa: BLE001
        logger.warning("_momentum_bullish KO : %s", e)
        return None


def _short_term_bullish(ticker: str, daily_df) -> bool:
    """True si la dynamique court terme repart. Priorité au 4h, repli sur le daily récent."""
    if not config.MONITOR.get("short_term_confirm"):
        return False
    interval = config.MONITOR.get("short_term_interval", "4h")
    period = config.MONITOR.get("short_term_period", "60d")
    try:
        df_st = data_fetcher.fetch_ticker(ticker, period=period, interval=interval)
        res = _momentum_bullish(df_st)
    except Exception as e:  # noqa: BLE001
        logger.warning("court terme %s KO : %s", ticker, e)
        res = None
    if res is None:  # 4h indisponible -> repli sur la dynamique récente du daily
        res = _momentum_bullish(daily_df)
    return bool(res)


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

        # Dynamique court terme : ne calculée que si la cassure de tendance est
        # plausible (prix sous la MA50) — inutile de taper l'API 4h sinon.
        st_bull = False
        if ma50 is not None and price < ma50 and not ma50_rising:
            st_bull = _short_term_bullish(tk, df)

        code, reason = _signal(stock["type"], price, entry, rsi, ma20, ma50, ma200,
                               ma50_rising, st_bull=st_bull)
        out.update({
            "ok": True, "price": price, "rsi": rsi, "ma50": ma50, "ma200": ma200,
            "pnl": ((price - entry) / entry) if entry else None,
            "signal": code, "reason": reason,
            "snapshot": data_fetcher.latest_snapshot(df),
        })
    except Exception as e:  # noqa: BLE001
        out["reason"] = f"erreur : {str(e)[:60]}"
    return out


# ─────────────────────────────────────────────────────────────
# WATCHLIST DYNAMIQUE (suivre / ne plus suivre via Telegram)
# Liste finale = valeurs de config + ajouts (agent_state) − retraits.
# ─────────────────────────────────────────────────────────────

def _cur_for(ticker: str) -> str:
    eu = (".PA", ".MI", ".DE", ".AS", ".BR", ".MC", ".LS", ".HE", ".ST")
    return "€" if any(ticker.upper().endswith(s) for s in eu) else "$"


def resolve_ticker(text: str) -> str | None:
    """Transforme un nom ou un ticker en ticker Yahoo. None si introuvable."""
    text = (text or "").strip().lstrip("$")
    if not text:
        return None
    # déjà un ticker (lettres/chiffres/point, sans espace) ?
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", text):
        return text.upper()
    try:
        import yfinance as yf
        res = yf.Search(text, max_results=5)
        for q in (getattr(res, "quotes", None) or []):
            if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF"):
                return q["symbol"].upper()
    except Exception as e:  # noqa: BLE001
        logger.debug("resolve_ticker(%s) KO : %s", text, e)
    return None


def get_watchlist() -> list[dict]:
    """Watchlist effective : config + ajouts − retraits (agent_state)."""
    try:
        from memory import state
        added = state.get_state("monitor_added", default=[]) or []
        removed = {t.upper() for t in (state.get_state("monitor_removed", default=[]) or [])}
    except Exception:  # noqa: BLE001
        added, removed = [], set()
    seen, out = set(), []
    for s in list(config.WATCHLIST_MONITOR) + list(added):
        tk = s["ticker"].upper()
        if tk in removed or tk in seen:
            continue
        seen.add(tk)
        out.append(s)
    return out


def format_watchlist() -> str:
    """Liste lisible des actions actuellement suivies (convictions + spéculatives)."""
    wl = get_watchlist()
    conv = [s for s in wl if s.get("type") == "conviction"]
    spec = [s for s in wl if s.get("type") != "conviction"]

    def line(s):
        entry = s.get("entry")
        prix = f" — acheté à {entry}{s.get('cur', '')}" if entry else ""
        return f"  • {s.get('name', s['ticker'])} ({s['ticker']}){prix}"

    out = [f"📋 Actions suivies : {len(wl)}"]
    if conv:
        out.append(f"\n💎 Conviction ({len(conv)}) :")
        out += [line(s) for s in conv]
    if spec:
        out.append(f"\n⚡ Spéculatif ({len(spec)}) :")
        out += [line(s) for s in spec]
    return "\n".join(out)


def follow(arg: str, typ: str = "spec") -> dict:
    """Ajoute une valeur au suivi (par ticker ou par nom)."""
    tk = resolve_ticker(arg)
    if not tk:
        return {"ok": False, "msg": f"❓ Action introuvable : « {arg} ». Donne le ticker (ex. $NVDA)."}
    from memory import state
    added = state.get_state("monitor_added", default=[]) or []
    removed = [t for t in (state.get_state("monitor_removed", default=[]) or []) if t.upper() != tk]
    state.set_state("monitor_removed", removed)
    if any(s["ticker"].upper() == tk for s in get_watchlist()):
        return {"ok": True, "msg": f"ℹ️ {tk} est déjà suivie."}
    name = arg.strip().lstrip("$") if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", arg.strip().lstrip("$")) else tk
    added.append({"name": name, "ticker": tk, "type": typ, "entry": None, "cur": _cur_for(tk)})
    state.set_state("monitor_added", added)
    return {"ok": True, "msg": f"✅ {name} ({tk}) ajoutée au suivi (profil {typ})."}


def unfollow(arg: str) -> dict:
    """Retire une valeur du suivi."""
    tk = resolve_ticker(arg)
    if not tk:
        return {"ok": False, "msg": f"❓ Action introuvable : « {arg} »."}
    from memory import state
    added = [s for s in (state.get_state("monitor_added", default=[]) or []) if s["ticker"].upper() != tk]
    state.set_state("monitor_added", added)
    if any(s["ticker"].upper() == tk for s in config.WATCHLIST_MONITOR):
        removed = state.get_state("monitor_removed", default=[]) or []
        if tk not in {t.upper() for t in removed}:
            removed.append(tk)
        state.set_state("monitor_removed", removed)
    return {"ok": True, "msg": f"🛑 {tk} retirée du suivi."}


def analyze_all() -> list[dict]:
    return [analyze(s) for s in get_watchlist()]


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
            verdict = "✅ confirment l'achat — vas-y"
        elif bearish:
            verdict = "❌ contre : le creux sent le piège — n'achète pas, attends"
        else:
            verdict = "🤔 partagées — je maintiens l'achat (le signal technique prime)"
    else:  # signal de vente
        if bearish:
            verdict = "✅ confirment la vente — vends"
        elif bullish:
            verdict = "⚠️ y voient un point d'achat — ne vends que la moitié"
        else:
            verdict = "🤔 partagées — je maintiens la vente (le signal technique prime)"
    return f"{verdict} ({final_score:.0f}/100, {buy_votes}/3 ACHETER)"


def ai_opinion(stock: dict, analysis: dict, market: dict) -> tuple[str | None, float | None]:
    """Lance le débat des 3 IA sur la valeur.

    Retourne (avis court, score final 0-100) — (None, None) si le débat échoue.
    Le score sert aussi de filtre anti-spam (config.MONITOR["min_ai_score"]).
    """
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
        return f"🤖 IA : {head}\n   {per}", float(res["final_score"])
    except Exception as e:  # noqa: BLE001
        logger.warning("ai_opinion %s KO : %s", stock.get("ticker"), e)
        return None, None


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
    code = r.get("signal", "HOLD")
    emoji, label, _ = SIGNALS.get(code, SIGNALS["HOLD"])
    order = ORDERS.get(code, "GARDE")
    cur = r.get("cur", "")
    pnl = r.get("pnl")
    pnl_txt = f" · ta PV {pnl*100:+.0f}%" if pnl is not None else ""
    price = r.get("price")
    price_txt = f" ({price:.2f}{cur})" if price is not None else ""
    return f"{emoji} {order} {r['name']}{price_txt} — {r['reason']}{pnl_txt}"


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
        r["ai"], r["ai_score"] = ai_opinion(r, r, market)
        n += 1


def _ai_gate(r: dict) -> bool:
    """Filtre anti-spam : une alerte ponctuelle ne part que si le score des 3 IA
    atteint config.MONITOR["min_ai_score"]. Pas de score (débat non lancé ou en
    échec) = pas de message : Rémy préfère le silence au bruit."""
    mn = config.MONITOR.get("min_ai_score", 0)
    if not mn:
        return True
    score = r.get("ai_score")
    return score is not None and score >= mn


def check_and_alert(send: bool = True) -> dict:
    """Détecte les valeurs qui ENTRENT dans une zone actionnable et alerte."""
    results = analyze_all()
    prev = _refresh_state(results)
    changed = {r["ticker"] for r in results if r.get("ok")
               and _is_actionable(r["signal"]) and prev.get(r["ticker"]) != r["signal"]}
    if changed:
        _enrich_ai(results, _market_status(), only=changed)

    alerts = []
    muted = 0
    for r in results:
        if r.get("ticker") in changed:
            if not _ai_gate(r):   # score IA < minimum -> pas de message (anti-spam)
                muted += 1
                continue
            if r["signal"].startswith("BUY"):
                tag = "ACHAT"
            elif r["signal"] == "WAIT":
                tag = "À SURVEILLER"
            else:
                tag = "VENTE/ALLÉGER"
            msg = f"⚡ SIGNAL {tag}\n{_fmt_line(r)}"
            if r.get("ai"):
                msg += "\n" + r["ai"]
            alerts.append(msg)
    if muted:
        logger.info("Monitor : %s alerte(s) silencée(s) (score IA < %s)",
                    muted, config.MONITOR.get("min_ai_score"))

    if send and alerts:
        try:
            from alerts import telegram_bot
            for a in alerts:
                telegram_bot.send_message(a)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi alerte monitor échoué : %s", e)

    # Alertes de franchissement de prix (niveaux clés type Sanofi 76 / Hermès 1690)
    price_alerts = 0
    try:
        from alerts import price_alerts as pa
        price_alerts = pa.check(send=send).get("alerts", 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("Alertes prix échouées : %s", e)

    logger.info("Monitor : %s alerte(s) ponctuelle(s), %s alerte(s) prix",
                len(alerts), price_alerts)
    return {"alerts": len(alerts), "price_alerts": price_alerts, "results": results}


# ─────────────────────────────────────────────────────────────
# BULLETIN DU MATIN (état complet du portefeuille)
# ─────────────────────────────────────────────────────────────

def format_bulletin(results: list[dict]) -> str:
    import datetime as dt
    today = dt.date.today().isoformat()
    # Même filtre anti-spam que les alertes ⚡ : une reco n'apparaît dans le
    # bulletin que si le score IA atteint le minimum. Les signaux trop faibles
    # sont rétrogradés en "à conserver" (la valeur reste visible, sans reco).
    def kept(r):
        return _is_actionable(r.get("signal", "HOLD")) and _ai_gate(r)
    buys = [r for r in results if r.get("signal", "").startswith("BUY") and kept(r)]
    sells = [r for r in results if r.get("signal") in ("SELL", "TRIM") and kept(r)]
    waits = [r for r in results if r.get("signal") == "WAIT" and kept(r)]
    demoted = [r for r in results if r.get("ok")
               and _is_actionable(r.get("signal", "HOLD")) and not _ai_gate(r)]
    holds = [r for r in results if r.get("signal") == "HOLD"] + demoted
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
    if waits:
        lines.append("🟡 SOUS SURVEILLANCE (cassure daily mais rebond court terme — on attend) :")
        lines += block(waits)
        lines.append("")
    if not buys and not sells and not waits:
        lines.append("Rien à faire aujourd'hui — aucune valeur en zone d'achat ou de vente.")
        lines.append("")
    if holds:
        held = ", ".join(
            f"{r['name']} ({r['pnl']*100:+.0f}%)" if r.get("pnl") is not None else r["name"]
            for r in holds)
        lines.append(f"⚪ À conserver : {held}")
    if demoted:
        lines.append(f"\n🔇 {len(demoted)} signal(aux) faible(s) ignoré(s) "
                     f"(score IA < {config.MONITOR.get('min_ai_score')}/100)")
    if errs:
        lines.append(f"\n⚠️ Données indisponibles : {', '.join(r['name'] for r in errs)}")
    lines.append("\n(Ordres nets — la dernière décision reste la tienne.)")
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


# ─────────────────────────────────────────────────────────────
# FILE DE COMMANDES (déposées par le bot Telegram : suivre / analyser un tweet)
# ─────────────────────────────────────────────────────────────

def process_commands(send: bool = True) -> dict:
    """Traite les demandes en attente déposées par Telegram (suivre/unfollow/tweet)."""
    from memory import state
    queue = state.get_state("monitor_queue", default=[]) or []
    if not queue:
        return {"processed": 0}
    state.set_state("monitor_queue", [])   # vidé d'abord (évite les doublons)

    replies = []
    for cmd in queue:
        action, arg = cmd.get("action"), cmd.get("arg", "")
        try:
            if action == "follow":
                replies.append(follow(arg, cmd.get("type", "spec"))["msg"])
            elif action == "unfollow":
                replies.append(unfollow(arg)["msg"])
            elif action == "list":
                replies.append(format_watchlist())
            elif action == "portfolio":
                import holdings
                replies.append(holdings.format_portfolio())
            elif action == "tweet":
                import tweet
                tweet.analyze_tweet(arg, send=True)
            elif action == "tweet_image":
                import tweet
                tweet.analyze_image(arg, send=True)
            elif action == "screenshot":
                import transactions
                transactions.handle_screenshot(arg, send=True)
            elif action == "journal":
                import transactions
                replies.append(transactions.format_journal())
            elif action == "undo_tx":
                import transactions
                replies.append(transactions.undo_last())
        except Exception as e:  # noqa: BLE001
            logger.warning("Commande %s KO : %s", action, e)
            replies.append(f"⚠️ Échec de la commande ({action}).")

    if send and replies:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message("\n".join(replies))
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi réponses commandes échoué : %s", e)
    logger.info("Monitor : %s commande(s) traitée(s)", len(queue))
    return {"processed": len(queue)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_bulletin(send=False))
