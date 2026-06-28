"""
test_monitor.py — Validation du moteur de signaux achat/vente (sans réseau).

Lancer : python test_monitor.py
"""

import config
import monitor as m

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


# Raccourci : _signal(typ, price, entry, rsi, ma20, ma50, ma200, ma50_rising)
def sig(typ, price, entry, rsi, ma20, ma50, ma200, rising):
    return m._signal(typ, price, entry, rsi, ma20, ma50, ma200, rising)[0]


print(SEP)
print("1. CONVICTION — renforcer sur repli")
# tendance haussière (prix > MA200, MA50 monte), RSI très bas -> ACHAT FORT
check("RSI 28 en tendance haussière -> ACHAT FORT",
      sig("conviction", 100, 90, 28, 101, 100, 80, True) == "BUY_STRONG")
# repli pile sur la MA50 en tendance haussière -> ACHAT
check("repli sur MA50 -> ACHAT",
      sig("conviction", 100.5, 90, 45, 102, 100, 80, True) == "BUY")
# rien de spécial -> CONSERVER
check("milieu de range -> CONSERVER",
      sig("conviction", 110, 90, 55, 108, 100, 80, True) == "HOLD")
# suracheté -> VENTE (vendre haut pour racheter plus bas)
check("RSI 80 -> VENTE (on vend la surchauffe pour racheter plus bas)",
      sig("conviction", 120, 90, 80, 110, 100, 80, True) == "SELL")
# très étiré (+20% au-dessus MA50) même RSI moyen -> VENTE
check("+20% au-dessus MA50 -> VENTE (étiré)",
      sig("conviction", 120, 90, 60, 110, 100, 80, True) == "SELL")
# vraie cassure (sous MA50 et MA200, MA50 baisse) -> VENTE
check("sous MA50 et MA200 + MA50 baisse -> VENTE (tendance cassée)",
      sig("conviction", 78, 90, 45, 82, 85, 80, False) == "SELL")

print(SEP)
print("2. SPEC — entrer / sortir")
# objectif de gain atteint (+16% depuis achat) -> VENTE
check("PV +16% -> VENTE (objectif)",
      sig("spec", 116, 100, 60, 110, 105, 90, True) == "SELL")
# suracheté -> VENTE
check("RSI 75 -> VENTE",
      sig("spec", 108, 100, 75, 106, 104, 90, True) == "SELL")
# cassure sous MA50 en tendance baissière -> VENTE
check("sous MA50 + MA50 baisse -> VENTE",
      sig("spec", 95, 100, 50, 98, 100, 110, False) == "SELL")
# survendu -> ACHAT
check("RSI 30 -> ACHAT (entrée)",
      sig("spec", 90, 100, 30, 92, 95, 100, True) == "BUY")
# reprise au-dessus des moyennes -> ACHAT
check("prix > MA20 > MA50, RSI 60 -> ACHAT (momentum)",
      sig("spec", 105, 100, 60, 103, 101, 95, True) == "BUY")
# rien -> CONSERVER
check("neutre -> CONSERVER",
      sig("spec", 100, 100, 50, 100, 100, 100, True) == "HOLD")

print(SEP)
print("3. priorité des sorties spec (objectif avant entrée)")
# survendu MAIS +16% : on prend les bénéfices (sortie prioritaire)
check("survendu + objectif atteint -> VENTE (priorité sortie)",
      sig("spec", 116, 100, 30, 110, 108, 90, True) == "SELL")

print(SEP)
print("4. config watchlist cohérente")
wl = config.WATCHLIST_MONITOR
check("11 valeurs surveillées", len(wl) == 11)
check("6 convictions", sum(1 for s in wl if s["type"] == "conviction") == 6)
check("5 spéculatives", sum(1 for s in wl if s["type"] == "spec") == 5)
check("toutes ont un prix d'achat", all(s.get("entry") for s in wl))

print(SEP)
print("5. format bulletin (sans réseau)")
fake = [
    {"name": "LVMH", "cur": "€", "ok": True, "price": 480.0, "pnl": 0.01, "signal": "BUY",
     "reason": "repli sur la MA50"},
    {"name": "Soitec", "cur": "€", "ok": True, "price": 180.0, "pnl": 0.16, "signal": "SELL",
     "reason": "objectif atteint"},
    {"name": "Tesla", "cur": "$", "ok": True, "price": 400.0, "pnl": -0.12, "signal": "HOLD",
     "reason": "rien"},
]
b = m.format_bulletin(fake)
check("section achat présente", "À ACHETER" in b and "LVMH" in b)
check("section vente présente", "À VENDRE" in b and "Soitec" in b)
check("conserver listé avec PV", "Tesla" in b and "-12%" in b)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
