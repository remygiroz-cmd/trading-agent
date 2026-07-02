"""
test_pepites.py — Validation du radar pépites (sans réseau).

Lancer : python test_pepites.py
"""

import numpy as np
import pandas as pd

import config
import pepites as pp

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


def make_df(n=60, base=100.0, ret5=0.0, vol_spike=1.0, rng_pct=0.06):
    """DataFrame synthétique : n bougies plates, puis un momentum sur 5 jours,
    un pic de volume sur la dernière bougie et une amplitude (ATR) contrôlée."""
    close = np.full(n, base)
    # rampe linéaire sur les 5 dernières bougies pour atteindre ret5
    for k in range(5):
        close[n - 5 + k] = base * (1 + ret5 * (k + 1) / 5)
    volume = np.full(n, 1_000_000.0)
    volume[-1] = 1_000_000.0 * vol_spike
    high = close * (1 + rng_pct / 2)
    low = close * (1 - rng_pct / 2)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": close, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)


print(SEP)
print("1. evaluate : métriques calculées sur la dernière bougie")
df = make_df(ret5=0.08, vol_spike=2.0, rng_pct=0.06)
m = pp.evaluate(df)
check("métriques présentes", m is not None)
check("vol_ratio ≈ 2", m and abs(m["vol_ratio"] - 2.0) < 0.15)
check("ret5 ≈ +8%", m and abs(m["ret5"] - 0.08) < 0.01)
check("atr_pct ≈ 6%", m and abs(m["atr_pct"] - 0.06) < 0.015)
check("données insuffisantes -> None", pp.evaluate(make_df(n=10)) is None)

print(SEP)
print("2. passes : seuils du signal explosif")
strong = pp.evaluate(make_df(ret5=0.08, vol_spike=2.0, rng_pct=0.06))
flat = pp.evaluate(make_df(ret5=0.01, vol_spike=1.0, rng_pct=0.02))
no_vol = pp.evaluate(make_df(ret5=0.08, vol_spike=1.0, rng_pct=0.06))
check("volume x2 + momentum 8% + ATR 6% -> déclenche", pp.passes(strong))
check("valeur plate -> ne déclenche pas", not pp.passes(flat))
check("momentum sans volume -> ne déclenche pas", not pp.passes(no_vol))
check("None -> ne déclenche pas", not pp.passes(None))

print(SEP)
print("3. plan de trade : stop et objectif bornés")
p = pp.plan(100.0, atr=4.0)  # 1.5x4=6% stop, 3x4=12% objectif
check("stop ≈ 94", abs(p["stop"] - 94.0) < 0.5)
check("objectif ≈ 112", abs(p["target"] - 112.0) < 0.5)
p2 = pp.plan(100.0, atr=0.5)  # 0.75% -> borné à min_stop_pct (4%)
check("stop borné au minimum 4%", abs(p2["stop_pct"] - config.RISK["min_stop_pct"]) < 1e-9)
p3 = pp.plan(100.0, atr=20.0)  # 30% stop -> borné à 15% ; 60% objectif -> borné à 45%
check("stop borné au maximum 15%", abs(p3["stop_pct"] - config.RISK["max_stop_pct"]) < 1e-9)
check("objectif borné à 45%", abs(p3["target_pct"] - config.RISK["max_target_pct"]) < 1e-9)

print(SEP)
print("4. select : priorité PEA puis score")
cands = [
    {"ticker": "NVDA", "market": "US", "score": 9.0},
    {"ticker": "ALKAL.PA", "market": "EU", "score": 2.0},
    {"ticker": "SOI.PA", "market": "EU", "score": 3.0},
    {"ticker": "PLTR", "market": "US", "score": 8.0},
]
sel = pp.select(cands, top_n=3, pea_first=True)
check("les PEA passent devant malgré un score plus faible",
      [c["ticker"] for c in sel] == ["SOI.PA", "ALKAL.PA", "NVDA"])
sel2 = pp.select(cands, top_n=2, pea_first=False)
check("sans priorité PEA : tri par score pur",
      [c["ticker"] for c in sel2] == ["NVDA", "PLTR"])

print(SEP)
print("5. format du message")
pick = {"ticker": "SOI.PA", "market": "EU", "price": 100.0, "vol_ratio": 2.1,
        "ret5": 0.08, "atr_pct": 0.06, "score": 2.27, "plan": pp.plan(100.0, 4.0)}
msg = pp.format_message([pick])
check("ordre net ACHÈTE présent", "ACHÈTE SOI.PA" in msg)
check("tag PEA présent", "PEA" in msg)
check("stop et objectif présents", "Stop" in msg and "Objectif" in msg)
check("avertissement stop obligatoire", "OBLIGATOIRE" in msg)
msg_vide = pp.format_message([])
check("aucun pick -> message honnête", "Rien de convaincant" in msg_vide)
msg_bear = pp.format_message([], market_reason="SPX sous MA50")
check("marché défavorable -> rien proposé", "Rien aujourd'hui" in msg_bear)

print(SEP)
print("6. config cohérente")
check("PEPITES activé", config.PEPITES["enabled"] is True)
check("top_n raisonnable (1-5)", 1 <= config.PEPITES["top_n"] <= 5)
check("cooldown en jours > 0", config.PEPITES["cooldown_days"] > 0)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
