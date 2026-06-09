"""
thresholds.py — Simulation « et si le seuil d'alerte avait été plus bas ? »

À partir de l'historique des actions étudiées par les IA (14 derniers jours,
stocké dans agent_state "activity"), on simule, pour différents seuils de score
final, ce que ça aurait donné : on prend chaque finaliste dont le score dépasse
le seuil, on simule une entrée (clôture du jour) puis une sortie (objectif / stop
/ horizon, exactement comme en réel via market_context.compute_levels), et on
agrège réussite + P&L (1000 €/trade).

Honnête : ne comptent que les trades ARRIVÉS À TERME (objectif/stop touché, ou
horizon écoulé). Les signaux trop récents restent "en cours" et sont exclus —
donc la simulation se remplit au fil des jours.
"""

import logging

import data_fetcher
import market_context

logger = logging.getLogger("thresholds")

STAKE = 1000
LEVELS = (75, 65, 60, 55)


def _atr_pct(df, i0: int, period: int = 14):
    s = max(0, i0 - period)
    sub = df.iloc[s:i0 + 1]
    if len(sub) < 2:
        return None
    tr = float((sub["high"] - sub["low"]).mean())
    price = float(df["close"].iloc[i0])
    return (tr / price) if price else None


def _simulate_one(df, date_iso: str):
    """Rendement simulé d'un trade entré à la clôture de `date_iso`. None si encore ouvert."""
    if df is None or df.empty:
        return None
    idx = [ts.date().isoformat() for ts in df.index]
    after = [i for i, dd in enumerate(idx) if dd >= date_iso]
    if not after:
        return None
    i0 = after[0]
    entry = float(df["close"].iloc[i0])
    if entry <= 0:
        return None
    lv = market_context.compute_levels(entry, _atr_pct(df, i0))
    target, stop, hor = lv["target"], lv["stop"], int(lv["horizon"])
    future = df.iloc[i0 + 1: i0 + 1 + hor]
    if future.empty:
        return None
    for _, row in future.iterrows():
        if float(row["low"]) <= stop:
            return (stop - entry) / entry
        if float(row["high"]) >= target:
            return (target - entry) / entry
    if len(future) >= hor:   # horizon atteint sans toucher objectif/stop
        return (float(future.iloc[-1]["close"]) - entry) / entry
    return None              # pas encore assez de recul -> en cours


def simulate(levels=LEVELS) -> dict:
    """Simule les seuils sur l'historique d'activité. Retourne le rapport."""
    from memory import state
    log = state.get_state("activity", default={}) or {}

    # finalistes uniques par (date, ticker), on garde le meilleur score
    trades: dict[tuple, dict] = {}
    for d, runs in log.items():
        for r in runs:
            for det in (r.get("details") or []):
                tk, sc = det.get("ticker"), det.get("final_score")
                if not tk or sc is None:
                    continue
                key = (d, tk)
                if key not in trades or sc > trades[key]["score"]:
                    trades[key] = {"score": float(sc)}

    if not trades:
        return {"days": len(log), "total": 0, "closed": 0, "report": []}

    tickers = list({tk for (_, tk) in trades})
    bars = data_fetcher.fetch_batch(tickers, period="3mo", interval="1d")

    outcomes = []  # (score, realized_pct or None)
    for (d, tk), info in trades.items():
        outcomes.append((info["score"], _simulate_one(bars.get(tk), d)))

    closed = [(sc, o) for sc, o in outcomes if o is not None]
    report = []
    for lvl in levels:
        rs = [o for sc, o in closed if sc >= lvl]
        n = len(rs)
        wins = sum(1 for x in rs if x > 0)
        report.append({
            "level": lvl, "n": n,
            "win": (wins / n) if n else 0.0,
            "avg": (sum(rs) / n) if n else 0.0,
            "pnl": sum(x * STAKE for x in rs),
        })
    return {"days": len(log), "total": len(trades), "closed": len(closed), "report": report}


def format_report(res: dict) -> str:
    if res["total"] == 0:
        return ("📐 Simulation des seuils\nPas encore de données (aucun finaliste "
                "enregistré). Reviens dans quelques jours.")
    if res["closed"] == 0:
        return (f"📐 Simulation des seuils ({res['days']} j, {res['total']} actions étudiées)\n"
                "Aucun trade encore arrivé à terme (signaux trop récents). "
                "Les résultats apparaîtront dans quelques jours.")
    lines = [f"📐 SIMULATION DES SEUILS ({res['days']} j · {res['closed']} trades arrivés à terme)",
             "Si le seuil d'alerte avait été :"]
    for r in res["report"]:
        if r["n"] == 0:
            lines.append(f"  • {r['level']} : aucun trade")
        else:
            lines.append(f"  • {r['level']} : {r['n']} trades · {r['win']*100:.0f}% réussite · "
                         f"{r['avg']*100:+.1f}%/trade · {r['pnl']:+,.0f} €")
    lines.append("\n(1000 €/trade, sorties objectif/stop/horizon comme en réel. "
                 "Indicatif, hors frais.)")
    return "\n".join(lines)


def run(send: bool = True, levels=LEVELS) -> str:
    msg = format_report(simulate(levels))
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi simulation seuils échoué : %s", e)
    return msg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run(send=False)
