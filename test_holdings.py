"""
test_holdings.py — Suivi temps réel (registre de parts) + transactions (sans réseau).

On mocke les cours et le taux de change. Lancer : python test_holdings.py
"""

import holdings as h
import transactions as t

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
d = h.derive({"value_eur": 3496.70, "pl_pct": -0.1258, "buy_price": 441.28})
check("cost_basis ≈ 4000 €", approx(d["cost_basis_eur"], 4000.0, 1.0))
check("ref_price ≈ 385.8", approx(d["ref_price"], 385.78, 0.5))
d = h.derive({"value_eur": 977.86, "pl_eur": -62.62, "buy_price": 80.04})
check("cost_basis = 1040.48 €", approx(d["cost_basis_eur"], 1040.48, 0.01))
check("ref_price ≈ 75.22", approx(d["ref_price"], 75.22, 0.2))


print(SEP)
print("2) SEED — registre en parts depuis le relevé (fx € par $ = 0.92)")
FX = 0.92
lines = [
    {"account": "CTO", "name": "Tesla", "ticker": "TSLA", "cur": "$",
     "value_eur": 3496.70, "pl_pct": -0.1258, "buy_price": 441.28},
    {"account": "PEA", "name": "Sanofi", "ticker": "SAN.PA", "cur": "€",
     "value_eur": 977.86, "pl_eur": -62.62, "buy_price": 80.04},
]
ledger = h.seed_ledger(lines, fx=FX)
tsla = ledger["CTO|TSLA"]
san = ledger["PEA|SAN.PA"]
# Sanofi : parts = 1040.48 (cost) / 75.22 (ref) ≈ 12.99 ; valeur au ref = relevé
check("Sanofi ≈ 13 parts", approx(san["shares"], 13.0, 0.1))
check("Sanofi fx = 1", san["fx"] == 1.0)
# Tesla $ : valeur au cours de réf (385.78) doit redonner le relevé (fx compris)
val_ref = tsla["shares"] * 385.78 * FX
check("Tesla : valeur au ref ≈ 3496.70 €", approx(val_ref, 3496.70, 1.0))
check("Tesla fx = 0.92", tsla["fx"] == FX)


print(SEP)
print("3) ÉVALUATION LIVE — Sanofi +10% depuis le relevé")
def fake_two(_tk):
    return 82.74, 80.00  # ref 75.22 -> +10% ; veille 80
h._last_two_closes = fake_two
r = h.evaluate_position(san)
check("position OK", r["ok"])
check("valeur ≈ 1076 €", approx(r["value_now"], 1075.6, 2.0))
check("P/L depuis achat > 0", r["pl_eur"] > 0)
check("variation jour ≈ +3.4%", approx(r["day_pct"] * 100, 3.42, 0.1))


print(SEP)
print("4) ACHAT — renforce une position existante (parts + coût)")
ledger2 = {"CTO|IONQ": {"account": "CTO", "name": "IonQ", "ticker": "IONQ",
                        "cur": "$", "shares": 2.0, "cost_eur": 90.0, "fx": 0.92}}
res = h.apply_transaction(ledger2, {
    "account": "CTO", "ticker": "IONQ", "action": "buy",
    "shares": 2.19756, "price_eur": 45.515, "total_eur": 101.02})
pos = ledger2["CTO|IONQ"]
check("achat OK", res["ok"])
check("parts cumulées ≈ 4.20", approx(pos["shares"], 4.19756, 0.001))
check("coût cumulé = 191.02 €", approx(pos["cost_eur"], 191.02, 0.01))


print(SEP)
print("5) ACHAT — nouvelle position $ : fx figé via le prix de la capture")
h._last_two_closes = lambda _tk: (50.0, 49.0)  # cours natif du moment
ledger3 = {}
h.apply_transaction(ledger3, {
    "account": "CTO", "ticker": "RXRX", "name": "Recursion", "cur": "$",
    "action": "buy", "shares": 10.0, "price_eur": 4.6, "total_eur": 46.0})
pos = ledger3["CTO|RXRX"]
check("nouvelle position créée", "CTO|RXRX" in ledger3)
check("fx figé = price_eur/natif = 0.092", approx(pos["fx"], 4.6 / 50.0, 0.001))
# valeur au cours du moment ≈ ce qu'il a payé
r = h.evaluate_position(pos)
check("valeur ≈ 46 € au cours du moment", approx(r["value_now"], 46.0, 0.5))


print(SEP)
print("6) VENTE — réduit parts et coût proportionnellement")
ledger4 = {"PEA|SOI.PA": {"account": "PEA", "name": "Soitec", "ticker": "SOI.PA",
                          "cur": "€", "shares": 2.0, "cost_eur": 315.60, "fx": 1.0}}
h.apply_transaction(ledger4, {
    "account": "PEA", "ticker": "SOI.PA", "action": "sell",
    "shares": 1.0, "price_eur": 113.0, "total_eur": 113.0})
pos = ledger4["PEA|SOI.PA"]
check("reste 1 part", approx(pos["shares"], 1.0, 0.001))
check("coût réduit de moitié ≈ 157.8 €", approx(pos["cost_eur"], 157.80, 0.1))


print(SEP)
print("7) NORMALISATION VISION — capture IonQ -> transaction")
fields = {"kind": "transaction", "action": "buy", "account": "Compte-Titres",
          "asset": "IonQ", "shares": 2.19756, "price_eur": 45.515,
          "fees_eur": 1.0, "total_eur": 101.02, "date": "2026-06-25"}
tx = t.normalize(fields)
check("ticker reconnu IONQ", tx and tx["ticker"] == "IONQ")
check("compte = CTO", tx and tx["account"] == "CTO")
check("action = buy", tx and tx["action"] == "buy")
check("total = 101.02 €", tx and approx(tx["total_eur"], 101.02, 0.01))


print(SEP)
print("8) GARDE-FOU — une transaction antérieure au relevé n'est pas recomptée")
check("25/06 < relevé 28/06 -> déjà comptée", t._predates_snapshot("2026-06-25") is True)
check("30/06 > relevé -> à appliquer", t._predates_snapshot("2026-06-30") is False)


print(SEP)
print(f"RÉSULTAT : {ok} OK / {ko} KO")
if ko:
    raise SystemExit(1)
