"""
test_analyse.py — Validation du moteur de verdict /analyse (sans réseau).

Lancer : python test_analyse.py
"""

import analyse as an
from alerts import price_alerts as pa

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


# Raccourci : _verdict(price, rsi, ma20, ma50, ma200, ma50_rising, macd_bull, st_bull)
def v(price, rsi, ma20, ma50, ma200, rising, macd=False, st=False):
    return an._verdict(price, rsi, ma20, ma50, ma200, rising, macd, st)


print(SEP)
print("1. verdicts en tendance haussière")
# survendu en tendance haussière -> ACHÈTE
code, lvl, _ = v(100, 30, 102, 101, 90, True)
check("RSI 30 + tendance haussière -> ACHÈTE MAINTENANT", code == "BUY_NOW")
# repli sur la MA50 -> ACHÈTE
code, lvl, _ = v(100, 50, 103, 100.5, 90, True)
check("repli sur MA50 -> ACHÈTE MAINTENANT", code == "BUY_NOW")
# suracheté -> ATTENDS un repli (niveau = MA20 sous le prix)
code, lvl, _ = v(120, 75, 112, 105, 90, True)
check("RSI 75 -> ATTENDS", code == "WAIT_PULLBACK")
check("niveau d'attente = MA20", lvl == 112)
# très étiré au-dessus de la MA50 -> ATTENDS
code, lvl, _ = v(120, 60, 113, 105, 90, True)
check("+14% au-dessus MA50 -> ATTENDS le repli", code == "WAIT_PULLBACK")
# tendance saine + momentum -> ACHÈTE
code, lvl, _ = v(107, 55, 105, 103, 90, True, macd=True)
check("momentum sain (MACD) -> ACHÈTE MAINTENANT", code == "BUY_NOW")
# tendance saine mais momentum mou -> ATTENDS sur MA50
code, lvl, _ = v(107, 55, 105, 103, 90, True, macd=False, st=False)
check("momentum mou -> ATTENDS sur la MA50", code == "WAIT_PULLBACK" and lvl == 103)

print(SEP)
print("2. verdicts en tendance baissière")
# baissier + rebond court terme -> ATTENDS la reprise de la MA50
code, lvl, _ = v(95, 45, 97, 100, 110, False, st=True)
check("baissier + rebond 4h -> ATTENDS la reprise MA50", code == "WAIT_RECLAIM" and lvl == 100)
# baissier sans rebond -> N'ACHÈTE PAS
code, lvl, _ = v(95, 45, 97, 100, 110, False, st=False)
check("baissier sans rebond -> N'ACHÈTE PAS", code == "NO_BUY")

print(SEP)
print("3. résolution des noms (alias, sans réseau)")
al = an._aliases()
check("sanofi -> SAN.PA", al.get("sanofi") == "SAN.PA")
check("hermès -> RMS.PA", al.get("hermès") == "RMS.PA")
check("google -> GOOGL", al.get("google") == "GOOGL")
check("schneider -> SU.PA", al.get("schneider") == "SU.PA")
check("nvidia -> NVDA", al.get("nvidia") == "NVDA")

print(SEP)
print("4. format du message")
tech = {"atr": 3.0, "trend_txt": "tendance haussière", "rsi_txt": "57",
        "macd_txt": "haussier", "st_txt": "dynamique qui repart",
        "ma20_txt": "74,10€", "ma50_txt": "76,20€", "support_txt": "72,00€"}
m1 = an.format_analysis("SAN.PA", "Sanofi", "€", 75.0, "BUY_NOW", 75.0,
                        "tendance haussière et momentum sain", tech, [])
check("verdict ACHÈTE net", "VERDICT : ACHÈTE MAINTENANT" in m1)
check("plan complet présent", "stop" in m1 and "objectif" in m1)
m2 = an.format_analysis("SAN.PA", "Sanofi", "€", 75.0, "WAIT_PULLBACK", 71.5,
                        "suracheté", tech, [])
check("verdict ATTENDS avec prix précis", "ATTENDS — achète vers 71.50€" in m2)
check("alerte auto annoncée", "Je te préviens automatiquement" in m2)
m3 = an.format_analysis("SAN.PA", "Sanofi", "€", 75.0, "WAIT_RECLAIM", 76.2,
                        "tendance pas réparée", tech, [])
check("verdict reprise : achat conditionnel", "SEULEMENT si ça repasse 76.20€" in m3)
m4 = an.format_analysis("SAN.PA", "Sanofi", "€", 75.0, "NO_BUY", 76.2,
                        "tendance baissière", tech, [])
check("verdict N'ACHÈTE PAS net", "VERDICT : N'ACHÈTE PAS" in m4)
check("niveau d'invalidation donné", "76.20€" in m4)

print(SEP)
print("5. alertes dynamiques : cycle de vie (sans réseau)")
saved = {}
pa._load_dynamic = lambda: saved.get("rules", [])
pa._save_dynamic = lambda rules: saved.update({"rules": rules})
pa.add_dynamic("Sanofi", "SAN.PA", 71.5, "below", "€", "touche le prix visé")
check("alerte posée", len(saved["rules"]) == 1 and saved["rules"][0]["level"] == 71.5)
pa.add_dynamic("Sanofi", "SAN.PA", 70.0, "below", "€", "nouveau niveau")
check("remplacée (pas dupliquée) sur même ticker+sens", len(saved["rules"]) == 1
      and saved["rules"][0]["level"] == 70.0)
pa.add_dynamic("Sanofi", "SAN.PA", 76.2, "above", "€", "reprise")
check("sens opposé = alerte distincte", len(saved["rules"]) == 2)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
