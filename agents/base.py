"""
agents/base.py — Socle commun aux trois agents IA.

Appels HTTP directs (requests) — pas de SDK, pour rester léger et compatible
serverless. Deux familles d'API :
  - OpenAI-compatible (DeepSeek, Grok/xAI) : POST /chat/completions
  - Anthropic (Claude) : POST /v1/messages

Parsing JSON robuste : les IA renvoient parfois le JSON entouré de texte ou de
balises markdown ```json — on extrait proprement.
"""

import json
import re
import time
import logging

import requests

import config

logger = logging.getLogger("agents")


def _fallback(reason: str) -> dict:
    """Réponse de repli en cas d'échec d'une IA (le débat continue sans planter)."""
    return {
        "verdict": "IGNORER",
        "score": 0,
        "raison_principale": f"Indisponible : {reason}",
        "_error": True,
    }


def parse_json_response(text: str) -> dict:
    """Extrait un objet JSON depuis la réponse brute d'une IA."""
    if not text:
        return _fallback("réponse vide")

    # Retirer les fences markdown ```json ... ```
    cleaned = re.sub(r"```(?:json)?", "", text).strip("` \n")

    # Tentative directe
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Extraire le premier bloc {...} équilibré
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("JSON non parsable : %s", text[:200])
    return _fallback("JSON illisible")


# ─────────────────────────────────────────────────────────────
# APPELS API
# ─────────────────────────────────────────────────────────────

def call_openai_compatible(agent: str, system: str, user: str,
                           extra_payload: dict | None = None) -> str:
    """Appel pour DeepSeek / Grok (format OpenAI chat.completions)."""
    cfg = config.AI_CONFIG[agent]
    if not cfg["api_key"]:
        raise RuntimeError(f"Clé API {agent} manquante")

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.AI_REQUEST["temperature"],
        "max_tokens": config.AI_REQUEST["max_tokens"],
    }
    if extra_payload:
        payload.update(extra_payload)

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    resp = _post_with_retry(cfg["url"], headers, payload)
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_claude(system: str, user: str) -> str:
    """Appel Anthropic Messages API."""
    cfg = config.AI_CONFIG["claude"]
    if not cfg["api_key"]:
        raise RuntimeError("Clé API claude manquante")

    payload = {
        "model": cfg["model"],
        "max_tokens": config.AI_REQUEST["max_tokens"],
        "temperature": config.AI_REQUEST["temperature"],
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": cfg["api_key"],
        "anthropic-version": cfg["anthropic_version"],
        "Content-Type": "application/json",
    }

    resp = _post_with_retry(cfg["url"], headers, payload)
    data = resp.json()
    # concaténer les blocs de texte
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts)


def _post_with_retry(url: str, headers: dict, payload: dict) -> requests.Response:
    last = None
    for attempt in range(config.AI_REQUEST["max_retries"] + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload,
                                 timeout=config.AI_REQUEST["timeout"])
            if resp.status_code < 400:
                return resp
            last = f"HTTP {resp.status_code}: {resp.text[:200]}"
            # 4xx (hors 429) inutile de réessayer
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                break
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "échec requête IA")


def safe_analyze(fn, *args, **kwargs) -> dict:
    """Exécute une analyse d'agent en capturant toute erreur -> fallback dict."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error("Analyse échouée : %s", e)
        return _fallback(str(e)[:80])
