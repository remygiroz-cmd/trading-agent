"""
test_conviction.py — Validation conviction composite / divergences / sizing.

Logique pure, aucune dépendance réseau ni DB.

Lancer : python test_conviction.py
"""

import config
import conviction as C

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
print("1. compute_conviction : trois piliers")
c = C.compute_conviction(final_score=80, fundamental_score=90, sentiment_score=0.0)
# (.8*.5 + .9*.3 + .5*.2)/1.0 = .77 -> 77
check("conviction = 77", c["conviction"] == 77)
check("label forte", c["label"] == "forte")
check("3 axes disponibles", c["available"] == 3)

print(SEP)
print("2. compute_conviction : renormalisation sur dispo partielle")
c2 = C.compute_conviction(final_score=80)  # technique seule
check("conviction = 80 (poids renormalisé)", c2["conviction"] == 80)
check("1 axe", c2["available"] == 1)
check("rien -> n/d", C.compute_conviction()["conviction"] is None)

print(SEP)
print("3. detect_divergences")
d1 = C.detect_divergences({"technique": 0.8, "fondamental": 0.3})
check("technique forte / fondamental fragile détectée",
      any("piège" in x for x in d1))
d2 = C.detect_divergences({"technique": 0.3, "fondamental": 0.8})
check("fondamental solide / technique faible détectée",
      any("timing" in x for x in d2))
d3 = C.detect_divergences({"technique": 0.8, "sentiment": 0.2})
check("technique forte / actualités négatives détectée",
      any("catalyseur" in x for x in d3))
d4 = C.detect_divergences({"technique": 0.7, "fondamental": 0.7, "sentiment": 0.7})
check("aucune divergence si tout aligné", d4 == [])

print(SEP)
print("4. position_size : échelle de conviction")
check("conviction 100 -> plafond 10%",
      C.position_size(100) == config.SIZING["max_pct"])
check("conviction <= plancher -> 1%",
      C.position_size(60) == config.SIZING["min_pct"])
mid = C.position_size(80)
check("conviction 80 -> intermédiaire (~5.5%)", 5.0 <= mid <= 6.0)

print(SEP)
print("5. position_size : pénalité divergence")
base = C.position_size(100, has_divergence=False)
pen = C.position_size(100, has_divergence=True)
check("divergence réduit la taille", pen < base)
check("réduction = facteur config", abs(pen - base * config.SIZING["divergence_factor"]) < 0.6)

print(SEP)
print("6. position_size : cap par le risque (sécurité)")
# downside 20% -> risque max 1% => taille max 5%
check("stop large plafonne la taille (downside 20% -> 5%)",
      C.position_size(100, downside_pct=20.0) == 5.0)
check("stop serré ne bride pas (downside 5% -> reste 10%)",
      C.position_size(100, downside_pct=5.0) == 10.0)

print(SEP)
print("7. position_size : cap des IA (prudence Claude)")
check("cap IA respecté (max 3%)", C.position_size(100, ai_max_pct=3) == 3.0)

print(SEP)
print("8. evaluate : synthèse complète")
ev = C.evaluate(final_score=85, fundamental_score=30, sentiment_score=-0.5,
                downside_pct=10.0, ai_max_pct=8)
check("conviction calculée", ev["conviction"] is not None)
check("divergence détectée (tech forte / fond fragile)", ev["divergence"] is True)
check("texte divergence non vide", bool(ev["divergence_text"]))
check("taille conseillée bornée et > 0", 0 < ev["suggested_position_pct"] <= config.SIZING["max_pct"])
check("texte conviction lisible", "Conviction" in ev["conviction_text"])

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
