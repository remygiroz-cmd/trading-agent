"""
memory/learning.py — Boucle d'apprentissage cumulative.

- update_open_signal_results : remplit J+1/J+3/J+7, marque stop/objectif atteints
- update_ticker_performance_all : agrège les stats par ticker
- generate_learned_rules : déduit des règles fiables depuis l'historique
- run_daily_learning / run_weekly_learning : orchestrations appelées par le scheduler

Aucune suppression : on n'insère et ne met à jour que (règle métier 8).
"""

import logging
import datetime as dt

import data_fetcher
from . import database, signals, performance, weights

logger = logging.getLogger("learning")


# ─────────────────────────────────────────────────────────────
# MISE À JOUR DES RÉSULTATS (quotidien, 22h30)
# ─────────────────────────────────────────────────────────────

def _parse_dt(s: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return dt.datetime.now(dt.timezone.utc)


def update_open_signal_results(now: dt.datetime | None = None) -> dict:
    """Met à jour les signaux ouverts avec le prix actuel. Retourne un résumé."""
    now = now or dt.datetime.now(dt.timezone.utc)
    open_signals = signals.get_open_signals()
    updated, stops, targets = 0, 0, 0

    # Récupération groupée des prix
    tickers = list({s["ticker"] for s in open_signals})
    prices = {}
    if tickers:
        data = data_fetcher.fetch_batch(tickers, period="5d", interval="1d")
        for tk, df in data.items():
            if df is not None and not df.empty:
                prices[tk] = float(df["close"].iloc[-1])

    for s in open_signals:
        price = prices.get(s["ticker"])
        if price is None:
            continue
        entry = float(s["entry_price"])
        if entry <= 0:
            continue
        result = (price - entry) / entry
        days = (now - _parse_dt(s["created_at"])).days
        signals.update_signal_result(s["id"], days, result)
        updated += 1

        if s.get("stop_loss") and price <= float(s["stop_loss"]):
            signals.mark_stop_reached(s["id"])
            stops += 1
        if s.get("target_price") and price >= float(s["target_price"]):
            signals.mark_target_reached(s["id"])
            targets += 1

    logger.info("Résultats MAJ : %s signaux, %s stops, %s objectifs", updated, stops, targets)
    return {"updated": updated, "stops": stops, "targets": targets}


# ─────────────────────────────────────────────────────────────
# CLÔTURE SIMULÉE DES POSITIONS (vente paper trading)
# ─────────────────────────────────────────────────────────────

def _simulate_exit(sig: dict, bars, now: dt.datetime):
    """
    Détermine la sortie d'une position en parcourant les bougies jour après jour
    depuis l'entrée :
      - si le plus haut touche l'objectif -> sortie à l'objectif
      - sinon si le plus bas touche le stop -> sortie au stop
      - sinon, à la fin de l'horizon -> sortie à la clôture
    Si l'objectif ET le stop sont touchés le même jour, on retient le STOP
    (hypothèse prudente, on ne connaît pas l'ordre intra-journalier).

    Retourne dict de clôture, ou None si la position est encore ouverte.
    """
    import pandas as pd

    entry = float(sig["entry_price"])
    if entry <= 0 or bars is None or bars.empty:
        return None
    target = float(sig["target_price"]) if sig.get("target_price") else None
    stop = float(sig["stop_loss"]) if sig.get("stop_loss") else None
    horizon = int(sig.get("horizon_days") or 10)

    created = _parse_dt(sig["created_at"])
    # bougies postérieures à l'entrée
    bars = bars[bars.index > pd.Timestamp(created).tz_localize(None)]
    if bars.empty:
        return None

    for i, (ts, row) in enumerate(bars.iterrows(), start=1):
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        # stop prioritaire si les deux sont touchés le même jour (prudence)
        if stop and lo <= stop:
            return _close(sig, stop, ts, "stop", entry, i)
        if target and hi >= target:
            return _close(sig, target, ts, "objectif", entry, i)
        if i >= horizon:
            return _close(sig, close, ts, "horizon", entry, i)

    # horizon non encore atteint et ni stop ni objectif touchés -> encore ouverte
    elapsed = (now - created).days
    if elapsed >= horizon:
        # horizon dépassé mais pas assez de bougies (week-ends/jours fériés) :
        # clôture à la dernière bougie disponible
        last_ts = bars.index[-1]
        return _close(sig, float(bars.iloc[-1]["close"]), last_ts, "horizon", entry, len(bars))
    return None


def _close(sig, exit_price, ts, reason, entry, hold_days) -> dict:
    pct = (exit_price - entry) / entry
    from config import PAPER_TRADING_CONFIG
    stake = PAPER_TRADING_CONFIG["fixed_position_eur"]
    return {
        "closed": True,
        "exit_price": round(exit_price, 4),
        "exit_date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "exit_reason": reason,
        "realized_pct": round(pct, 4),
        "realized_pnl_eur": round(stake * pct, 2),
        "hold_days": hold_days,
    }


def close_due_paper_trades(now: dt.datetime | None = None) -> dict:
    """
    Clôture les positions paper dont l'objectif/stop a été touché ou l'horizon
    écoulé. Met à jour les colonnes de clôture en base. Retourne un résumé.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = (database.table("trading_signals")
            .select("*").eq("is_paper", True).execute()).data or []
    open_rows = [r for r in rows if not r.get("closed")]
    if not open_rows:
        return {"closed": 0}

    tickers = list({r["ticker"] for r in open_rows})
    bars_by_ticker = data_fetcher.fetch_batch(tickers, period="60d", interval="1d")

    closed, by_reason = 0, {"objectif": 0, "stop": 0, "horizon": 0}
    for r in open_rows:
        bars = bars_by_ticker.get(r["ticker"])
        result = _simulate_exit(r, bars, now)
        if result:
            try:
                database.table("trading_signals").update(result).eq("id", r["id"]).execute()
                closed += 1
                by_reason[result["exit_reason"]] = by_reason.get(result["exit_reason"], 0) + 1
            except Exception as e:  # noqa: BLE001
                logger.warning("Clôture %s échouée : %s", r["ticker"], e)

    logger.info("Positions clôturées : %s (%s)", closed, by_reason)
    return {"closed": closed, "by_reason": by_reason}


# ─────────────────────────────────────────────────────────────
# PERFORMANCE PAR TICKER
# ─────────────────────────────────────────────────────────────

def update_ticker_performance_all() -> int:
    """Recalcule les agrégats par ticker depuis les signaux clos (result_7d connu)."""
    rows = (database.table("trading_signals")
            .select("ticker, result_7d")
            .execute()).data or []

    by_ticker: dict[str, list[float]] = {}
    for r in rows:
        if r.get("result_7d") is not None:
            by_ticker.setdefault(r["ticker"], []).append(float(r["result_7d"]))

    for ticker, results in by_ticker.items():
        total = len(results)
        correct = sum(1 for x in results if x > 0)
        gains = [x for x in results if x > 0]
        losses = [x for x in results if x <= 0]
        performance.upsert_ticker_performance(ticker, {
            "total_signals": total,
            "correct_signals": correct,
            "win_rate": round(correct / total, 3) if total else 0,
            "avg_gain": round(sum(gains) / len(gains), 4) if gains else 0,
            "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0,
        })
    logger.info("Perf ticker recalculée pour %s tickers", len(by_ticker))
    return len(by_ticker)


# ─────────────────────────────────────────────────────────────
# GÉNÉRATION DE RÈGLES APPRISES
# ─────────────────────────────────────────────────────────────

def generate_learned_rules(min_sample: int = 8) -> list[dict]:
    """
    Déduit des règles depuis l'historique clos :
      - par figure chartiste (taux de réussite)
      - par tranche de score final (>=85 vs 75-84)
    N'insère une règle que si l'échantillon est suffisant et le signal net.
    """
    rows = (database.table("trading_signals")
            .select("pattern_name, final_score, result_7d")
            .execute()).data or []
    closed = [r for r in rows if r.get("result_7d") is not None]
    if len(closed) < min_sample:
        logger.info("Pas assez de signaux clos (%s) pour générer des règles.", len(closed))
        return []

    created = []

    # Règles par figure
    by_pattern: dict[str, list[float]] = {}
    for r in closed:
        by_pattern.setdefault(r["pattern_name"], []).append(float(r["result_7d"]))
    for pattern, res in by_pattern.items():
        if len(res) < min_sample:
            continue
        wr = sum(1 for x in res if x > 0) / len(res)
        if wr >= 0.65:
            rule = performance.add_learned_rule(
                f"La figure {pattern} réussit dans {wr*100:.0f}% des cas",
                "pattern", wr, len(res))
            if rule:
                created.append(rule)
        elif wr <= 0.35:
            rule = performance.add_learned_rule(
                f"Méfiance : la figure {pattern} échoue souvent ({(1-wr)*100:.0f}% de pertes)",
                "pattern", 1 - wr, len(res))
            if rule:
                created.append(rule)

    # Règle haute conviction
    high = [float(r["result_7d"]) for r in closed if (r.get("final_score") or 0) >= 85]
    if len(high) >= min_sample:
        wr = sum(1 for x in high if x > 0) / len(high)
        if wr >= 0.65:
            rule = performance.add_learned_rule(
                f"Les signaux à score >= 85/100 réussissent à {wr*100:.0f}%",
                "timing", wr, len(high))
            if rule:
                created.append(rule)

    logger.info("Règles apprises générées : %s", len(created))
    return created


# ─────────────────────────────────────────────────────────────
# ORCHESTRATIONS
# ─────────────────────────────────────────────────────────────

def run_daily_learning() -> dict:
    """Quotidien (22h30) : MAJ résultats + clôtures simulées + perf ticker."""
    res = update_open_signal_results()
    closures = close_due_paper_trades()
    update_ticker_performance_all()
    res["closures"] = closures
    return res


def _winrate(results: list[float]) -> tuple[float, int]:
    """Taux de réussite + taille d'échantillon."""
    if not results:
        return 0.0, 0
    return sum(1 for r in results if r > 0) / len(results), len(results)


def analyze_signal_drivers(min_sample: int = 8) -> list[dict]:
    """
    ATTRIBUTION : mesure, sur les signaux clos, quel pilier prédit le mieux les
    gains (conviction, fondamental, sentiment, divergence) et en tire des règles.

    Sans biais : on lit ce qui était connu AU MOMENT du signal (colonnes
    enregistrées) vs le résultat J+7 réel. Dégrade en silence si la migration 005
    n'est pas passée (colonnes absentes -> valeurs None ignorées).
    """
    rows = (database.table("trading_signals")
            .select("result_7d, conviction, fundamental_score, news_sentiment, divergence")
            .execute()).data or []
    closed = [r for r in rows if r.get("result_7d") is not None]
    if len(closed) < min_sample:
        return []

    created = []

    def add(desc, rtype, reliability, n):
        rule = performance.add_learned_rule(desc, rtype, reliability, n)
        if rule:
            created.append(rule)

    # 1) Conviction élevée (>=75) vs le reste
    high = [float(r["result_7d"]) for r in closed if (r.get("conviction") or 0) >= 75]
    wr, n = _winrate(high)
    if n >= min_sample and wr >= 0.65:
        add(f"Conviction >= 75/100 : {wr*100:.0f}% de réussite ({n} signaux)", "conviction", wr, n)

    # 2) Fondamental solide (>=70) vs fragile (<45)
    solid = [float(r["result_7d"]) for r in closed if (r.get("fundamental_score") or 0) >= 70]
    wr, n = _winrate(solid)
    if n >= min_sample and wr >= 0.65:
        add(f"Fondamental solide (>=70) : {wr*100:.0f}% de réussite ({n} signaux)", "fondamental", wr, n)
    fragile = [float(r["result_7d"]) for r in closed
               if r.get("fundamental_score") is not None and r["fundamental_score"] < 45]
    wr, n = _winrate(fragile)
    if n >= min_sample and wr <= 0.40:
        add(f"Méfiance : fondamental fragile (<45) échoue souvent "
            f"({(1-wr)*100:.0f}% de pertes, {n} signaux)", "fondamental", 1 - wr, n)

    # 3) Sentiment actualités positif vs négatif
    pos = [float(r["result_7d"]) for r in closed if (r.get("news_sentiment") or 0) > 0.1]
    wr, n = _winrate(pos)
    if n >= min_sample and wr >= 0.65:
        add(f"Actualités positives : {wr*100:.0f}% de réussite ({n} signaux)", "sentiment", wr, n)

    # 4) Divergence : sous-performe-t-elle ?
    div = [float(r["result_7d"]) for r in closed if r.get("divergence")]
    wr, n = _winrate(div)
    if n >= min_sample and wr <= 0.40:
        add(f"Méfiance : les divergences échouent souvent "
            f"({(1-wr)*100:.0f}% de pertes, {n} signaux)", "divergence", 1 - wr, n)

    logger.info("Attribution : %s règles déduites des pilotes de conviction", len(created))
    return created


def run_weekly_learning() -> dict:
    """Hebdo (lundi) : règles apprises + attribution des pilotes + recalcul des poids."""
    rules = generate_learned_rules()
    driver_rules = analyze_signal_drivers()
    new_weights = weights.recalculate_ai_weights()
    return {"rules_created": len(rules) + len(driver_rules), "weights": new_weights}
