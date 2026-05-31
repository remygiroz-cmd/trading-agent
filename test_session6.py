"""
test_session6.py — Validation Session 6 : alertes Telegram.

Envoie réellement sur le Telegram de Rémy :
  1. Un message de connexion
  2. Une alerte complète formatée AVEC les boutons (Pris / Ignoré / Surveille)
  3. Un exemple de bilan quotidien

Puis attend ~25s un éventuel clic sur un bouton pour valider la boucle retour.

Lancer : python test_session6.py
"""

import time
import logging

from alerts import telegram_bot, daily_report

logging.basicConfig(level=logging.INFO, format="%(message)s")


SAMPLE_ALERT = {
    "ticker": "DEMO", "pattern_name": "bull_flag", "final_score": 82,
    "deepseek_verdict": "ACHETER", "deepseek_score": 9,
    "grok_verdict": "ACHETER", "grok_score": 8,
    "claude_verdict": "ATTENDRE", "claude_score": 6,
    "price": 100.0, "target": 115.0, "upside": 15.0,
    "stop": 95.0, "downside": 5.0,
    "max_position_pct": 5, "horizon_days": 10, "timeframe": "1d",
    "deepseek_reason": "Mât propre +18%, cassure en volume x2.1.",
    "grok_reason": "Sentiment positif, catalyseur produit récent.",
    "claude_reason": "Setup valide mais résultats dans 8 jours — prudence.",
    "claude_warning": "Risque de gap sur les résultats du 9 juin.",
    "is_paper": True,
}


def main():
    print("1) Message de connexion…")
    telegram_bot.send_message("✅ Session 6 — ton agent boursier est branché sur Telegram.")

    print("2) Alerte complète avec boutons…")
    res = telegram_bot.send_alert(SAMPLE_ALERT, signal_id="demo-1234")
    assert res and res.get("message_id"), "envoi alerte échoué"
    print(f"   alerte envoyée (message_id={res['message_id']})")

    print("3) Bilan quotidien…")
    telegram_bot.send_message(daily_report.format_daily_report(
        "2026-05-31",
        [{"ticker": "DEMO", "result_1d": 0.021}, {"ticker": "TEST2", "result_1d": -0.013}],
        {"week_win_rate": 0.62, "best_agent": "deepseek"},
        adjustments="Poids DeepSeek 33% -> 35% (bonne semaine).",
    ))

    print("\n4) Clique un bouton de l'alerte dans Telegram… (j'écoute 25s)")
    deadline = time.time() + 25
    last_offset = None
    seen = False
    while time.time() < deadline:
        updates = telegram_bot.get_updates(offset=last_offset, timeout=5)
        for u in updates:
            last_offset = u["update_id"] + 1
            cq = u.get("callback_query")
            if cq:
                data = cq.get("data", "")
                reply = daily_report.handle_callback(data)
                telegram_bot.answer_callback(cq["id"], reply)
                telegram_bot.send_message(reply)
                print(f"   ✅ Bouton cliqué : {data} -> {reply}")
                seen = True
        if seen:
            break
        time.sleep(1)

    if not seen:
        print("   (aucun clic capté — pas grave, l'envoi fonctionne)")

    print("\nBILAN SESSION 6 : ✅ alertes, boutons et bilan envoyés sur Telegram")


if __name__ == "__main__":
    main()
