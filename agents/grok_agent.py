"""
agents/grok_agent.py — Agent sentiment & actualités (Grok / xAI).

Rôle : sentiment sur X (Twitter) et actualités récentes. Utilise la recherche
en temps réel de Grok (Live Search) si disponible.
"""

import logging

import config
from . import base, prompts

logger = logging.getLogger("grok")
NAME = "grok"


def _extra_payload() -> dict:
    """Active Live Search côté xAI pour interroger X + le web (si supporté)."""
    if config.AI_CONFIG[NAME].get("live_search"):
        return {
            "search_parameters": {
                "mode": "auto",
                "sources": [{"type": "x"}, {"type": "news"}, {"type": "web"}],
                "max_search_results": 10,
            }
        }
    return {}


def analyze_t1(ctx: dict) -> dict:
    """Tour 1 — sentiment réseaux sociaux + actus."""
    user = prompts.fill(prompts.GROK_PROMPT_T1, ctx)
    try:
        text = base.call_openai_compatible(NAME, prompts.SYSTEM[NAME], user, _extra_payload())
    except Exception as e:  # noqa: BLE001
        # Si Live Search non supporté/erreur, on retombe sur un appel simple
        logger.warning("Grok live search KO (%s) — appel simple", str(e)[:80])
        text = base.call_openai_compatible(NAME, prompts.SYSTEM[NAME], user)
    return base.parse_json_response(text)


def revise_t2(ctx: dict) -> dict:
    """Tour 2 — relecture croisée et révision éventuelle."""
    user = prompts.fill(prompts.DEBATE_ROUND2_PROMPT, ctx)
    text = base.call_openai_compatible(NAME, prompts.SYSTEM[NAME], user)
    return base.parse_json_response(text)
