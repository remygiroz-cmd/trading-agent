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
        })
    except Exception as e:  # noqa: BLE001
        out["reason"] = f"erreur : {str(e)[:60]}"
    return out


def analyze_all() -> list[dict]:
    return [analyze(s) for s in config.WATCHLIST_MONITOR]


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


def check_and_alert(send: bool = True) -> dict:
    """Détecte les valeurs qui ENTRENT dans une zone actionnable et alerte."""
    from memory import state
    prev = state.get_state(STATE_KEY, default={}) or {}
    results = analyze_all()
    new_state = {}
    alerts = []
    for r in results:
        if not r.get("ok"):
            new_state[r["ticker"]] = prev.get(r["ticker"], "HOLD")
            continue
        code = r["signal"]
        new_state[r["ticker"]] = code
        _, _, actionable = SIGNALS.get(code, SIGNALS["HOLD"])
        # alerte seulement si la valeur ENTRE dans une zone actionnable (changement)
        if actionable and prev.get(r["ticker"]) != code:
            tag = "ACHAT" if code.startswith("BUY") else "VENTE/ALLÉGER"
            alerts.append(f"⚡ SIGNAL {tag}\n{_fmt_line(r)}")

    state.set_state(STATE_KEY, new_state)
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

    lines = [f"📋 SUIVI PORTEFEUILLE — {today}", ""]
    if buys:
        lines.append("🟢 À ACHETER / RENFORCER :")
        lines += [f"  {_fmt_line(r)}" for r in buys]
        lines.append("")
    if sells:
        lines.append("🔴 À VENDRE / ALLÉGER :")
        lines += [f"  {_fmt_line(r)}" for r in sells]
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
    """Bulletin complet du matin. Met à jour l'état SANS doublonner d'alertes
    ponctuelles (le bulletin récapitule déjà tout)."""
    res = check_and_alert(send=False)["results"]
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
