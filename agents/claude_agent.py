"""
agents/claude_agent.py — Agent macro & fondamental (Claude / Anthropic).

Rôle : avocat du diable. Cherche pourquoi un setup techniquement valide
pourrait échouer (risques macro, fondamentaux, calendrier des résultats).
Fournit aussi la taille de position max conseillée.
"""

import logging

from . import base, prompts

logger = logging.getLogger("claude")
NAME = "claude"


def analyze_t1(ctx: dict) -> dict:
    """Tour 1 — analyse macro/fondamentale prudente."""
    user = prompts.fill(prompts.CLAUDE_PROMPT_T1, ctx)
    text = base.call_claude(prompts.SYSTEM[NAME], user)
    return base.parse_json_response(text)


def revise_t2(ctx: dict) -> dict:
    """Tour 2 — relecture croisée et révision éventuelle."""
    user = prompts.fill(prompts.DEBATE_ROUND2_PROMPT, ctx)
    text = base.call_claude(prompts.SYSTEM[NAME], user)
    return base.parse_json_response(text)
