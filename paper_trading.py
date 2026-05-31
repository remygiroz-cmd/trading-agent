"""
paper_trading.py — Paper trading (positions virtuelles).

Principe demandé par Rémy : on fait COMME SI il prenait TOUS les signaux, avec
1000 € investis sur chacun. Le P&L est calculé à partir du dernier résultat
connu de chaque signal (result_7d > result_3d > result_1d, sinon prix en direct).

- is_paper_active() : True pendant la fenêtre (30 j) sauf arrêt manuel
- stop_paper() / resume_paper() : arrêt/reprise manuels (Telegram /stop_paper)
- compute_portfolio() : récap global du portefeuille virtuel
- format_portfolio() : texte lisible pour Telegram
"""

import logging
import datetime as dt

import config

logger = logging.getLogger("paper")

STATE_KEY = "paper_state"


def _load_state() -> dict:
    from memory import state
    return state.get_state(STATE_KEY, default={}) or {}


def _save_state(data: dict) -> None:
    from memory import state
    state.set_state(STATE_KEY, data)


def ensure_started(today: dt.date | None = None) -> str:
    state = _load_state()
    if not state.get("start_date"):
        today = today or dt.date.today()
        state["start_date"] = today.isoformat()
        _save_state(state)
        logger.info("Paper trading démarré le %s", state["start_date"])
    return state["start_date"]


def stop_paper() -> None:
    """Arrête manuellement le paper trading (passage en réel)."""
    state = _load_state()
    state["stopped"] = True
    state["stopped_at"] = dt.date.today().isoformat()
    _save_state(state)
    logger.info("Paper trading ARRÊTÉ manuellement.")


def resume_paper() -> None:
    state = _load_state()
    state["stopped"] = False
    _save_state(state)


def is_stopped() -> bool:
    return bool(_load_state().get("stopped"))


def is_paper_active(today: dt.date | None = None) -> bool:
    """True si on est en paper trading (activé, fenêtre non écoulée, non arrêté)."""
    if not config.PAPER_TRADING_CONFIG["enabled"]:
        return False
    if is_stopped():
        return False
    start = ensure_started(today)
    today = today or dt.date.today()
    elapsed = (today - dt.date.fromisoformat(start)).days
    return elapsed < config.PAPER_TRADING_CONFIG["duration_days"]


def days_elapsed(today: dt.date | None = None) -> int:
    start = ensure_started(today)
    today = today or dt.date.today()
    return (today - dt.date.fromisoformat(start)).days


def days_left(today: dt.date | None = None) -> int:
    return max(0, config.PAPER_TRADING_CONFIG["duration_days"] - days_elapsed(today))


# ─────────────────────────────────────────────────────────────
# RÉCAP DU PORTEFEUILLE VIRTUEL
# ─────────────────────────────────────────────────────────────

def _latest_result(sig: dict) -> tuple[float | None, str]:
    """Dernier résultat connu d'un signal (fraction, horizon). None si aucun."""
    for field, label in [("result_7d", "J+7"), ("result_3d", "J+3"), ("result_1d", "J+1")]:
        if sig.get(field) is not None:
            return float(sig[field]), label
    return None, "en cours"


def compute_portfolio(live: bool = False) -> dict:
    """
    Récap des positions virtuelles (1000 € chacune).

    live=True : récupère le prix actuel pour les signaux sans résultat (plus lent).
    """
    stake = config.PAPER_TRADING_CONFIG["fixed_position_eur"]
    try:
        from memory import database
        rows = (database.table("trading_signals")
                .select("*").eq("is_paper", True)
                .order("created_at", desc=True).execute()).data or []
    except Exception as e:  # noqa: BLE001
        logger.error("compute_portfolio : %s", e)
        rows = []

    positions, closed_pnl, open_count = [], 0.0, 0
    wins = losses = 0
    invested_closed = 0.0
    live_prices = {}

    if live:
        opens = [r["ticker"] for r in rows if _latest_result(r)[0] is None]
        if opens:
            try:
                import data_fetcher
                data = data_fetcher.fetch_batch(list(set(opens)), period="5d", interval="1d")
                for tk, df in data.items():
                    if df is not None and not df.empty:
                        live_prices[tk] = float(df["close"].iloc[-1])
            except Exception:  # noqa: BLE001
                pass

    for r in rows:
        res, horizon = _latest_result(r)
        if res is None and live and r["ticker"] in live_prices and r.get("entry_price"):
            entry = float(r["entry_price"])
            if entry > 0:
                res = (live_prices[r["ticker"]] - entry) / entry
                horizon = "live"
        pnl = stake * res if res is not None else None
        positions.append({
            "ticker": r["ticker"], "pattern": r["pattern_name"],
            "entry": r.get("entry_price"), "result": res, "horizon": horizon,
            "pnl_eur": round(pnl, 2) if pnl is not None else None,
            "date": r.get("created_at", "")[:10],
        })
        if res is None:
            open_count += 1
        else:
            closed_pnl += pnl
            invested_closed += stake
            if res > 0:
                wins += 1
            else:
                losses += 1

    closed = wins + losses
    return {
        "stake": stake,
        "n_total": len(rows),
        "n_open": open_count,
        "n_closed": closed,
        "wins": wins, "losses": losses,
        "win_rate": (wins / closed) if closed else 0.0,
        "pnl_eur": round(closed_pnl, 2),
        "invested_closed": invested_closed,
        "roi": (closed_pnl / invested_closed) if invested_closed else 0.0,
        "positions": positions,
        "active": is_paper_active(),
        "days_elapsed": days_elapsed() if _load_state().get("start_date") else 0,
        "days_left": days_left() if _load_state().get("start_date") else config.PAPER_TRADING_CONFIG["duration_days"],
    }


def format_portfolio(p: dict) -> str:
    status = "actif" if p["active"] else ("arrêté" if is_stopped() else "terminé")
    msg = f"""📒 PAPER TRADING ({p['stake']} € / trade) — {status}
━━━━━━━━━━━━━━━━━━━━━━━
Jour {p['days_elapsed']}/{config.PAPER_TRADING_CONFIG['duration_days']} ({p['days_left']} restants)

Positions : {p['n_total']} ({p['n_closed']} clôturées, {p['n_open']} en cours)
Réussite   : {p['win_rate']*100:.0f}%  ({p['wins']}✅ / {p['losses']}❌)
P&L réalisé : {p['pnl_eur']:+.0f} €  (ROI {p['roi']*100:+.1f}%)
"""
    # Top 3 / Flop 3 parmi les clôturées
    closed = [x for x in p["positions"] if x["pnl_eur"] is not None]
    closed.sort(key=lambda x: x["pnl_eur"], reverse=True)
    if closed:
        msg += "\nMeilleurs :\n"
        for x in closed[:3]:
            msg += f"  ✅ {x['ticker']} {x['pnl_eur']:+.0f} € ({x['result']*100:+.1f}%)\n"
        if len(closed) > 3:
            msg += "Pires :\n"
            for x in closed[-3:]:
                msg += f"  ❌ {x['ticker']} {x['pnl_eur']:+.0f} € ({x['result']*100:+.1f}%)\n"
    if p["n_open"]:
        msg += f"\n⏳ {p['n_open']} position(s) encore en cours."
    return msg
