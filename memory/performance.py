"""
memory/performance.py — Performance par ticker, règles apprises, blacklist.

- ticker_performance : agrégats par ticker (taux de réussite, gains/pertes)
- learned_rules : règles découvertes par le système (jamais supprimées)
- blacklist : un ticker blacklisté n'est jamais réintégré automatiquement
"""

import logging

from . import database

logger = logging.getLogger("performance")

TICKER_PERF = "ticker_performance"
RULES = "learned_rules"


# ─────────────────────────────────────────────────────────────
# PERFORMANCE PAR TICKER
# ─────────────────────────────────────────────────────────────

def get_ticker_performance(ticker: str) -> dict:
    try:
        res = database.table(TICKER_PERF).select("*").eq("ticker", ticker).limit(1).execute()
        return res.data[0] if res.data else {}
    except Exception as e:  # noqa: BLE001
        logger.error("get_ticker_performance échec : %s", e)
        return {}


def upsert_ticker_performance(ticker: str, stats: dict) -> None:
    """Met à jour (ou crée) la ligne de performance d'un ticker."""
    try:
        existing = get_ticker_performance(ticker)
        if existing:
            database.table(TICKER_PERF).update(stats).eq("ticker", ticker).execute()
        else:
            database.table(TICKER_PERF).insert({"ticker": ticker, **stats}).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("upsert_ticker_performance échec : %s", e)


def get_agent_ticker_performance(agent_name: str, ticker: str) -> dict:
    """Performance d'un agent SUR un ticker précis (pour le brief)."""
    perf = {"total": 0, "win_rate": 0.0, "summary": "aucun historique"}
    try:
        votes = (database.table("ai_votes")
                 .select("verdict, trading_signals!inner(ticker, result_7d)")
                 .eq("agent_name", agent_name)
                 .eq("verdict", "ACHETER")
                 .eq("trading_signals.ticker", ticker)
                 .execute()).data or []
        results = [float(v["trading_signals"]["result_7d"]) for v in votes
                   if v.get("trading_signals") and v["trading_signals"].get("result_7d") is not None]
        perf["total"] = len(results)
        if results:
            correct = sum(1 for r in results if r > 0)
            perf["win_rate"] = correct / len(results)
            perf["summary"] = f"{correct}/{len(results)} gagnants"
    except Exception as e:  # noqa: BLE001
        logger.warning("get_agent_ticker_performance : %s", e)
    return perf


# ─────────────────────────────────────────────────────────────
# BLACKLIST
# ─────────────────────────────────────────────────────────────

def get_blacklisted_tickers() -> set[str]:
    try:
        res = database.table(TICKER_PERF).select("ticker").eq("blacklisted", True).execute()
        return {r["ticker"] for r in (res.data or [])}
    except Exception as e:  # noqa: BLE001
        logger.error("get_blacklisted_tickers échec : %s", e)
        return set()


def blacklist_ticker(ticker: str, reason: str) -> None:
    """Blackliste un ticker (décision manuelle de Rémy — pas de réintégration auto)."""
    upsert_ticker_performance(ticker, {"blacklisted": True, "blacklist_reason": reason})
    logger.info("Ticker blacklisté : %s (%s)", ticker, reason)


# ─────────────────────────────────────────────────────────────
# RÈGLES APPRISES
# ─────────────────────────────────────────────────────────────

def get_relevant_rules(ticker: str | None = None, agent: str | None = None,
                       min_reliability: float = 0.65) -> list[dict]:
    """Règles actives et suffisamment fiables (pour le brief des IA)."""
    try:
        res = (database.table(RULES).select("*")
               .eq("active", True)
               .gte("reliability", min_reliability)
               .order("reliability", desc=True)
               .limit(15).execute())
        return res.data or []
    except Exception as e:  # noqa: BLE001
        logger.error("get_relevant_rules échec : %s", e)
        return []


def add_learned_rule(description: str, rule_type: str, reliability: float,
                     sample_size: int) -> dict | None:
    try:
        res = database.table(RULES).insert({
            "rule_description": description,
            "rule_type": rule_type,
            "reliability": round(reliability, 3),
            "sample_size": sample_size,
            "active": True,
        }).execute()
        logger.info("Règle apprise ajoutée : %s", description[:60])
        return res.data[0] if res.data else None
    except Exception as e:  # noqa: BLE001
        logger.error("add_learned_rule échec : %s", e)
        return None
