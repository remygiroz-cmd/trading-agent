"""
budget_sim.py — « Si j'avais investi X € en suivant le bot ? »

Contrairement au paper trading (1000 €/signal, argent infini), on simule un
PORTE-MONNAIE UNIQUE au budget fixe (ex. 1500 €) qui suit les signaux : il ne
peut pas dépasser son budget, le cash se libère quand une position se clôture,
et on regarde combien il reste à la fin. Une simulation par seuil (75/70/65/60)
pour comparer.

Source : l'historique des actions étudiées (agent_state "activity", 14 j). Pour
chaque finaliste dont le score dépasse le seuil, on simule entrée (clôture du
jour) -> sortie (objectif/stop/horizon, comme en réel). Contrainte de cash gérée
chronologiquement.

Honnête : seuls les trades ARRIVÉS À TERME comptent. Les positions encore
ouvertes ne sont pas valorisées (le résultat se précisera dans quelques jours).
Le dimensionnement (part fixe du budget) est une simplification — l'historique
ne conserve pas la taille exacte calculée en temps réel.
"""

import logging

import data_fetcher
import market_context
from thresholds import _atr_pct

logger = logging.getLogger("budget_sim")


def _trade_outcome(df, date_iso: str):
    """(date de sortie ISO, rendement) d'un trade entré à la clôture de date_iso. None si en cours."""
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
    fut = df.iloc[i0 + 1: i0 + 1 + hor]
    if fut.empty:
        return None
    for ts, row in fut.iterrows():
        if float(row["low"]) <= stop:
            return ts.date().isoformat(), (stop - entry) / entry
        if float(row["high"]) >= target:
            return ts.date().isoformat(), (target - entry) / entry
    if len(fut) >= hor:
        ts = fut.index[-1]
        return ts.date().isoformat(), (float(fut.iloc[-1]["close"]) - entry) / entry
    return None


def _collect_trades() -> list[tuple]:
    """Liste (date, ticker, score) des finalistes uniques, triée par date."""
    from memory import state
    import config
    log = state.get_state("activity", default={}) or {}
    excl = {t.upper() for t in config.TRADE_REPUBLIC.get("exclude", [])}
    best: dict[tuple, float] = {}
    for d, runs in log.items():
        for r in runs:
            for det in (r.get("details") or []):
                tk, sc = det.get("ticker"), det.get("final_score")
                if not tk or sc is None or str(tk).upper() in excl:
                    continue
                key = (d, tk)
                best[key] = max(best.get(key, -1), float(sc))
    return sorted(((d, tk, sc) for (d, tk), sc in best.items()), key=lambda x: x[0])


def _run_wallet(trades, outcomes, level, budget, per_trade_pct) -> dict:
    """Simule un porte-monnaie pour un seuil donné (contrainte de cash)."""
    import datetime as dt
    today = dt.date.today().isoformat()
    per_trade = budget * per_trade_pct
    cash = budget
    realized = 0.0
    n, wins = 0, 0
    open_pos = []  # {exit_date, cost, proceeds}

    def _free(upto: str):
        nonlocal cash, realized, wins, open_pos
        keep = []
        for p in open_pos:
            if p["exit_date"] <= upto:
                cash += p["proceeds"]
                realized += p["proceeds"] - p["cost"]
                if p["proceeds"] > p["cost"]:
                    wins += 1
            else:
                keep.append(p)
        open_pos = keep

    for (d, tk, sc) in trades:
        if sc < level:
            continue
        _free(d)                       # libère le cash des positions clôturées avant ce jour
        out = outcomes.get((d, tk))
        if out is None:
            continue                    # pas de données / encore ouvert
        exit_date, rpct = out
        invest = min(per_trade, cash)
        if invest < budget * 0.05:      # plus assez de cash dispo
            continue
        cash -= invest
        open_pos.append({"exit_date": exit_date, "cost": invest,
                         "proceeds": invest * (1 + rpct)})
        n += 1

    _free(today)                        # clôture tout ce qui est arrivé à terme aujourd'hui
    return {"level": level, "trades": n, "wins": wins,
            "realized": round(realized, 2), "final": round(budget + realized, 2)}


def simulate(budget=None, levels=None, per_trade_pct=None) -> dict:
    cfg = config_budget()
    budget = budget or cfg["budget"]
    levels = levels or cfg["levels"]
    per_trade_pct = per_trade_pct or cfg["per_trade_pct"]

    trades = _collect_trades()
    if not trades:
        return {"budget": budget, "total": 0, "wallets": []}

    tickers = list({tk for (_, tk, _) in trades})
    bars = data_fetcher.fetch_batch(tickers, period="3mo", interval="1d")
    outcomes = {(d, tk): _trade_outcome(bars.get(tk), d) for (d, tk, _) in trades}

    wallets = [_run_wallet(trades, outcomes, lvl, budget, per_trade_pct) for lvl in levels]
    return {"budget": budget, "total": len(trades), "wallets": wallets,
            "per_trade_pct": per_trade_pct}


def config_budget() -> dict:
    import config
    return config.BUDGET_SIM


def format_report(res: dict) -> str:
    b = res["budget"]
    if res["total"] == 0:
        return (f"💼 Simulation budget {b:.0f} €\nPas encore de données. "
                "Reviens dans quelques jours.")
    any_trade = any(w["trades"] for w in res["wallets"])
    if not any_trade:
        return (f"💼 Simulation budget {b:.0f} € ({res['total']} actions étudiées)\n"
                "Aucun trade encore arrivé à terme (signaux trop récents). "
                "Les chiffres arriveront dans quelques jours.")
    lines = [f"💼 SIMULATION BUDGET {b:.0f} €",
             "Si tu avais investi ce budget en suivant le bot :"]
    for w in res["wallets"]:
        if w["trades"] == 0:
            lines.append(f"  • seuil {w['level']} : aucun trade")
            continue
        wr = w["wins"] / w["trades"] * 100
        lines.append(f"  • seuil {w['level']} : {w['trades']} trades · {wr:.0f}% gagnants · "
                     f"{w['realized']:+,.0f} € → {w['final']:,.0f} €")
    lines.append(f"\n(position {res['per_trade_pct']*100:.0f}% du budget/trade, sorties "
                 "objectif/stop/horizon. Trades en cours non comptés. Indicatif, hors frais.)")
    return "\n".join(lines)


def run(send: bool = True) -> str:
    msg = format_report(simulate())
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi simulation budget échoué : %s", e)
    return msg


# ─────────────────────────────────────────────────────────────
# RAPPORT DÉTAILLÉ (journal trade par trade + cumul) par seuil
# ─────────────────────────────────────────────────────────────

def _ledger(trades, detail_map, level, budget, per_trade_pct) -> list[dict]:
    """Journal des trades clôturés pris par le porte-monnaie (contrainte de cash)."""
    per_trade = budget * per_trade_pct
    cash = budget
    open_pos = []
    executed = []

    def _free(upto: str):
        nonlocal cash, open_pos
        keep = []
        for p in open_pos:
            if p["exit_date"] <= upto:
                cash += p["proceeds"]
            else:
                keep.append(p)
        open_pos = keep

    for (d, tk, sc) in trades:           # trades déjà triés par date d'étude
        if sc < level:
            continue
        _free(d)
        det = detail_map.get((d, tk))
        if det is None:                  # pas encore clôturé -> on n'inscrit pas
            continue
        invest = min(per_trade, cash)
        if invest < budget * 0.05:
            continue
        cash -= invest
        proceeds = invest * (1 + det["pct"])
        open_pos.append({"exit_date": det["exit_date"], "proceeds": proceeds})
        executed.append({
            "tk": tk, "score": sc, "entry_date": det["entry_date"], "entry": det["entry"],
            "exit_date": det["exit_date"], "exit": det["exit"], "reason": det["reason"],
            "pct": det["pct"], "invest": invest, "pnl": proceeds - invest,
        })

    executed.sort(key=lambda x: x["exit_date"])   # ordre de clôture pour le cumul
    return executed


def _format_ledger(executed: list[dict], level: int, budget: float, n_open: int) -> str:
    if not executed:
        return (f"🧾 SEUIL {level} — budget {budget:.0f} €\n"
                f"Aucun trade clôturé pour l'instant ({n_open} en cours).")
    lines = [f"🧾 SEUIL {level} — budget {budget:.0f} €", ""]
    balance = budget
    wins = 0
    for t in executed:
        balance += t["pnl"]
        if t["pnl"] > 0:
            wins += 1
        emoji = "✅" if t["pct"] > 0 else "❌" if t["pct"] < 0 else "➖"
        lines.append(
            f"{emoji} {t['tk']} (score {t['score']:.0f})\n"
            f"   {t['entry_date']} {t['entry']:.2f} → {t['exit_date']} {t['exit']:.2f} "
            f"({t['reason']}) {t['pct']*100:+.1f}%\n"
            f"   mise {t['invest']:.0f} € → {t['pnl']:+.0f} € · solde {balance:,.0f} €")
    total_pnl = balance - budget
    lines.append(f"\n➡️ TOTAL seuil {level} : {len(executed)} trades, {wins} gagnants, "
                 f"{total_pnl:+,.0f} € → {balance:,.0f} €")
    if n_open:
        lines.append(f"   (+ {n_open} position(s) encore en cours, non comptées)")
    return "\n".join(lines)


def detail(levels=(65, 60), send: bool = True) -> str:
    """Journal complet trade par trade + cumul, pour chaque seuil."""
    import thresholds
    cfg = config_budget()
    budget, ptp = cfg["budget"], cfg["per_trade_pct"]

    trades = _collect_trades()
    if not trades:
        msg = f"🧾 Rapport budget {budget:.0f} € : pas encore de données."
        print(msg)
        if send:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        return msg

    tickers = list({tk for (_, tk, _) in trades})
    bars = data_fetcher.fetch_batch(tickers, period="3mo", interval="1d")
    detail_map = {(d, tk): thresholds._trade_detail(bars.get(tk), d) for (d, tk, _) in trades}

    blocks = []
    for lvl in levels:
        executed = _ledger(trades, detail_map, lvl, budget, ptp)
        n_open = sum(1 for (d, tk, sc) in trades
                     if sc >= lvl and detail_map.get((d, tk)) is None)
        blocks.append(_format_ledger(executed, lvl, budget, n_open))

    msg = (f"📒 RAPPORT DÉTAILLÉ — budget {budget:.0f} € "
           f"(position {ptp*100:.0f}%/trade, valeurs Trade Republic only)\n\n"
           + "\n\n".join(blocks)
           + "\n\n(Sorties objectif/stop/horizon comme en réel. Indicatif, hors frais.)")
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi rapport budget échoué : %s", e)
    return msg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run(send=False)