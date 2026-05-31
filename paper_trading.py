"""
paper_trading.py — Paper trading des 30 premiers jours.

Chaque alerte crée une position virtuelle (le signal en base avec is_paper=True).
Le capital de référence et la taille de position sont définis dans config.
À J+30, on pourra produire un bilan Go/No-Go (Session 8).

L'état (date de démarrage) est persisté localement pour survivre aux redémarrages.
"""

import os
import json
import logging
import datetime as dt

import config

logger = logging.getLogger("paper")

STATE_PATH = "data_cache/paper_state.json"


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_state(state: dict) -> None:
    os.makedirs("data_cache", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def ensure_started(today: dt.date | None = None) -> str:
    """Initialise la date de démarrage du paper trading si nécessaire."""
    state = _load_state()
    if not state.get("start_date"):
        today = today or dt.date.today()
        state["start_date"] = today.isoformat()
        _save_state(state)
        logger.info("Paper trading démarré le %s", state["start_date"])
    return state["start_date"]


def is_paper_active(today: dt.date | None = None) -> bool:
    """
    True si on est encore dans la fenêtre paper trading (30 jours) ET activé.
    Rémy peut désactiver manuellement via config.PAPER_TRADING_CONFIG['enabled'].
    """
    if not config.PAPER_TRADING_CONFIG["enabled"]:
        return False
    start = ensure_started(today)
    today = today or dt.date.today()
    start_date = dt.date.fromisoformat(start)
    return (today - start_date).days < 30


def days_elapsed(today: dt.date | None = None) -> int:
    start = ensure_started(today)
    today = today or dt.date.today()
    return (today - dt.date.fromisoformat(start)).days


def position_size_eur(virtual_capital: float | None = None) -> float:
    """Taille de position virtuelle en euros (max_position_pct du capital)."""
    cap = virtual_capital or config.PAPER_TRADING_CONFIG["virtual_capital"]
    return round(cap * config.PAPER_TRADING_CONFIG["max_position_pct"], 2)
