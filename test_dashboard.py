"""
test_dashboard.py — Validation des agrégats du tableau de bord (sans réseau).

Lancer : python test_dashboard.py
"""

import dashboard as D

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


SIGS = [
    {"ticker": "A", "sector": "Technology", "cap_bucket": "large", "conviction": 85,
     "result_7d": 0.10, "realized_pnl_eur": 100, "divergence": False, "created_at": "2026-06-01T10:00:00"},
    {"ticker": "B", "sector": "Technology", "cap_bucket": "small", "conviction": 70,
     "result_7d": -0.05, "realized_pnl_eur": -50, "divergence": True, "created_at": "2026-06-01T10:00:00"},
    {"ticker": "C", "sector": "Healthcare", "cap_bucket": "large", "conviction": 60,
     "result_7d": 0.02, "divergence": False, "created_at": "2026-06-01T10:00:00"},
    {"ticker": "D", "sector": "Technology", "cap_bucket": "large", "conviction": 90,
     "result_7d": 0.15, "divergence": False, "created_at": "2026-06-01T10:00:00"},
    {"ticker": "E", "sector": "Energy", "conviction": 40, "result_7d": None,
     "created_at": "2026-06-01T10:00:00"},  # en cours
]

print(SEP)
print("1. global_stats")
g = D.global_stats(SIGS)
check("4 signaux clos", g["n"] == 4)
check("1 en cours", g["open"] == 1)
check("taux de réussite 75%", abs(g["win_rate"] - 0.75) < 1e-9)
check("espérance ~5.5%", abs(g["expectancy"] - 0.055) < 1e-9)
check("gain moyen 9%", abs(g["avg_gain"] - 0.09) < 1e-9)
check("perte moyenne -5%", abs(g["avg_loss"] + 0.05) < 1e-9)
check("P&L paper +50€", abs(g["pnl_eur"] - 50) < 1e-9)
check("meilleur 15% / pire -5%", abs(g["best"] - 0.15) < 1e-9 and abs(g["worst"] + 0.05) < 1e-9)

print(SEP)
print("2. global_stats : aucun signal clos")
g0 = D.global_stats([{"result_7d": None}])
check("n=0, pas de division par zéro", g0["n"] == 0 and g0["win_rate"] == 0.0)

print(SEP)
print("3. winrate_by secteur / capi")
secs = {r["key"]: r for r in D.winrate_by(SIGS, "sector")}
check("Technology n=3, ~67%", secs["Technology"]["n"] == 3 and abs(secs["Technology"]["win_rate"] - 2/3) < 1e-9)
check("Healthcare n=1, 100%", secs["Healthcare"]["n"] == 1 and secs["Healthcare"]["win_rate"] == 1.0)
check("Energy (en cours) absent", "Energy" not in secs)
caps = {r["key"]: r for r in D.winrate_by(SIGS, "cap_bucket")}
check("large 100% (n=3)", caps["large"]["win_rate"] == 1.0 and caps["large"]["n"] == 3)
check("small 0% (n=1)", caps["small"]["win_rate"] == 0.0)
check("min_n filtre les petits échantillons",
      all(r["n"] >= 2 for r in D.winrate_by(SIGS, "sector", min_n=2)))

print(SEP)
print("4. winrate_by_conviction (tranches)")
conv = {r["key"]: r for r in D.winrate_by_conviction(SIGS)}
check("tranche 80-100 : 2 signaux, 100%", conv["80-100"]["n"] == 2 and conv["80-100"]["win_rate"] == 1.0)
check("tranche 65-79 : 0%", conv["65-79"]["win_rate"] == 0.0)
check("tranche 50-64 : 100%", conv["50-64"]["win_rate"] == 1.0)

print(SEP)
print("5. divergence_stats")
d = D.divergence_stats(SIGS)
check("avec divergence : 0% (n=1)", d["avec"]["n"] == 1 and d["avec"]["win_rate"] == 0.0)
check("sans divergence : 100% (n=3)", d["sans"]["n"] == 3 and d["sans"]["win_rate"] == 1.0)

print(SEP)
print("6. rendus (ne crashent pas, contenu attendu)")
txt = D.build_text_summary(SIGS)
check("résumé texte : taux global présent", "Taux de réussite : 75%" in txt)
html_out = D.build_html(SIGS)
check("HTML : doctype", html_out.startswith("<!doctype html>"))
check("HTML : un ticker récent affiché", ">A<" in html_out or ">D<" in html_out)
check("HTML : carte taux de réussite", "Taux de réussite" in html_out)
empty = D.build_text_summary([{"result_7d": None}])
check("résumé vide géré proprement", "Aucun signal clos" in empty)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
