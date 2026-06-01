"""
test_fundamentals.py — Validation de l'analyse fondamentale (sans réseau ni DB).

Teste le scoring heuristique, le consensus analystes, le formatage et
l'intégration dans les prompts (DeepSeek compact + Claude bloc complet).

Lancer : python test_fundamentals.py
"""

import fundamentals
from agents import prompts

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
print("1. score_fundamentals : entreprise solide")
solide = {"revenueGrowth": 0.25, "earningsGrowth": 0.30, "profitMargins": 0.22,
          "returnOnEquity": 0.28, "debtToEquity": 30, "freeCashflow": 5e9}
sc = fundamentals.score_fundamentals(solide)
check("score élevé", sc["score"] >= 90)
check("label solide", sc["label"] == "solide")
check("toutes composantes comptées", sc["available"] == 6)

print(SEP)
print("2. score_fundamentals : entreprise fragile")
fragile = {"revenueGrowth": -0.10, "earningsGrowth": -0.20, "profitMargins": -0.05,
           "returnOnEquity": -0.02, "debtToEquity": 250, "freeCashflow": -1e8}
sc2 = fundamentals.score_fundamentals(fragile)
check("score faible", sc2["score"] <= 25)
check("label fragile", sc2["label"] == "fragile")

print(SEP)
print("3. score_fundamentals : normalisation sur données partielles")
partiel = {"revenueGrowth": 0.20, "profitMargins": 0.18}  # 2 composantes seulement
sc3 = fundamentals.score_fundamentals(partiel)
check("score calculé sur dispo uniquement", sc3["score"] is not None)
check("n'invente pas de composantes", sc3["available"] == 2)
check("dict vide -> n/d", fundamentals.score_fundamentals({})["label"] == "n/d")

print(SEP)
print("4. dette : plus bas = mieux")
faible_dette = fundamentals.score_fundamentals({"debtToEquity": 20})["score"]
forte_dette = fundamentals.score_fundamentals({"debtToEquity": 300})["score"]
check("dette faible mieux notée que dette forte", faible_dette > forte_dette)

print(SEP)
print("5. analyst_view : consensus + potentiel")
data = {"recommendationKey": "buy", "numberOfAnalystOpinions": 25, "targetMeanPrice": 120.0}
av = fundamentals.analyst_view(data, price=100.0)
check("traduit la reco en FR", "achat" in av)
check("nb analystes", "25 analystes" in av)
check("potentiel calculé (+20%)", "+20%" in av)
check("sans données -> n/d", "n/d" in fundamentals.analyst_view({}, 100))

print(SEP)
print("6. fundamentals_context : structure (données injectées en cache, sans réseau)")
# Injecte un cache process en court-circuitant la récupération réseau.
orig = fundamentals._fetch_raw
fundamentals._fetch_raw = lambda t: {
    "sector": "Technology", "marketCap": 3.2e12, "trailingPE": 30,
    "revenueGrowth": 0.18, "profitMargins": 0.25, "returnOnEquity": 0.40,
    "debtToEquity": 45, "recommendationKey": "buy",
    "numberOfAnalystOpinions": 40, "targetMeanPrice": 250.0,
}
try:
    fc = fundamentals.fundamentals_context("NVDA", price=200.0)
    check("score_text rempli", "Santé fondamentale" in fc["score_text"])
    check("secteur extrait", fc["sector"] == "Technology")
    check("capi formatée en Md/$", "$" in fc["market_cap"])
    check("consensus avec potentiel", "+25%" in fc["analyst_text"])
    check("PER présent dans le détail", "PER" in fc["text"])
finally:
    fundamentals._fetch_raw = orig

print(SEP)
print("7. intégration prompts (pas de KeyError, blocs injectés)")
ctx = {
    "ticker": "NVDA", "company_name": "Nvidia", "sector": "Technology",
    "market_cap": "3200.0 Md$", "pattern_name": "bull_flag", "setup_score": 42,
    "fundamentals_score": "Santé fondamentale : solide (92/100)",
    "fundamentals_context": "croissance CA +18% · marge nette 25% | PER 30",
    "analyst_view": "Consensus analystes : achat, 40 analystes, objectif moyen 250.00 (+25%)",
}
ds = prompts.fill(prompts.DEEPSEEK_PROMPT_T1, ctx)
cl = prompts.fill(prompts.CLAUDE_PROMPT_T1, ctx)
check("DeepSeek : ligne fondamentaux compacte", "solide (92/100)" in ds)
check("Claude : bloc fondamentaux complet", "croissance CA +18%" in cl)
check("Claude : consensus analystes injecté", "objectif moyen 250" in cl)
check("aucun placeholder résiduel (Claude)", "{fundamentals_context}" not in cl)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
