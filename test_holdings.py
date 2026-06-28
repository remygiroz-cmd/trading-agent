"""
test_holdings.py — Validation du suivi temps réel du portefeuille (sans réseau).

On mocke les cours pour vérifier la dérivation (prix de revient, cours de
référence) et le calcul live (valeur, P/L, variation du jour, agrégats).

Lancer : python test_holdings.py
"""

import holdings as h

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


def approx(a, b, tol=0.5):
    return a is not None and abs(a - b) <= tol


print(SEP)
print("1) DÉRIVATION — relevé appli -> prix de revient + cours de référence")

# Ligne CTO en % : valeur 3496.70 €, -12.58%, acheté 441.28
d = h.derive({"value_eur": 3496.70, "pl_pct": -0.1258, "buy_price": 441.28})
check("cost_basis ≈ 4000 €", approx(d["cost_basis_eur"], 4000.0, 1.0))
check("ref_price ≈ 385.8", approx(d["ref_price"], 385.78, 0.5))

# Ligne PEA en € : valeur 977.86 €, -62.62 €, acheté 80.04
d = h.derive({"value_eur": 977.86, "pl_eur": -62.62, "buy_price": 80.04})
check("cost_basis = 1040.48 €", approx(d["cost_basis_eur"], 1040.48, 0.01))
check("pl_pct ≈ -6.0%", approx(d["pl_pct_snap"] * 100, -6.02, 0.1))
check("ref_price ≈ 75.22 (≈ 13 actions)", approx(d["ref_price"], 75.22, 0.2))

# Ligne sans buy_price (ETF) : ref_price incalculable
d = h.derive({"value_eur": 518.48, "pl_pct": -0.6549, "buy_price": None})
check("ETF : cost_basis ≈ 1502 €", approx(d["cost_basis_eur"], 1502.4, 1.0))
check("ETF : ref_price = None", d["ref_price"] is None)


print(SEP)
print("2) CALCUL LIVE — le cours monte de 10% depuis le relevé")

# On force le cours live : ref ≈ 75.22, cours +10% -> 82.74, veille 80.00
def fake_two(_tk):
    return 82.74, 80.00

h._last_two_closes = fake_two

line = {"account": "PEA", "name": "Sanofi", "ticker": "SAN.PA", "cur": "€",
        "value_eur": 977.86, "pl_eur": -62.62, "buy_price": 80.04}
r = h.evaluate_line(line, {})
check("position OK", r["ok"] is True)
# valeur = 977.86 * 82.74/75.22 ≈ 1075.6
check("valeur live ≈ 1075 €", approx(r["value_now"], 1075.6, 2.0))
# P/L depuis achat = 1075.6 - 1040.48 ≈ +35 €
check("P/L depuis achat ≈ +35 €", approx(r["pl_eur"], 35.1, 2.0))
check("P/L % > 0 maintenant", r["pl_pct"] > 0)
check("variation du jour ≈ +3.4%", approx(r["day_pct"] * 100, 3.42, 0.1))


print(SEP)
print("3) ETF sans buy_price — la référence se fixe au 1er passage")

def fake_etf(_tk):
    return 50.0, 49.0

h._last_two_closes = fake_etf
cache = {}
etf = {"account": "CTO", "name": "Gold 3x", "ticker": "3GOL.L", "cur": "$",
       "value_eur": 518.48, "pl_pct": -0.6549, "buy_price": None}
r = h.evaluate_line(etf, cache)
check("référence mémorisée = 50.0", cache.get("3GOL.L") == 50.0)
check("valeur = valeur du relevé au 1er passage", approx(r["value_now"], 518.48, 0.5))


print(SEP)
print("4) AGRÉGATS — totaux par compte + espèces + global")

def fake_flat(_tk):
    return 100.0, 100.0  # cours = référence -> valeur = relevé

h._last_two_closes = fake_flat
lines = [
    {"account": "CTO", "name": "A", "ticker": "A", "cur": "$",
     "value_eur": 1000.0, "pl_pct": 0.0, "buy_price": 100.0},
    {"account": "PEA", "name": "B", "ticker": "B", "cur": "€",
     "value_eur": 500.0, "pl_eur": 0.0, "buy_price": 100.0},
]
res = h.evaluate_all(lines)
s = h.summarize(res)
import config
# CASH PEA = 1745.45 dans la config réelle
check("total CTO = valeur (pas d'espèces)", approx(s["accounts"]["CTO"]["total"], 1000.0, 0.5))
check("PEA inclut les espèces de config.CASH",
      approx(s["accounts"]["PEA"]["total"], 500.0 + float(config.CASH.get("PEA", 0)), 0.5))
check("total global = somme des comptes",
      approx(s["grand"]["total"],
             s["accounts"]["CTO"]["total"] + s["accounts"]["PEA"]["total"], 0.5))


print(SEP)
print("5) FORMAT — le message Telegram se génère sans erreur")
msg = h.format_portfolio(res)
check("contient 'PORTEFEUILLE'", "PORTEFEUILLE" in msg)
check("contient 'TOTAL'", "TOTAL" in msg)
check("contient les 2 comptes", "CTO" in msg and "PEA" in msg)
print()
print(msg)


print(SEP)
print(f"RÉSULTAT : {ok} OK / {ko} KO")
if ko:
    raise SystemExit(1)
