"""
alerts/telegram_bot.py — Envoi des alertes et messages Telegram.

Appels directs à l'API Bot Telegram (requests) — pas de SDK, cohérent avec le
reste du projet. Gère :
  - l'envoi de messages texte
  - l'alerte principale formatée + boutons inline (Pris / Ignoré / Surveille)
  - la lecture des updates (boutons cliqués, commandes /pause, /actif…)
"""

import logging

import requests

import config

logger = logging.getLogger("telegram")

API = "https://api.telegram.org/bot{token}/{method}"


def _url(method: str) -> str:
    return API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)


def _enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


# ─────────────────────────────────────────────────────────────
# ENVOI
# ─────────────────────────────────────────────────────────────

def send_message(text: str, chat_id: str | None = None,
                 buttons: list[list[tuple[str, str]]] | None = None,
                 parse_mode: str | None = None) -> dict | None:
    """
    Envoie un message. `buttons` : liste de rangées de (label, callback_data).
    Retourne la réponse Telegram (avec message_id) ou None.
    """
    if not _enabled():
        logger.warning("Telegram non configuré — message ignoré.")
        return None

    payload = {
        "chat_id": chat_id or config.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": label, "callback_data": data} for (label, data) in row]
                for row in buttons
            ]
        }

    try:
        r = requests.post(_url("sendMessage"), json=payload,
                          timeout=config.DATA_SOURCE["request_timeout"])
        data = r.json()
        if not data.get("ok"):
            logger.error("sendMessage KO : %s", data)
            return None
        return data["result"]
    except Exception as e:  # noqa: BLE001
        logger.error("send_message échec : %s", e)
        return None


def answer_callback(callback_id: str, text: str = "") -> None:
    """Accuse réception d'un clic sur bouton (enlève le 'chargement')."""
    if not _enabled():
        return
    try:
        requests.post(_url("answerCallbackQuery"),
                      json={"callback_query_id": callback_id, "text": text},
                      timeout=15)
    except Exception as e:  # noqa: BLE001
        logger.warning("answer_callback échec : %s", e)


# ─────────────────────────────────────────────────────────────
# ALERTE PRINCIPALE
# ─────────────────────────────────────────────────────────────

ALERT_BUTTONS_TEMPLATE = [
    [("✅ Pris", "action_taken"), ("❌ Ignoré", "action_ignored")],
    [("⏳ Je surveille", "action_watching")],
]


def format_alert(s: dict) -> str:
    """Construit le texte de l'alerte (cf. SPECS 5.2)."""
    verdict_emoji = "✅" if s.get("final_score", 0) >= config.ALERT_RULES["high_conviction_score"] else "⚡"

    msg = f"""{verdict_emoji} {str(s.get('pattern_name','')).upper()} — {s.get('ticker')} | {s.get('final_score')}/100
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 DeepSeek : {s.get('deepseek_verdict','?')} {s.get('deepseek_score','?')}/10
🐦 Grok     : {s.get('grok_verdict','?')} {s.get('grok_score','?')}/10
🧠 Claude   : {s.get('claude_verdict','?')} {s.get('claude_score','?')}/10

💰 Prix actuel  : {s.get('price')}
🎯 Objectif     : {s.get('target')} (+{s.get('upside',0):.1f}%)
🛑 Stop         : {s.get('stop')} (-{s.get('downside',0):.1f}%)
⚖️  Position     : {s.get('suggested_position_pct', s.get('max_position_pct'))}% du portefeuille
⏱️  Horizon      : {s.get('horizon_days')} jours
📈 Timeframe    : {s.get('timeframe')}

💬 DeepSeek : {s.get('deepseek_reason','')}
💬 Grok     : {s.get('grok_reason','')}
💬 Claude   : {s.get('claude_reason','')}"""

    if s.get("regime_label"):
        msg += f"\n\n🌡️ Régime marché : {s['regime_label']}"
    if s.get("conviction_text"):
        msg += f"\n🎯 {s['conviction_text']}"
    if s.get("divergence_text"):
        msg += f"\n⚠️ Divergence : {s['divergence_text']}"
    if s.get("claude_warning"):
        msg += f"\n\n⚠️ Claude : {s['claude_warning']}"
    if s.get("is_paper"):
        msg += "\n\n📝 (Paper trading — position virtuelle)"
    return msg


def send_alert(signal_data: dict, signal_id: str | None = None) -> dict | None:
    """
    Envoie l'alerte formatée avec les boutons de feedback.
    Le signal_id est intégré aux callback_data pour relier le clic au signal.
    """
    text = format_alert(signal_data)
    suffix = f":{signal_id}" if signal_id else ""
    buttons = [
        [(label, data + suffix) for (label, data) in row]
        for row in ALERT_BUTTONS_TEMPLATE
    ]
    return send_message(text, buttons=buttons)


# ─────────────────────────────────────────────────────────────
# LECTURE DES UPDATES (boutons + commandes)
# ─────────────────────────────────────────────────────────────

def get_updates(offset: int | None = None, timeout: int = 0) -> list[dict]:
    """Récupère les updates (messages, clics boutons)."""
    if not _enabled():
        return []
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(_url("getUpdates"), params=params, timeout=timeout + 15)
        data = r.json()
        return data.get("result", []) if data.get("ok") else []
    except Exception as e:  # noqa: BLE001
        logger.error("get_updates échec : %s", e)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_message("✅ Test de connexion — ton agent boursier est branché sur Telegram.")
    print("Message de test envoyé.")
