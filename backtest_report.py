"""
backtest_report.py — Backtest rigoureux du socle technique sur plusieurs années.

Réutilise le moteur de optimize.py (génération des signaux sur l'historique +
simulation des sorties) et produit un rapport complet avec des métriques de pro :
réussite, espérance, profit factor, drawdown (pire perte cumulée), résultat net
après frais.

Honnête : ça valide le SOCLE TECHNIQUE (figures + force relative + sorties ATR),
PAS le débat des 3 IA (impossible à rejouer dans le passé : pas de scores IA
historiques). C'est néanmoins la meilleure preuve disponible que la base de la
stratégie a un avantage — sur des années, pas sur 3 trades.
"""

import sys
import logging

logger = logging.getLogger("backtest_report")

STAKE = 1000
FEE_RT = 0.004   # frais aller-retour estimés (0,4%)

# Univers NEUTRE : grandes valeurs liquides, multi-secteurs, dispo Trade Republic,
# NON choisies pour leur momentum -> retire (en grande partie) le biais du survivant
# de la watchlist "chaude". US blue chips + grandes européennes.
NEUTRAL_UNIVERSE = [
    # US large caps multi-secteurs
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "JPM", "V", "JNJ", "WMT",
    "PG", "XOM", "KO", "PEP", "DIS", "NKE", "MCD", "CSCO", "INTC", "VZ",
    "BA", "CAT", "GE", "IBM", "ORCL", "CVX", "PFE", "MRK", "ABBV", "BAC",
    "HD", "UNH", "CRM", "ADBE", "NFLX", "AMD", "QCOM", "TXN", "COST", "WFC",
    # Grandes européennes (Euronext / Xetra)
    "MC.PA", "OR.PA", "AIR.PA", "SAN.PA", "BNP.PA", "DG.PA", "SU.PA", "AI.PA",
    "EL.PA", "RMS.PA", "BN.PA", "KER.PA", "CAP.PA", "DSY.PA", "SAP", "ASML",
    "SIE.DE", "ALV.DE", "BAS.DE", "BMW.DE",
]


def _metrics(dated: list[tuple]) -> dict:
    """dated : liste de (date, rendement). Calcule toutes les métriques."""
    rs = [r for _, r in dated]
    n = len(rs)
    if n == 0:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # Courbe d'équité (1000 €/trade) par ordre chronologique -> drawdown
    ordered = sorted(dated, key=lambda x: x[0])
    eq = peak = 0.0
    maxdd = 0.0
    for _, r in ordered:
        eq += r * STAKE
        peak = max(peak, eq)
        maxdd = min(maxdd, eq - peak)

    net = sum(rs) * STAKE - n * STAKE * FEE_RT
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "expectancy": sum(rs) / n,
        "profit_factor": pf,
        "best": max(rs),
        "worst": min(rs),
        "max_drawdown_eur": maxdd,
        "gross_eur": sum(rs) * STAKE,
        "net_eur": net,
    }


def _build_signals(years: int, tickers: list[str]):
    """Signaux du socle technique sur un univers donné, avec leur score de figure.

    Retourne une liste de (df, i, entry, atr, date, setup_score).
    """
    import data_fetcher
    from horizon_test import collect_signals

    spx = data_fetcher.fetch_ticker("^GSPC", period=f"{years+1}y", interval="1d")
    regime, spx_by_date = {}, {}
    if not spx.empty:
        ma = spx["close"].rolling(50).mean()
        regime = {d.strftime("%Y-%m-%d"): bool(x) for d, x in (spx["close"] >= ma).items()}
        spx_by_date = {d.strftime("%Y-%m-%d"): float(x) for d, x in spx["close"].items()}

    data = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")
    out = []
    for tk, df in data.items():
        if df is None or df.empty or len(df) < 80:
            continue
        d2, sigs = collect_signals(df, regime, spx_by_date)
        for (i, e, a, sc) in sigs:
            out.append((d2, i, e, a, d2.index[i], sc))
    return out


# Tranches de qualité technique (score de figure /50) — l'équivalent historique
# de "relever la barre" (le seuil IA 60/65/70/75 n'existe pas dans le passé).
TIERS = [("≥ 45/50", 45, 999), ("40-44", 40, 45), ("35-39", 35, 40)]


def run_report(years: int = 3, universe: str = "neutral", send: bool = True) -> str:
    import autotune

    tickers = NEUTRAL_UNIVERSE if universe == "neutral" else None
    if tickers is None:
        import watchlist
        tickers = watchlist.get_full_watchlist()

    signals = _build_signals(years, tickers)
    if not signals:
        msg = f"📈 Backtest {years} ans : aucun signal généré (données indisponibles ?)."
        print(msg)
        return msg

    ts, ss, h = autotune.active_spec()
    scored = []  # (date, rendement, score)
    import optimize
    for (df, i, entry, atr, date, sc) in signals:
        r = optimize.simulate(entry, atr, df.iloc[i + 1:], ts, ss, h)
        if r is not None:
            scored.append((date, r, sc))

    overall = _metrics([(d, r) for d, r, _ in scored])
    tiers = []
    for label, lo, hi in TIERS:
        sub = [(d, r) for d, r, sc in scored if lo <= sc < hi]
        if sub:
            tiers.append((label, _metrics(sub)))

    label_univ = "univers NEUTRE (anti-biais)" if universe == "neutral" else "watchlist"
    msg = format_full(overall, tiers, years, label_univ)
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi backtest échoué : %s", e)
    return msg


def format_full(overall: dict, tiers: list, years: int, label_univ: str) -> str:
    if overall.get("n", 0) == 0:
        return f"📈 Backtest {years} ans : aucun trade simulé."
    pf = overall["profit_factor"]
    pf_txt = "∞" if pf == float("inf") else f"{pf:.2f}"
    verdict = ("✅ avantage positif" if overall["expectancy"] > 0 and pf > 1.2
               else "⚠️ avantage faible" if overall["expectancy"] > 0 else "❌ pas d'avantage")
    lines = [
        f"📈 BACKTEST {years} ANS — {label_univ}",
        f"Trades : {overall['n']} · réussite {overall['win_rate']*100:.0f}% · "
        f"espérance {overall['expectancy']*100:+.2f}%/trade",
        f"Profit factor : {pf_txt} · net {overall['net_eur']:+,.0f} € (1000€/trade, frais inclus)",
        f"Drawdown : {overall['max_drawdown_eur']:+,.0f} €",
        "",
        "📊 Effet de RELEVER LA BARRE (qualité technique de la figure) :",
    ]
    for label, m in tiers:
        pf2 = m["profit_factor"]
        pf2_txt = "∞" if pf2 == float("inf") else f"{pf2:.2f}"
        lines.append(f"  • score {label} : {m['n']} trades · {m['win_rate']*100:.0f}% · "
                     f"espérance {m['expectancy']*100:+.2f}% · PF {pf2_txt}")
    lines += [
        f"\nVerdict : {verdict}.",
        "(Socle TECHNIQUE, hors débat IA. Les seuils IA 60/65/70/75 sont mesurés "
        "en direct par la simulation du soir. Indicatif, hors slippage.)",
    ]
    return "\n".join(lines)


def format_report(m: dict, years: int, spec=None) -> str:
    if m.get("n", 0) == 0:
        return f"📈 Backtest {years} ans : aucun trade simulé."
    pf = m["profit_factor"]
    pf_txt = "∞" if pf == float("inf") else f"{pf:.2f}"
    verdict = ("✅ avantage positif" if m["expectancy"] > 0 and pf > 1.2
               else "⚠️ avantage faible" if m["expectancy"] > 0
               else "❌ pas d'avantage")
    lines = [
        f"📈 BACKTEST {years} ANS — socle technique",
        f"Trades simulés : {m['n']}",
        f"Réussite : {m['win_rate']*100:.0f}%",
        f"Espérance : {m['expectancy']*100:+.2f}%/trade",
        f"Gain moyen : {m['avg_win']*100:+.1f}% · Perte moyenne : {m['avg_loss']*100:+.1f}%",
        f"Profit factor : {pf_txt} (>1 = rentable)",
        f"Pire perte cumulée : {m['max_drawdown_eur']:+,.0f} € (sur 1000 €/trade)",
        f"Résultat net (frais inclus) : {m['net_eur']:+,.0f} €",
        f"Meilleur / pire trade : {m['best']*100:+.0f}% / {m['worst']*100:+.0f}%",
        f"\nVerdict : {verdict}.",
        "(Valide le SOCLE TECHNIQUE, hors débat IA. Indicatif, hors slippage.)",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    yrs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_report(yrs, send=False)
