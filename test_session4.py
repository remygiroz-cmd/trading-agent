"""
test_session4.py — Validation Session 4 : mémoire cumulative Supabase.

Teste sur les 5 tables :
  1. Connexion (ping)
  2. Insertion d'un signal + lecture
  3. Insertion de votes d'IA liés au signal
  4. Mise à jour d'un résultat (J+1)
  5. Poids des IA (init, lecture, normalisation)
  6. Règle apprise + performance ticker

Les données de test (ticker __TEST__) sont nettoyées à la fin via un appel
REST direct (le code applicatif n'expose JAMAIS de suppression — règle métier).

Lancer : python test_session4.py
"""

import logging

import requests

import config
from memory import database, signals, weights, performance

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
SEP = "─" * 60
TEST_TICKER = "__TEST__"


def cleanup():
    """Supprime les données de test (hors logique applicative)."""
    base = config.SUPABASE_URL.rstrip("/") + "/rest/v1"
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}
    # voter d'abord (clé étrangère), puis signaux, puis perf/weights de test
    sigs = requests.get(f"{base}/trading_signals", headers=h,
                        params={"ticker": f"eq.{TEST_TICKER}", "select": "id"}).json()
    for s in sigs:
        requests.delete(f"{base}/ai_votes", headers=h, params={"signal_id": f"eq.{s['id']}"})
    requests.delete(f"{base}/trading_signals", headers=h, params={"ticker": f"eq.{TEST_TICKER}"})
    requests.delete(f"{base}/ticker_performance", headers=h, params={"ticker": f"eq.{TEST_TICKER}"})
    requests.delete(f"{base}/learned_rules", headers=h,
                    params={"rule_description": "like.*__TEST__*"})


def main():
    print(SEP); print("TEST 1 — Connexion Supabase"); print(SEP)
    assert database.ping(), "ping échoué"
    print("  ✅ Connexion OK")

    print(); print(SEP); print("TEST 2 — Insertion + lecture d'un signal"); print(SEP)
    sig = signals.insert_signal({
        "ticker": TEST_TICKER, "pattern_name": "bull_flag", "timeframe": "1d",
        "entry_price": 100.0, "target_price": 115.0, "stop_loss": 95.0,
        "setup_score": 38, "final_score": 82, "buy_votes": 2, "horizon_days": 10,
        "is_paper": True,
    })
    assert sig and sig.get("id"), "insertion signal échouée"
    sig_id = sig["id"]
    print(f"  ✅ Signal inséré id={sig_id[:8]}…")
    read = signals.get_signal(sig_id)
    assert read and read["ticker"] == TEST_TICKER
    print(f"  ✅ Relu : {read['ticker']} {read['pattern_name']} entry={read['entry_price']}")

    print(); print(SEP); print("TEST 3 — Votes des 3 IA"); print(SEP)
    w = weights.get_current_weights()
    for agent, vote in [
        ("deepseek", {"verdict": "ACHETER", "score": 9, "raison_principale": "mât propre"}),
        ("grok", {"verdict": "ACHETER", "score": 8, "sentiment_score": 0.6}),
        ("claude", {"verdict": "ATTENDRE", "score": 5, "risque_macro": "résultats proches"}),
    ]:
        v = signals.insert_vote(sig_id, agent, tour=1, vote=vote, weight_at_time=w.get(agent))
        assert v, f"vote {agent} échoué"
        print(f"  ✅ Vote {agent:9} {vote['verdict']} {vote['score']}/10 (poids {w.get(agent)})")

    print(); print(SEP); print("TEST 4 — Mise à jour résultat J+1"); print(SEP)
    signals.update_signal_result(sig_id, days_elapsed=1, result=0.034)
    updated = signals.get_signal(sig_id)
    assert updated["result_1d"] is not None
    print(f"  ✅ result_1d = {updated['result_1d']}")
    signals.mark_target_reached(sig_id)
    print("  ✅ target_reached marqué")

    print(); print(SEP); print("TEST 5 — Poids des IA"); print(SEP)
    print(f"  Poids actuels : {w}")
    norm = weights.normalize_weights()
    total = sum(norm.values())
    print(f"  Après normalisation : { {k: round(v,3) for k,v in norm.items()} } (somme={total:.3f})")
    assert abs(total - 1.0) < 0.01, "normalisation incorrecte"
    print("  ✅ Somme des poids = 1")

    print(); print(SEP); print("TEST 6 — Règle apprise + perf ticker"); print(SEP)
    rule = performance.add_learned_rule(
        "__TEST__ Éviter les cassures sur RSI > 85", "pattern", 0.72, 12)
    assert rule, "règle non insérée"
    rules = performance.get_relevant_rules()
    print(f"  ✅ Règle insérée, {len(rules)} règle(s) active(s) fiables")
    performance.upsert_ticker_performance(TEST_TICKER, {
        "total_signals": 1, "correct_signals": 1, "win_rate": 1.0, "avg_gain": 0.034})
    tp = performance.get_ticker_performance(TEST_TICKER)
    print(f"  ✅ Perf ticker : {tp.get('total_signals')} signaux, win_rate={tp.get('win_rate')}")

    print(); print(SEP); print("BILAN SESSION 4 : ✅ Les 5 tables fonctionnent (insert/read/update)")
    print(SEP)


if __name__ == "__main__":
    try:
        main()
    finally:
        print("\nNettoyage des données de test…")
        try:
            cleanup()
            print("✅ Données __TEST__ supprimées (base propre).")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Nettoyage partiel : {e}")
