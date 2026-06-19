"""
test_advanced.py — Portefeuille + sentiment social + métriques backtest (sans réseau).

Lancer : python test_advanced.py
"""

import config
import portfolio
import social
import backtest_report as br

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


def pos(sector, pct):
    return {"sector": sector, "suggested_position_pct": pct, "closed": False, "is_paper": True}


print(SEP)
print("1. portfolio : nombre max de positions")
config.PORTFOLIO.update({"enabled": True, "max_concurrent": 3, "max_per_sector": 2,
                         "max_total_exposure_pct": 80, "max_sector_exposure_pct": 35})
full = [pos("Tech", 10), pos("Santé", 10), pos("Énergie", 10)]
r = portfolio.check_new_position("Banque", 10, full)
check("bloque si max positions atteint", r["allowed"] is False)

print(SEP)
print("2. portfolio : concentration sectorielle")
two_tech = [pos("Tech", 10), pos("Tech", 10)]
r = portfolio.check_new_position("Tech", 10, two_tech)
check("bloque la 3e position du même secteur", r["allowed"] is False and "Tech" in r["reason"])
r2 = portfolio.check_new_position("Santé", 10, two_tech)
check("autorise un autre secteur", r2["allowed"] is True)

print(SEP)
print("3. portfolio : réduction par exposition")
# exposition totale 75%, plafond 80% -> reste 5% -> position de 10% réduite à 5%
heavy = [pos("Tech", 30), pos("Santé", 25), pos("Énergie", 20)]
config.PORTFOLIO["max_concurrent"] = 8
config.PORTFOLIO["max_per_sector"] = 5
r = portfolio.check_new_position("Banque", 10, heavy)
check("réduit la taille au plafond d'expo (5%)", r["allowed"] is True and r["pos_pct"] == 5.0)
# secteur Tech déjà à 30%, plafond 35% -> reste 5%
r = portfolio.check_new_position("Tech", 10, heavy)
check("réduit par expo sectorielle", r["allowed"] is True and r["pos_pct"] == 5.0)

print(SEP)
print("4. portfolio : désactivable")
config.PORTFOLIO["enabled"] = False
r = portfolio.check_new_position("Tech", 10, two_tech * 5)
check("désactivé -> tout passe", r["allowed"] is True and r["pos_pct"] == 10)
config.PORTFOLIO["enabled"] = True

print(SEP)
print("5. social : score StockTwits (parsing local)")
# on court-circuite le réseau en testant la logique de score directement
s = social.sentiment_text({"score": 0.5, "bull": 9, "bear": 3, "n": 20})
check("texte haussier", "haussier" in s)
check("texte vide si pas de score", social.sentiment_text({"score": None}) == "")
check("symbole nettoie le suffixe", social._symbol("STMPA.PA") == "STMPA")

print(SEP)
print("6. backtest : métriques")
import datetime as dt
d = dt.date(2025, 1, 1)
dated = [(d, 0.10), (d, -0.05), (d, 0.20), (d, -0.08), (d, 0.04)]
m = br._metrics(dated)
check("nb trades", m["n"] == 5)
check("réussite 60%", abs(m["win_rate"] - 0.6) < 1e-9)
check("espérance correcte", abs(m["expectancy"] - (0.10-0.05+0.20-0.08+0.04)/5) < 1e-9)
# profit factor = (0.10+0.20+0.04) / (0.05+0.08) = 0.34/0.13
check("profit factor", abs(m["profit_factor"] - (0.34/0.13)) < 1e-6)
check("drawdown <= 0", m["max_drawdown_eur"] <= 0)
check("net = brut - frais", abs(m["net_eur"] - (m["gross_eur"] - 5*1000*br.FEE_RT)) < 1e-6)
check("aucun trade -> n=0", br._metrics([])["n"] == 0)

print(SEP)
print("7. backtest : rapport lisible")
txt = br.format_report(m, 3)
check("contient le verdict", "Verdict" in txt and "Profit factor" in txt)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
