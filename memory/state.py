"""
memory/state.py — État persistant clé-valeur (table agent_state dans Supabase).

Indispensable pour le déploiement cloud : sur GitHub Actions, le système de
fichiers est éphémère (rien ne survit entre deux exécutions). On stocke donc
dans Supabase : watchlist dynamique, état paper trading, mode d'alerte, offset
Telegram, marqueurs anti-doublon des scans.

Repli local (fichier) si Supabase indisponible, pour le dev hors-ligne.
"""

import os
import json
import logging

logger = logging.getLogger("state")

TABLE = "agent_state"
LOCAL_DIR = "data_cache/state"


def get_state(key: str, default=None):
    try:
        from . import database
        res = database.table(TABLE).select("value").eq("key", key).limit(1).execute()
        if res.data:
            return res.data[0]["value"]
        return default
    except Exception as e:  # noqa: BLE001
        logger.warning("get_state(%s) DB KO (%s) — repli fichier", key, str(e)[:60])
        return _local_get(key, default)


def set_state(key: str, value) -> None:
    try:
        from . import database
        existing = database.table(TABLE).select("key").eq("key", key).limit(1).execute()
        if existing.data:
            database.table(TABLE).update({"value": value}).eq("key", key).execute()
        else:
            database.table(TABLE).insert({"key": key, "value": value}).execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("set_state(%s) DB KO (%s) — repli fichier", key, str(e)[:60])
        _local_set(key, value)


# — repli local —
def _local_path(key: str) -> str:
    return os.path.join(LOCAL_DIR, f"{key}.json")


def _local_get(key: str, default=None):
    p = _local_path(key)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return default
    return default


def _local_set(key: str, value) -> None:
    os.makedirs(LOCAL_DIR, exist_ok=True)
    with open(_local_path(key), "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
