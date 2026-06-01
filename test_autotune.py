"""
test_autotune.py — Validation de l'auto-réglage des sorties (sans réseau).

Teste la logique pure (décision, conversion réglage<->override) et l'intégration
de l'override dans market_context.compute_levels, sans toucher à Supabase ni aux
données marché.

Lancer : python test_autotune.py
"""

import config
import market_context
import autotune

SEP = "─" * 60
ok = 0
ko = 0


def check(name, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        ko += 1
        print(f"  ❌ {name}")


def _row(win, avg_win, exp, target=("atr", 3.0), stop=("atr", 1.5), h=42):
    return {"cfg": f"obj {target[0]}{target[1]} / stop {stop[0]}{stop[1]} / {h}j",
            "target": target, "stop": stop, "horizon": h,
            "te": {"n": 100, "win": win, "avg_win": avg_win, "pct_ge10": 30,
                   "exp": exp, "net": exp * 100, "worst": -20},
            "tr": {"n": 100, "win": win, "avg_win": avg_win, "pct_ge10": 30,
                   "exp": exp, "net": exp * 100, "worst": -20}}


print(SEP)
print("1. choose_candidate : critère strict prioritaire")
rows = [
    _row(60, 12, 2.0, target=("atr", 3.0)),   # passe le critère, exp 2.0
    _row(58, 11, 3.5, target=("atr", 4.0)),   # passe le critère, exp 3.5 -> gagnant
    _row(70, 5, 5.0, target=("pct", 0.10)),   # meilleure exp mais avg_win < 10 -> exclu
]
cand = autotune.choose_candidate(rows, min_winrate=55, min_avg_win=10)
check("retient le meilleur respectant le critère (exp 3.5)", cand["te"]["exp"] == 3.5)
check("ignore le réglage à gagnants < 10%", cand["target"] != ("pct", 0.10))

print(SEP)
print("2. choose_candidate : repli si aucun ne passe le critère")
rows2 = [_row(40, 6, 1.0), _row(45, 7, 2.5), _row(50, 8, 0.5)]
cand2 = autotune.choose_candidate(rows2, min_winrate=55, min_avg_win=10)
check("repli sur la meilleure espérance TEST (2.5)", cand2["te"]["exp"] == 2.5)

print(SEP)
print("3. should_apply : garde-fous")
current = _row(50, 10, 1.0)
# candidat nettement meilleur
apply, reason = autotune.should_apply(_row(60, 12, 3.0), current,
                                      min_improvement_pp=0.5, min_test_winrate=50)
check("applique si gain suffisant", apply is True)
# gain insuffisant
apply, reason = autotune.should_apply(_row(60, 12, 1.2), current, 0.5, 50)
check("refuse si gain < marge (+0.2pp)", apply is False)
# espérance négative
apply, reason = autotune.should_apply(_row(60, 12, -0.5), current, 0.5, 50)
check("refuse si espérance TEST négative", apply is False)
# réussite trop faible
apply, reason = autotune.should_apply(_row(45, 12, 5.0), current, 0.5, 50)
check("refuse si réussite TEST < mini", apply is False)
# pas de référence -> adopte si valable
apply, reason = autotune.should_apply(_row(60, 12, 2.0), None, 0.5, 50)
check("adopte si aucune référence et candidat valable", apply is True)

print(SEP)
print("4. spec_to_params : conversion réglage -> override")
p = autotune.spec_to_params(("atr", 3.0), ("atr", 1.5), 42)
check("mode atr quand les deux jambes sont atr", p["mode"] == "atr")
check("target_kind/value corrects", p["target_kind"] == "atr" and p["target_value"] == 3.0)
check("horizon converti en int", p["default_horizon"] == 42)
p2 = autotune.spec_to_params(("pct", 0.15), ("pct", 0.10), 21)
check("mode fixed quand les deux jambes sont pct", p2["mode"] == "fixed")
p3 = autotune.spec_to_params(("atr", 3.0), ("pct", 0.10), 30)
check("mode atr si une seule jambe est atr (mixte)", p3["mode"] == "atr")

print(SEP)
print("5. compute_levels : override appris pris en compte")
# Force un override en mémoire process (sans DB) via le cache.
market_context._active_risk_cache = None
saved = market_context.get_active_risk
try:
    # Injecte un réglage 'jambes indépendantes' directement dans le cache
    market_context._active_risk_cache = {
        **config.RISK,
        "target_kind": "pct", "target_value": 0.20,
        "stop_kind": "pct", "stop_value": 0.08,
        "default_horizon": 30,
    }
    lv = market_context.compute_levels(100.0, atr_pct=0.03)
    check("objectif = +20% (jambe pct)", abs(lv["target"] - 120.0) < 1e-6)
    check("stop = -8% (jambe pct)", abs(lv["stop"] - 92.0) < 1e-6)
    check("horizon override = 30", lv["horizon"] == 30)

    # Jambe atr : objectif = entrée + mult*atr_pct, borné par max_target_pct
    market_context._active_risk_cache = {
        **config.RISK,
        "target_kind": "atr", "target_value": 3.0,
        "stop_kind": "atr", "stop_value": 1.5,
        "default_horizon": 42,
    }
    lv = market_context.compute_levels(100.0, atr_pct=0.04)
    # target_pct = 3*0.04 = 0.12 -> 112 ; stop_pct = 1.5*0.04 = 0.06 -> 94
    check("objectif atr = +12%", abs(lv["target"] - 112.0) < 1e-6)
    check("stop atr = -6%", abs(lv["stop"] - 94.0) < 1e-6)

    # Bornes : target_value énorme plafonné par max_target_pct
    market_context._active_risk_cache = {
        **config.RISK,
        "target_kind": "pct", "target_value": 0.99,
        "stop_kind": "pct", "stop_value": 0.30,
        "default_horizon": 10,
    }
    lv = market_context.compute_levels(100.0, atr_pct=0.03)
    check("objectif plafonné à max_target_pct",
          abs(lv["target_pct"] - config.RISK["max_target_pct"]) < 1e-6)
    check("stop plafonné à max_stop_pct",
          abs(lv["stop_pct"] - config.RISK["max_stop_pct"]) < 1e-6)
finally:
    market_context._active_risk_cache = None

print(SEP)
print("6. compute_levels : repli config.RISK historique (mode atr)")
market_context._active_risk_cache = dict(config.RISK)  # pas de jambes indépendantes
lv = market_context.compute_levels(100.0, atr_pct=0.02)
# atr_target_mult=3 *0.02=0.06 -> 106 ; atr_stop_mult=1.5*0.02=0.03 borné à min_stop 0.04 -> 96
check("mode atr historique : objectif +6%", abs(lv["target"] - 106.0) < 1e-6)
check("mode atr historique : stop borné à min_stop_pct (-4%)", abs(lv["stop"] - 96.0) < 1e-6)
market_context._active_risk_cache = None

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
