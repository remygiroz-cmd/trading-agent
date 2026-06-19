"""
portfolio.py — Gestionnaire de portefeuille (contrôle de l'exposition globale).

Le bot raisonnait signal par signal : il pouvait alerter sur 5 valeurs tech le
même jour et te faire tout miser sur un seul thème. Cette couche regarde le
PORTEFEUILLE dans son ensemble avant d'autoriser une nouvelle alerte :
  - nombre max de positions ouvertes,
  - nombre max de positions par secteur,
  - exposition totale max (% du capital engagé),
  - exposition max par secteur.

Si une nouvelle position dépasse une limite, on la BLOQUE (pas d'alerte) ou on
RÉDUIT sa taille pour rester dans les clous.

La logique de décision (check_new_position) est pure et testable. La lecture des
positions ouvertes vient de la base (signaux paper non clôturés).
"""

import logging

import config

logger = logging.getLogger("portfolio")


def get_open_positions() -> list[dict]:
    """Positions paper actuellement ouvertes (non clôturées), avec secteur et taille."""
    try:
        from memory import database
        rows = (database.table("trading_signals")
                .select("ticker, sector, suggested_position_pct, closed, is_paper")
                .eq("is_paper", True)
                .execute()).data or []
    except Exception as e:  # noqa: BLE001
        logger.warning("get_open_positions KO : %s", e)
        return []
    return [r for r in rows if not r.get("closed")]


def _exposure(positions: list[dict]) -> tuple[float, dict]:
    """Exposition totale (%) et par secteur à partir des positions ouvertes."""
    total = 0.0
    by_sector: dict[str, float] = {}
    for p in positions:
        pct = float(p.get("suggested_position_pct") or 0)
        total += pct
        sec = p.get("sector") or "n/d"
        by_sector[sec] = by_sector.get(sec, 0.0) + pct
    return total, by_sector


def check_new_position(sector: str | None, pos_pct: float,
                       positions: list[dict]) -> dict:
    """
    Décide si une nouvelle position est acceptée, réduite ou bloquée.

    Retourne {allowed, pos_pct (éventuellement réduit), reason}.
    """
    cfg = config.PORTFOLIO
    if not cfg.get("enabled"):
        return {"allowed": True, "pos_pct": pos_pct, "reason": ""}

    sector = sector or "n/d"
    n = len(positions)
    sector_count = sum(1 for p in positions if (p.get("sector") or "n/d") == sector)
    total_exp, by_sector = _exposure(positions)
    sector_exp = by_sector.get(sector, 0.0)

    # 1) Nombre de positions
    if n >= cfg["max_concurrent"]:
        return {"allowed": False, "pos_pct": 0.0,
                "reason": f"{n} positions déjà ouvertes (max {cfg['max_concurrent']})"}
    # 2) Concentration sectorielle (nombre)
    if sector_count >= cfg["max_per_sector"]:
        return {"allowed": False, "pos_pct": 0.0,
                "reason": f"déjà {sector_count} positions sur {sector} (max {cfg['max_per_sector']})"}

    # 3) Exposition totale (on réduit si besoin)
    room_total = cfg["max_total_exposure_pct"] - total_exp
    room_sector = cfg["max_sector_exposure_pct"] - sector_exp
    room = min(room_total, room_sector)
    if room <= 0.5:
        which = "totale" if room_total <= room_sector else f"secteur {sector}"
        return {"allowed": False, "pos_pct": 0.0,
                "reason": f"exposition {which} au maximum"}

    if pos_pct > room:
        return {"allowed": True, "pos_pct": round(room, 1),
                "reason": f"taille réduite à {room:.0f}% (plafond d'exposition)"}

    return {"allowed": True, "pos_pct": pos_pct, "reason": ""}


def evaluate(sector: str | None, pos_pct: float) -> dict:
    """Comme check_new_position mais lit les positions ouvertes en base."""
    return check_new_position(sector, pos_pct, get_open_positions())
