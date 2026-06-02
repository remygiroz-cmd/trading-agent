"""
memory/weights.py — Gestion des poids des trois IA.

Les poids évoluent selon les performances réelles. Bornes : 0.15 à 0.55.
La somme est normalisée à 1. Tout changement est historisé (jamais écrasé).
"""

import logging

import config
from . import database

logger = logging.getLogger("weights")

WEIGHTS = "ai_weights"
AGENTS = ["deepseek", "grok", "claude"]


def get_current_weights() -> dict:
    """
    Retourne les poids les plus récents par agent. Si aucun historique,
    renvoie les poids initiaux et les persiste.
    """
    weights = {}
    try:
        for agent in AGENTS:
            res = (database.table(WEIGHTS).select("weight")
                   .eq("agent_name", agent)
                   .order("updated_at", desc=True)
                   .limit(1).execute())
            if res.data:
                weights[agent] = float(res.data[0]["weight"])
    except Exception as e:  # noqa: BLE001
        logger.error("get_current_weights échec : %s", e)

    if len(weights) < len(AGENTS):
        # Initialisation
        weights = dict(config.INITIAL_WEIGHTS)
        for agent, w in weights.items():
            save_weight(agent, w, reason="initialisation")
    return weights


def save_weight(agent_name: str, weight: float, win_rate: float | None = None,
                total: int | None = None, correct: int | None = None,
                reason: str = "") -> None:
    """Insère une nouvelle ligne de poids (historisation, pas d'écrasement)."""
    weight = max(config.WEIGHT_MIN, min(config.WEIGHT_MAX, weight))
    try:
        database.table(WEIGHTS).insert({
            "agent_name": agent_name,
            "weight": round(weight, 3),
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "total_signals": total,
            "correct_signals": correct,
            "reason": reason[:200] if reason else None,
        }).execute()
        logger.info("Poids %s -> %.3f (%s)", agent_name, weight, reason)
    except Exception as e:  # noqa: BLE001
        logger.error("save_weight échec : %s", e)


def normalize_weights() -> dict:
    """Re-normalise les derniers poids pour que leur somme = 1 (en respectant les bornes)."""
    weights = get_current_weights()
    total = sum(weights.values())
    if total <= 0:
        return weights
    normalized = {a: w / total for a, w in weights.items()}
    for agent, w in normalized.items():
        save_weight(agent, w, reason="normalisation")
    return normalized


def get_agent_performance(agent_name: str) -> dict:
    """
    Statistiques globales d'un agent (pour le brief envoyé aux IA).
    Calculé depuis les votes ACHETER et les résultats J+7 associés.
    """
    perf = {
        "total": 0, "win_rate": 0.0, "current_weight": config.INITIAL_WEIGHTS.get(agent_name, 0.33),
        "best_conditions": "n/d", "worst_conditions": "n/d",
    }
    try:
        weights = get_current_weights()
        perf["current_weight"] = weights.get(agent_name, perf["current_weight"])

        # Votes ACHETER de l'agent avec le signal joint
        votes = (database.table("ai_votes")
                 .select("verdict, signal_id, trading_signals(result_7d)")
                 .eq("agent_name", agent_name)
                 .eq("verdict", "ACHETER")
                 .execute()).data or []
        results = [v["trading_signals"]["result_7d"] for v in votes
                   if v.get("trading_signals") and v["trading_signals"].get("result_7d") is not None]
        perf["total"] = len(results)
        if results:
            correct = sum(1 for r in results if float(r) > 0)
            perf["win_rate"] = correct / len(results)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_agent_performance(%s) : %s", agent_name, e)
    return perf


def recalculate_ai_weights(min_votes: int = 5, limit: int = 30) -> dict:
    """
    Recalcule les poids selon le taux de réussite des 30 derniers votes ACHETER.
    Appelé chaque lundi. Borne 0.15-0.55 puis normalisation.
    """
    new_weights = {}
    for agent in AGENTS:
        try:
            votes = (database.table("ai_votes")
                     .select("verdict, trading_signals(result_7d)")
                     .eq("agent_name", agent)
                     .eq("verdict", "ACHETER")
                     .order("created_at", desc=True)
                     .limit(limit).execute()).data or []
            results = [float(v["trading_signals"]["result_7d"]) for v in votes
                       if v.get("trading_signals") and v["trading_signals"].get("result_7d") is not None]
            if len(results) < min_votes:
                continue
            win_rate = sum(1 for r in results if r > 0) / len(results)
            w = max(config.WEIGHT_MIN, min(config.WEIGHT_MAX, win_rate))
            save_weight(agent, w, win_rate=win_rate, total=len(results),
                        correct=sum(1 for r in results if r > 0),
                        reason=f"recalcul hebdo ({len(results)} votes)")
            new_weights[agent] = w
        except Exception as e:  # noqa: BLE001
            logger.error("recalculate %s échec : %s", agent, e)

    if new_weights:
        normalize_weights()
    return get_current_weights()


# ─────────────────────────────────────────────────────────────
# MÉTA-APPRENTISSAGE : POIDS PAR SEGMENT (taille de capi / secteur)
# ─────────────────────────────────────────────────────────────
# Idée : une IA n'est pas également douée partout. DeepSeek (technique) peut
# exceller sur les small caps nerveuses, Claude (macro) sur les grandes valeurs.
# On apprend donc un jeu de poids PAR SEGMENT, et on l'utilise quand on a assez
# de preuves ; sinon on retombe sur les poids globaux.
#
# Stockage : un seul blob JSON dans agent_state (clé 'segment_weights'), pas de
# nouvelle table. Forme :
#   {"sector": {"Technology": {"weights": {...}, "_sample": 24}, ...},
#    "cap":    {"small": {"weights": {...}, "_sample": 18}, ...}}

SEGMENT_STATE = "segment_weights"
SEGMENT_MIN_VOTES = 8     # par IA et par segment, avant de différencier


def compute_segment_weights(min_votes: int = SEGMENT_MIN_VOTES, limit: int = 300) -> dict:
    """
    Recalcule les poids par segment (secteur, taille de capi) depuis les votes
    ACHETER joints aux résultats J+7. Appelé chaque semaine. Stocke le blob et
    le retourne. Une IA sans assez de données sur un segment garde son poids global.
    """
    global_w = get_current_weights()
    # accumulateur : agg[dim][segment][agent] = {"wins":x, "n":y}
    agg: dict[str, dict[str, dict[str, dict]]] = {"sector": {}, "cap": {}}

    for agent in AGENTS:
        try:
            votes = (database.table("ai_votes")
                     .select("verdict, trading_signals(result_7d, sector, cap_bucket)")
                     .eq("agent_name", agent)
                     .eq("verdict", "ACHETER")
                     .order("created_at", desc=True)
                     .limit(limit).execute()).data or []
        except Exception as e:  # noqa: BLE001
            logger.warning("compute_segment_weights(%s) lecture KO : %s", agent, e)
            continue
        for v in votes:
            ts = v.get("trading_signals")
            if not ts or ts.get("result_7d") is None:
                continue
            won = 1 if float(ts["result_7d"]) > 0 else 0
            for dim, key in (("sector", ts.get("sector")), ("cap", ts.get("cap_bucket"))):
                if not key or key == "n/d":
                    continue
                a = agg[dim].setdefault(key, {}).setdefault(agent, {"wins": 0, "n": 0})
                a["n"] += 1
                a["wins"] += won

    # conversion en poids bornés + normalisés par segment
    blob: dict[str, dict] = {"sector": {}, "cap": {}}
    for dim, segs in agg.items():
        for seg, agents in segs.items():
            has_specific = any(st["n"] >= min_votes for st in agents.values())
            if not has_specific:
                continue  # pas assez de preuve sur ce segment
            seg_w = {}
            for agent in AGENTS:
                st = agents.get(agent)
                if st and st["n"] >= min_votes:
                    wr = st["wins"] / st["n"]
                    seg_w[agent] = max(config.WEIGHT_MIN, min(config.WEIGHT_MAX, wr))
                else:
                    seg_w[agent] = global_w.get(agent, config.INITIAL_WEIGHTS.get(agent, 0.33))
            total = sum(seg_w.values()) or 1.0
            seg_w = {a: round(w / total, 3) for a, w in seg_w.items()}
            sample = sum(st["n"] for st in agents.values())
            blob[dim][seg] = {"weights": seg_w, "_sample": sample}

    try:
        from . import state
        state.set_state(SEGMENT_STATE, blob)
    except Exception as e:  # noqa: BLE001
        logger.warning("Stockage segment_weights KO : %s", e)
    n_segments = len(blob["sector"]) + len(blob["cap"])
    logger.info("Poids par segment recalculés : %s segment(s) différenciés", n_segments)
    return blob


def get_weights_for(sector: str | None = None, cap_bucket: str | None = None,
                    global_weights: dict | None = None) -> tuple[dict, str]:
    """
    Poids à utiliser pour un signal donné. Choisit le segment le mieux étayé
    (secteur ou taille de capi) si on a appris dessus ; sinon poids globaux.
    Retourne (poids, source) où source explique le choix (pour la traçabilité).
    """
    fallback = global_weights or get_current_weights()
    try:
        from . import state
        blob = state.get_state(SEGMENT_STATE, default={}) or {}
    except Exception:  # noqa: BLE001
        return fallback, "global"

    candidates = []
    if sector and blob.get("sector", {}).get(sector):
        candidates.append((f"secteur:{sector}", blob["sector"][sector]))
    if cap_bucket and blob.get("cap", {}).get(cap_bucket):
        candidates.append((f"capi:{cap_bucket}", blob["cap"][cap_bucket]))
    if not candidates:
        return fallback, "global"

    # on retient le segment avec le plus de preuves (échantillon le plus grand)
    src, entry = max(candidates, key=lambda c: c[1].get("_sample", 0))
    weights = entry.get("weights") or fallback
    # sécurité : s'assurer que les 3 IA sont présentes
    for a in AGENTS:
        weights.setdefault(a, fallback.get(a, config.INITIAL_WEIGHTS.get(a, 0.33)))
    return weights, src
