"""
memory/signals.py — Enregistrement et suivi des signaux + votes des IA.

Aucune suppression : on insère et on met à jour uniquement (règle métier 8).
"""

import logging

from . import database

logger = logging.getLogger("signals")

SIGNALS = "trading_signals"
VOTES = "ai_votes"

# Colonnes garanties par la migration 001 (toujours présentes en base).
# Les colonnes analytiques (conviction, divergence, news_sentiment, etc.) sont
# best-effort : si la migration 005 n'a pas encore été passée, on retombe sur
# ce socle pour ne jamais perdre un signal.
CORE_COLUMNS = {
    "ticker", "pattern_name", "timeframe", "entry_price", "target_price",
    "stop_loss", "setup_score", "final_score", "buy_votes", "horizon_days", "is_paper",
}


# ─────────────────────────────────────────────────────────────
# CRÉATION
# ─────────────────────────────────────────────────────────────

def insert_signal(signal: dict) -> dict | None:
    """
    Insère un signal et retourne la ligne créée (avec son id).

    Champs attendus (les manquants sont laissés à NULL) :
      ticker, pattern_name, timeframe, entry_price, target_price, stop_loss,
      setup_score, final_score, buy_votes, horizon_days, is_paper
    """
    try:
        res = database.table(SIGNALS).insert(signal).execute()
        row = res.data[0] if res.data else None
        if row:
            logger.info("Signal inséré : %s %s (id=%s)", row["ticker"], row["pattern_name"], row["id"])
        return row
    except Exception as e:  # noqa: BLE001
        # Repli : colonnes analytiques peut-être absentes (migration 005 non passée).
        # On réessaie avec le socle garanti pour ne jamais perdre le signal.
        core = {k: v for k, v in signal.items() if k in CORE_COLUMNS}
        if len(core) < len(signal):
            try:
                res = database.table(SIGNALS).insert(core).execute()
                row = res.data[0] if res.data else None
                if row:
                    logger.warning("Signal inséré sans colonnes analytiques "
                                   "(migration 005 à passer) : %s", row["ticker"])
                return row
            except Exception as e2:  # noqa: BLE001
                logger.error("insert_signal repli échec : %s", e2)
                return None
        logger.error("insert_signal échec : %s", e)
        return None


def insert_vote(signal_id: str, agent_name: str, tour: int, vote: dict,
                weight_at_time: float | None = None) -> dict | None:
    """
    Enregistre un vote d'IA pour un signal donné.

    `vote` : le JSON brut renvoyé par l'IA. On en extrait verdict/score et on
    stocke l'intégralité dans raw_response.
    """
    payload = {
        "signal_id": signal_id,
        "agent_name": agent_name,
        "tour": tour,
        "verdict": vote.get("verdict", "IGNORER"),
        "score": int(vote.get("score", 0) or 0),
        "position_changed": bool(vote.get("position_changed", False)),
        "raw_response": vote,
        "weight_at_time": weight_at_time,
    }
    try:
        res = database.table(VOTES).insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:  # noqa: BLE001
        logger.error("insert_vote échec (%s) : %s", agent_name, e)
        return None


# ─────────────────────────────────────────────────────────────
# LECTURE
# ─────────────────────────────────────────────────────────────

def get_open_signals(max_age_days: int = 8) -> list[dict]:
    """
    Récupère les signaux encore « ouverts » : résultat J+7 non rempli,
    ni stop ni objectif atteint, et créés il y a <= max_age_days.
    """
    try:
        res = (database.table(SIGNALS)
               .select("*")
               .is_("result_7d", "null")
               .eq("target_reached", False)
               .eq("stop_reached", False)
               .order("created_at", desc=True)
               .execute())
        return res.data or []
    except Exception as e:  # noqa: BLE001
        logger.error("get_open_signals échec : %s", e)
        return []


def get_today_signals(date_iso: str | None = None) -> list[dict]:
    """Signaux créés aujourd'hui (ou à une date donnée AAAA-MM-JJ)."""
    try:
        q = database.table(SIGNALS).select("*")
        if date_iso:
            q = q.gte("created_at", f"{date_iso}T00:00:00").lte("created_at", f"{date_iso}T23:59:59")
        return q.order("created_at", desc=True).execute().data or []
    except Exception as e:  # noqa: BLE001
        logger.error("get_today_signals échec : %s", e)
        return []


def get_signal(signal_id: str) -> dict | None:
    try:
        res = database.table(SIGNALS).select("*").eq("id", signal_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:  # noqa: BLE001
        logger.error("get_signal échec : %s", e)
        return None


def get_ticker_history(ticker: str, limit: int = 10) -> list[dict]:
    """Historique des signaux passés sur un ticker (pour le brief des IA)."""
    try:
        res = (database.table(SIGNALS).select("*")
               .eq("ticker", ticker)
               .order("created_at", desc=True)
               .limit(limit).execute())
        return res.data or []
    except Exception as e:  # noqa: BLE001
        logger.error("get_ticker_history échec : %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# MISE À JOUR DES RÉSULTATS
# ─────────────────────────────────────────────────────────────

def update_signal_result(signal_id: str, days_elapsed: int, result: float) -> None:
    """Met à jour result_1d / result_3d / result_7d selon le nombre de jours écoulés."""
    field = None
    if days_elapsed >= 7:
        field = "result_7d"
    elif days_elapsed >= 3:
        field = "result_3d"
    elif days_elapsed >= 1:
        field = "result_1d"
    if not field:
        return
    try:
        database.table(SIGNALS).update({field: round(result, 4)}).eq("id", signal_id).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("update_signal_result échec : %s", e)


def mark_target_reached(signal_id: str) -> None:
    _safe_update(signal_id, {"target_reached": True})


def mark_stop_reached(signal_id: str) -> None:
    _safe_update(signal_id, {"stop_reached": True})


def set_user_action(signal_id: str, action: str, entry_price: float | None = None) -> None:
    """Enregistre l'action de Rémy depuis les boutons Telegram."""
    payload = {"user_action": action}
    if entry_price is not None:
        payload["user_entry_price"] = entry_price
    _safe_update(signal_id, payload)


def _safe_update(signal_id: str, payload: dict) -> None:
    try:
        database.table(SIGNALS).update(payload).eq("id", signal_id).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("update %s échec : %s", payload, e)
