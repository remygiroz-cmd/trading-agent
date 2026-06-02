"""
test_meta.py — Méta-apprentissage par segment (sans réseau ni DB).

Teste le classement par taille de capi et la sélection des poids par segment
(secteur / capi) avec repli sur les poids globaux.

Lancer : python test_meta.py
"""

import fundamentals
from memory import weights, state

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


print(SEP)
print("1. cap_bucket : seuils de capitalisation")
check("< 2 Md$ -> small", fundamentals.cap_bucket(1.5e9) == "small")
check("2-10 Md$ -> mid", fundamentals.cap_bucket(5e9) == "mid")
check(">= 10 Md$ -> large", fundamentals.cap_bucket(50e9) == "large")
check("inconnu -> None", fundamentals.cap_bucket(None) is None)

print(SEP)
print("2. get_weights_for : sélection segment vs global")
GLOBAL = {"deepseek": 0.33, "grok": 0.33, "claude": 0.34}
blob = {
    "sector": {"Technology": {"weights": {"deepseek": 0.5, "grok": 0.3, "claude": 0.2}, "_sample": 30}},
    "cap": {"small": {"weights": {"deepseek": 0.6, "grok": 0.25, "claude": 0.15}, "_sample": 12}},
}
orig_get = state.get_state
orig_cur = weights.get_current_weights
try:
    weights.get_current_weights = lambda: dict(GLOBAL)
    state.get_state = lambda key, default=None: blob if key == weights.SEGMENT_STATE else default

    w, src = weights.get_weights_for()
    check("aucun segment -> global", src == "global" and w == GLOBAL)

    w, src = weights.get_weights_for(sector="Technology")
    check("secteur connu -> poids secteur", "secteur:Technology" in src and w["deepseek"] == 0.5)

    w, src = weights.get_weights_for(cap_bucket="small")
    check("capi connue -> poids capi", "capi:small" in src and w["deepseek"] == 0.6)

    w, src = weights.get_weights_for(sector="Technology", cap_bucket="small")
    check("secteur ET capi -> on prend le mieux étayé (secteur, n=30)",
          "secteur:Technology" in src)

    w, src = weights.get_weights_for(sector="Inconnu", cap_bucket="huge")
    check("segments inconnus -> global", src == "global")

    # blob partiel : une IA manquante doit être complétée par le global
    blob_partiel = {"sector": {"X": {"weights": {"deepseek": 0.7}, "_sample": 20}}, "cap": {}}
    state.get_state = lambda key, default=None: blob_partiel if key == weights.SEGMENT_STATE else default
    w, src = weights.get_weights_for(sector="X", global_weights=GLOBAL)
    check("les 3 IA sont toujours présentes", set(w) == {"deepseek", "grok", "claude"})
    check("IA manquante complétée par le global", w["grok"] == 0.33 and w["claude"] == 0.34)
finally:
    state.get_state = orig_get
    weights.get_current_weights = orig_cur

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
