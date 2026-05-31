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
    closed = bool(sig.get("closed"))

    if closed:
        statut = "clôturé"
        pct = sig.get("realized_pct", "")
        pnl = sig.get("realized_pnl_eur", "")
    else:
        statut = "en cours"
        # résultat latent connu (J+7 > J+3 > J+1)
        pct = next((sig[f] for f in ("result_7d", "result_3d", "result_1d")
                    if sig.get(f) is not None), "")
        pnl = round(stake * float(pct), 2) if pct != "" else ""

    pct_aff = round(float(pct) * 100, 2) if pct != "" else ""

    return {
        "id": sig.get("id", ""),
        "date_entree": (sig.get("created_at") or "")[:16].replace("T", " "),
        "ticker": sig.get("ticker", ""),
        "figure": sig.get("pattern_name", ""),
        "score": sig.get("final_score", ""),
        "prix_entree": sig.get("entry_price", ""),
        "objectif": sig.get("target_price", ""),
        "stop": sig.get("stop_loss", ""),
        "horizon_j": sig.get("horizon_days", ""),
        "mise_eur": stake,
        "statut": statut,
        "raison_sortie": sig.get("exit_reason", ""),
        "prix_sortie": sig.get("exit_price", ""),
        "date_sortie": (sig.get("exit_date") or "")[:16].replace("T", " "),
        "jours_detenus": sig.get("hold_days", ""),
        "resultat_pct": pct_aff,
        "plus_value_eur": pnl,
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
