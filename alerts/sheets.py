"""
alerts/sheets.py — Export des signaux vers Google Sheets.

Approche sans clé Google complexe : on poste vers un webhook Apps Script
(URL dans GOOGLE_SHEETS_WEBHOOK_URL). Le script Google fait un "upsert" par
signal_id : il met à jour la ligne si elle existe, sinon il l'ajoute.

Le code du script Apps Script à coller côté Google est dans
docs/google_apps_script.gs.
"""

import logging

import requests

import config

logger = logging.getLogger("sheets")


def enabled() -> bool:
    return bool(config.GOOGLE_SHEETS_WEBHOOK_URL)


def _row_from_signal(sig: dict) -> dict:
    """Transforme un signal (base) en ligne pour la feuille."""
    stake = config.PAPER_TRADING_CONFIG["fixed_position_eur"]
    res7 = sig.get("result_7d")
    pnl = (stake * float(res7)) if res7 is not None else ""
    return {
        "id": sig.get("id", ""),
        "date": (sig.get("created_at") or "")[:16].replace("T", " "),
        "ticker": sig.get("ticker", ""),
        "figure": sig.get("pattern_name", ""),
        "score": sig.get("final_score", ""),
        "entree": sig.get("entry_price", ""),
        "objectif": sig.get("target_price", ""),
        "stop": sig.get("stop_loss", ""),
        "mise_eur": stake,
        "result_1d": sig.get("result_1d", ""),
        "result_3d": sig.get("result_3d", ""),
        "result_7d": res7 if res7 is not None else "",
        "pnl_eur": round(pnl, 2) if pnl != "" else "",
        "objectif_atteint": sig.get("target_reached", False),
        "stop_atteint": sig.get("stop_reached", False),
        "action_remy": sig.get("user_action", ""),
        "paper": sig.get("is_paper", True),
    }


def export_signal(sig: dict) -> bool:
    """Envoie (upsert) un signal vers Google Sheets. No-op si non configuré."""
    if not enabled():
        return False
    try:
        r = requests.post(config.GOOGLE_SHEETS_WEBHOOK_URL,
                          json={"action": "upsert", "row": _row_from_signal(sig)},
                          timeout=20)
        return r.status_code < 400
    except Exception as e:  # noqa: BLE001
        logger.warning("export_signal échec : %s", e)
        return False


def sync_signals(rows: list[dict]) -> int:
    """Synchronise plusieurs signaux (upsert) — utilisé après la MAJ quotidienne."""
    if not enabled():
        return 0
    n = 0
    for sig in rows:
        if export_signal(sig):
            n += 1
    logger.info("Google Sheets : %s lignes synchronisées", n)
    return n
