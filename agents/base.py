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


def _first_balanced_json(text: str) -> dict | None:
    """
    Extrait le PREMIER objet {...} réellement équilibré (comptage d'accolades,
    en ignorant celles à l'intérieur des chaînes). Un regex gourmand `\\{.*\\}`
    capturerait du premier '{' au DERNIER '}' : si l'IA écrit du texte ou un
    second objet après son JSON, le parse échouait et le vote était perdu.
    """
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break  # objet mal formé -> essayer à partir du '{' suivant
        start = text.find("{", start + 1)
    return None


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

    # Extraire le premier objet {...} équilibré
    obj = _first_balanced_json(cleaned)
    if obj is not None:
        return obj

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


def call_claude_vision(system: str, user: str, image_b64: str,
                       media_type: str = "image/jpeg") -> str:
    """Appel Claude avec une image (lecture de capture d'écran)."""
    cfg = config.AI_CONFIG["claude"]
    if not cfg["api_key"]:
        raise RuntimeError("Clé API claude manquante")
    payload = {
        "model": cfg["model"],
        "max_tokens": config.AI_REQUEST["max_tokens"],
        "system": system,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": user},
        ]}],
    }
    headers = {
        "x-api-key": cfg["api_key"],
        "anthropic-version": cfg["anthropic_version"],
        "Content-Type": "application/json",
    }
    resp = _post_with_retry(cfg["url"], headers, payload)
    data = resp.json()
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
