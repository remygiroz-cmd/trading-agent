"""
test_session8.py — Validation Session 8 : boucle d'apprentissage.

Sur données simulées (nettoyées ensuite) :
  1. Insère 8 signaux clos (figure __TESTPAT__) + votes DeepSeek ACHETER
  2. update_ticker_performance_all -> agrégats par ticker
  3. generate_learned_rules -> règle déduite (figure gagnante)
  4. recalculate_ai_weights -> poids recalculés (puis restaurés à l'init)
  5. update_open_signal_results -> s'exécute sans erreur

L'état des poids est restauré à l'init pour ne pas polluer la prod.

Lancer : python test_session8.py
"""

import logging

import requests

import config
from memory import database, signals, performance, weights, learning

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
SEP = "─" * 60
T = "__TEST__"
PAT = "__TESTPAT__"


def cleanup():
    base = config.SUPABASE_URL.rstrip("/") + "/rest/v1"
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}
    sigs = requests.get(f"{base}/trading_signals", headers=h,
                        params={"ticker": f"eq.{T}", "select": "id"}).json()
    for s in sigs:
        requests.delete(f"{base}/ai_votes", headers=h, params={"signal_id": f"eq.{s['id']}"})
    requests.delete(f"{base}/trading_signals", headers=h, params={"ticker": f"eq.{T}"})
    requests.delete(f"{base}/ticker_performance", headers=h, params={"ticker": f"eq.{T}"})
    requests.delete(f"{base}/learned_rules", headers=h,
                    params={"rule_description": f"like.*{PAT}*"})


def restore_weights():
    """Réinsère les poids initiaux comme valeurs courantes (pas de suppression)."""
    for agent, w in config.INITIAL_WEIGHTS.items():
        weights.save_weight(agent, w, reason="restauration post-test")


def main():
    print(SEP); print("Préparation : 8 signaux clos simulés + votes DeepSeek"); print(SEP)
    # 6 gagnants, 2 perdants -> win rate 75% (déclenche une règle, >65%)
    results = [0.08, 0.05, 0.12, 0.03, 0.06, 0.09, -0.04, -0.02]
    for i, r in enumerate(results):
        sig = signals.insert_signal({
            "ticker": T, "pattern_name": PAT, "timeframe": "1d",
            "entry_price": 100.0, "target_price": 110.0, "stop_loss": 95.0,
            "setup_score": 40, "final_score": 88, "buy_votes": 3, "horizon_days": 7,
            "result_7d": r, "is_paper": True,
        })
        signals.insert_vote(sig["id"], "deepseek", 1,
                            {"verdict": "ACHETER", "score": 9}, weight_at_time=0.33)
    print(f"  {len(results)} signaux insérés (6 gagnants / 2 perdants)")

    print(); print(SEP); print("1) update_ticker_performance_all"); print(SEP)
    learning.update_ticker_performance_all()
    tp = performance.get_ticker_performance(T)
    print(f"  {T} : {tp.get('total_signals')} signaux, win_rate={tp.get('win_rate')}, "
          f"avg_gain={tp.get('avg_gain')}, avg_loss={tp.get('avg_loss')}")
    assert tp.get("total_signals") == 8 and abs(float(tp["win_rate"]) - 0.75) < 0.01

    print(); print(SEP); print("2) generate_learned_rules"); print(SEP)
    rules = learning.generate_learned_rules(min_sample=8)
    pat_rules = [r for r in rules if PAT in r["rule_description"]]
    for r in pat_rules:
        print(f"  ➕ {r['rule_description']} (fiabilité {float(r['reliability'])*100:.0f}%)")
    assert pat_rules, "aucune règle générée pour la figure test"

    print(); print(SEP); print("3) recalculate_ai_weights (puis restauration)"); print(SEP)
    new_w = weights.recalculate_ai_weights(min_votes=5)
    print(f"  Poids recalculés : { {k: round(v,3) for k,v in new_w.items()} } "
          f"(somme={sum(new_w.values()):.3f})")
    assert abs(sum(new_w.values()) - 1.0) < 0.02
    restore_weights()
    weights.normalize_weights()
    print(f"  Poids restaurés à l'init : {weights.get_current_weights()}")

    print(); print(SEP); print("4) update_open_signal_results"); print(SEP)
    res = learning.update_open_signal_results()
    print(f"  Exécuté : {res}")

    print(); print(SEP); print("BILAN SESSION 8 : ✅ boucle d'apprentissage opérationnelle"); print(SEP)


if __name__ == "__main__":
    try:
        main()
    finally:
        print("\nNettoyage des données de test…")
        try:
            cleanup()
            print("✅ Données de test supprimées (base propre).")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Nettoyage partiel : {e}")
