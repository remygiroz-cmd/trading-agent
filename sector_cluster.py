"""
sector_cluster.py — Clustering sectoriel des alertes.

Quand plusieurs signaux tombent dans le MÊME secteur le même jour, c'est rarement
un hasard : soit le secteur décolle (plusieurs confirmations indépendantes = signal
fort), soit c'est du bruit sectoriel. Le bot le note pour t'aider à juger.

Deux usages :
  - en direct pendant un scan : annoter une alerte ("3e signal Techno aujourd'hui") ;
  - dans le bilan du soir : répartition des signaux par secteur.

Dégradation gracieuse : si la colonne `sector` n'existe pas encore (migration 006
non passée) ou si Supabase est indisponible, on retombe sur un comptage neutre.
"""

import logging
import datetime as dt

logger = logging.getLogger("sector_cluster")

# Seuils de cluster (nombre de signaux du même secteur dans la journée)
CLUSTER_MIN = 2      # à partir de 2 : confirmation
HOT_MIN = 3          # à partir de 3 : secteur qui décolle


def todays_counts(date_iso: str | None = None) -> dict:
    """Nombre de signaux par secteur aujourd'hui (depuis la base)."""
    today = date_iso or dt.date.today().isoformat()
    try:
        from memory import database
        rows = (database.table("trading_signals").select("sector")
                .gte("created_at", f"{today}T00:00:00")
                .lte("created_at", f"{today}T23:59:59")
                .execute()).data or []
    except Exception as e:  # noqa: BLE001
        logger.debug("todays_counts indisponible : %s", str(e)[:80])
        return {}
    return _tally(r.get("sector") for r in rows)


def _tally(sectors) -> dict:
    counts: dict[str, int] = {}
    for s in sectors:
        if s and s != "n/d":
            counts[s] = counts.get(s, 0) + 1
    return counts


def cluster_note(count: int, sector: str | None = None) -> str:
    """Annotation d'alerte selon le nombre de signaux du secteur aujourd'hui."""
    if not sector or sector == "n/d":
        return ""
    if count >= HOT_MIN:
        return f"🔥 Secteur {sector} qui décolle — {count}e signal aujourd'hui"
    if count >= CLUSTER_MIN:
        return f"➕ {count}e signal du secteur {sector} aujourd'hui (confirmation)"
    return ""


def breakdown_text(counts: dict) -> str:
    """Répartition lisible des signaux par secteur (pour le bilan)."""
    clustered = {s: n for s, n in counts.items() if n >= CLUSTER_MIN}
    if not clustered:
        return ""
    parts = sorted(clustered.items(), key=lambda x: -x[1])
    return "🧭 Secteurs actifs : " + ", ".join(f"{s} ×{n}" for s, n in parts)


def breakdown_from_signals(signals: list[dict]) -> str:
    """Répartition sectorielle à partir d'une liste de signaux (bilan du jour)."""
    return breakdown_text(_tally(s.get("sector") for s in signals))
