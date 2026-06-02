"""
agents/debate.py — Orchestration du débat multi-agents en 3 tours.

TOUR 1 : analyses indépendantes (DeepSeek, Grok, Claude sans se voir)
TOUR 2 : lecture croisée + révision possible
TOUR 3 : vote final pondéré -> décision d'alerte

Le vote final suit SPECS 3.6 :
  - score final /100
  - alerte si final_score >= 75 ET au moins 2 votes ACHETER
"""

import json
import logging

import config
from . import base, prompts
from . import deepseek_agent, grok_agent, claude_agent

logger = logging.getLogger("debate")

AGENTS = {
    "deepseek": deepseek_agent,
    "grok": grok_agent,
    "claude": claude_agent,
}

VERDICT_NUMERIC = {"ACHETER": None, "ATTENDRE": 5, "IGNORER": 0}  # ACHETER -> score réel


# ─────────────────────────────────────────────────────────────
# TOUR 3 — VOTE FINAL PONDÉRÉ
# ─────────────────────────────────────────────────────────────

def calculate_final_score(votes: dict, weights: dict,
                          min_final_score: float | None = None,
                          min_buy_votes: int | None = None) -> dict:
    """
    votes : {agent: {"verdict":..., "score":...}}
    weights : {agent: poids}  (somme ~1)
    min_final_score / min_buy_votes : seuils d'alerte (par défaut config ;
      surchargés selon le régime de marché).
    """
    if min_final_score is None:
        min_final_score = config.ALERT_RULES["min_final_score"]
    if min_buy_votes is None:
        min_buy_votes = config.ALERT_RULES["min_buy_votes"]

    weighted = 0.0
    for agent, vote in votes.items():
        verdict = vote.get("verdict", "IGNORER")
        if verdict == "ACHETER":
            numeric = float(vote.get("score", 0) or 0)
        else:
            numeric = VERDICT_NUMERIC.get(verdict, 0)
        weighted += numeric * weights.get(agent, 0)

    final_score = round(weighted * 10, 1)  # /100
    buy_votes = sum(1 for v in votes.values() if v.get("verdict") == "ACHETER")

    return {
        "final_score": final_score,
        "buy_votes": buy_votes,
        "send_alert": final_score >= min_final_score and buy_votes >= min_buy_votes,
        "min_final_score": min_final_score,
    }


# ─────────────────────────────────────────────────────────────
# DÉBAT COMPLET
# ─────────────────────────────────────────────────────────────

def _summarize(vote: dict) -> str:
    """Résumé court d'un vote pour la lecture croisée (Tour 2)."""
    keys = ["verdict", "score", "raison_principale", "risque_principal",
            "risque_macro", "catalyseur_positif", "risque_detecte"]
    short = {k: vote[k] for k in keys if k in vote and vote[k] not in (None, "n/d")}
    return json.dumps(short, ensure_ascii=False)


def run_debate(ctx: dict, weights: dict | None = None, do_round2: bool = True,
               min_final_score: float | None = None, min_buy_votes: int | None = None) -> dict:
    """
    Lance le débat complet sur un setup (contexte `ctx`).

    Retourne :
      {
        "round1": {agent: vote},
        "round2": {agent: vote} | None,
        "final_votes": {agent: vote},   # tour utilisé pour le vote final
        "result": {final_score, buy_votes, send_alert},
        "weights": weights,
      }
    """
    if weights is None:
        try:
            from memory import weights as weights_mod
            weights = weights_mod.get_current_weights()
        except Exception:  # noqa: BLE001
            weights = dict(config.INITIAL_WEIGHTS)

    # ── TOUR 1 : analyses indépendantes ──
    round1 = {}
    for name, mod in AGENTS.items():
        round1[name] = base.safe_analyze(mod.analyze_t1, ctx)
        logger.info("[T1] %s : %s %s/10", name,
                    round1[name].get("verdict"), round1[name].get("score"))

    final_votes = round1
    round2 = None

    # ── TOUR 2 : lecture croisée ──
    if do_round2:
        round2 = {}
        names = list(AGENTS.keys())
        for name, mod in AGENTS.items():
            others = [o for o in names if o != name]
            r2_ctx = {
                "agent_name": name,
                "own_analysis": _summarize(round1[name]),
                "other_agent_1_name": others[0],
                "other_analysis_1": _summarize(round1[others[0]]),
                "other_agent_2_name": others[1],
                "other_analysis_2": _summarize(round1[others[1]]),
            }
            revised = base.safe_analyze(mod.revise_t2, r2_ctx)
            # si l'IA n'a pas renvoyé de verdict exploitable, garder le Tour 1
            if revised.get("_error") or "verdict" not in revised:
                revised = round1[name]
            round2[name] = revised
            logger.info("[T2] %s : %s %s/10 (changé=%s)", name,
                        revised.get("verdict"), revised.get("score"),
                        revised.get("position_changed"))
        final_votes = round2

    # ── TOUR 3 : vote final pondéré ──
    result = calculate_final_score(final_votes, weights, min_final_score, min_buy_votes)
    logger.info("[T3] score final %.1f/100, %s votes ACHETER -> alerte=%s",
                result["final_score"], result["buy_votes"], result["send_alert"])

    return {
        "round1": round1,
        "round2": round2,
        "final_votes": final_votes,
        "result": result,
        "weights": weights,
    }
