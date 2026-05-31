"""
agents/deepseek_agent.py — Agent technique (DeepSeek).

Rôle : analyse technique pure du setup (mât, correction, volume, RSI, MACD).
"""

import logging

from . import base, prompts

logger = logging.getLogger("deepseek")
NAME = "deepseek"


def analyze_t1(ctx: dict) -> dict:
    """Tour 1 — analyse technique indépendante."""
    user = prompts.fill(prompts.DEEPSEEK_PROMPT_T1, ctx)
    text = base.call_openai_compatible(NAME, prompts.SYSTEM[NAME], user)
    return base.parse_json_response(text)


def revise_t2(ctx: dict) -> dict:
    """Tour 2 — relecture croisée et révision éventuelle."""
    user = prompts.fill(prompts.DEBATE_ROUND2_PROMPT, ctx)
    text = base.call_openai_compatible(NAME, prompts.SYSTEM[NAME], user)
    return base.parse_json_response(text)
