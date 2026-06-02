"""
test_regime.py — Validation de l'adaptation au régime de marché (sans réseau).

Teste l'application des paramètres de régime : seuil d'alerte dynamique (débat),
multiplicateur de taille (conviction) et cohérence de la config des régimes.

Lancer : python test_regime.py
"""

import config
import conviction as C
from agents import debate

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
print("1. config des régimes : cohérence")
r = config.REGIMES
check("3 régimes définis", set(r) == {"haussier", "prudent", "defavorable"})
check("seuil croît avec la prudence",
      r["haussier"]["min_final_score"] < r["prudent"]["min_final_score"]
      < r["defavorable"]["min_final_score"])
check("taille décroît avec la prudence",
      r["haussier"]["size_mult"] > r["prudent"]["size_mult"] > r["defavorable"]["size_mult"])
check("haussier joue plein pot (x1.0)", r["haussier"]["size_mult"] == 1.0)

print(SEP)
print("2. seuil d'alerte dynamique (débat)")
votes = {"deepseek": {"verdict": "ACHETER", "score": 8},
         "grok": {"verdict": "ACHETER", "score": 8},
         "claude": {"verdict": "ATTENDRE", "score": 5}}
w = {"deepseek": 0.34, "grok": 0.33, "claude": 0.33}
# score final ≈ (8*.34 + 8*.33 + 5*.33)*10 = (2.72+2.64+1.65)*10 = 70.1
res75 = debate.calculate_final_score(votes, w, min_final_score=75)
res82 = debate.calculate_final_score(votes, w, min_final_score=82)
check("même score final quel que soit le seuil",
      res75["final_score"] == res82["final_score"])
# Un score ~70 ne passe ni 75 ni 82 -> testons un cas qui bascule
strong = {"deepseek": {"verdict": "ACHETER", "score": 8},
          "grok": {"verdict": "ACHETER", "score": 8},
          "claude": {"verdict": "ACHETER", "score": 8}}  # score 80
a75 = debate.calculate_final_score(strong, w, min_final_score=75)
a82 = debate.calculate_final_score(strong, w, min_final_score=82)
check("score 80 : alerte en haussier (seuil 75)", a75["send_alert"] is True)
check("score 80 : PAS d'alerte en prudent (seuil 82)", a82["send_alert"] is False)
check("seuil mémorisé dans le résultat", a82["min_final_score"] == 82)

print(SEP)
print("3. multiplicateur de taille selon le régime")
base = C.position_size(100, regime_mult=1.0)               # haussier
prud = C.position_size(100, regime_mult=0.6)               # prudent
defa = C.position_size(100, regime_mult=0.3)               # défavorable
check("prudent réduit la taille vs haussier", prud < base)
check("défavorable réduit encore plus", defa < prud)

print(SEP)
print("4. régime se combine avec le risque (sécurité prioritaire)")
# downside large -> le cap de risque doit primer même en haussier
capped = C.position_size(100, downside_pct=20.0, regime_mult=1.0)
check("cap de risque respecté malgré régime plein (downside 20% -> 5%)", capped == 5.0)

print(SEP)
print("5. evaluate : propage regime_mult")
ev_full = C.evaluate(final_score=90, fundamental_score=80, sentiment_score=0.3, regime_mult=1.0)
ev_prud = C.evaluate(final_score=90, fundamental_score=80, sentiment_score=0.3, regime_mult=0.6)
check("taille conseillée plus petite en prudent",
      ev_prud["suggested_position_pct"] < ev_full["suggested_position_pct"])

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
