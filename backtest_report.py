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


def run_report(years: int = 3, send: bool = True) -> str:
    import optimize
    import autotune

    train, test, _ = optimize.build_signals(years)
    signals = (train or []) + (test or [])
    if not signals:
        msg = f"📈 Backtest {years} ans : aucun signal généré (données indisponibles ?)."
        print(msg)
        return msg

    ts, ss, h = autotune.active_spec()
    dated = []
    for (df, i, entry, atr, date) in signals:
        r = optimize.simulate(entry, atr, df.iloc[i + 1:], ts, ss, h)
        if r is not None:
            dated.append((date, r))

    m = _metrics(dated)
    msg = format_report(m, years, (ts, ss, h))
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi backtest échoué : %s", e)
    return msg


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
