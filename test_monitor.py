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


# Raccourci : _signal(typ, price, entry, rsi, ma20, ma50, ma200, ma50_rising, st_bull)
def sig(typ, price, entry, rsi, ma20, ma50, ma200, rising, st_bull=False):
    return m._signal(typ, price, entry, rsi, ma20, ma50, ma200, rising, st_bull=st_bull)[0]


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
print("3bis. confirmation court terme : ne pas vendre dans un rebond")
# spec : cassure MA50 MAIS dynamique court terme repart -> ATTENDRE (pas VENTE)
check("spec cassure MA50 + rebond 4h -> ATTENDRE",
      sig("spec", 95, 100, 50, 98, 100, 110, False, st_bull=True) == "WAIT")
# spec : même cassure SANS rebond court terme -> VENTE (comportement inchangé)
check("spec cassure MA50 sans rebond -> VENTE",
      sig("spec", 95, 100, 50, 98, 100, 110, False, st_bull=False) == "SELL")
# conviction : tendance cassée MAIS rebond 4h -> ATTENDRE
check("conviction tendance cassée + rebond 4h -> ATTENDRE",
      sig("conviction", 78, 90, 45, 82, 85, 80, False, st_bull=True) == "WAIT")
# conviction : take-profit/surchauffe reste prioritaire même avec rebond court terme
check("conviction RSI 80 + rebond 4h -> VENTE (surchauffe prioritaire)",
      sig("conviction", 120, 90, 80, 110, 100, 80, True, st_bull=True) == "SELL")
check("spec objectif atteint + rebond 4h -> VENTE (bénéfices prioritaires)",
      sig("spec", 116, 100, 30, 110, 108, 90, True, st_bull=True) == "SELL")

print(SEP)
print("4. config watchlist cohérente")
wl = config.WATCHLIST_MONITOR
check("13 valeurs surveillées", len(wl) == 13)
check("8 convictions", sum(1 for s in wl if s["type"] == "conviction") == 8)
check("5 spéculatives", sum(1 for s in wl if s["type"] == "spec") == 5)
# entry facultatif (valeurs en simple surveillance) ; s'il est présent, il est positif
check("prix d'achat positif quand renseigné",
      all((s.get("entry") is None) or (s["entry"] > 0) for s in wl))

print(SEP)
print("5. format bulletin (sans réseau)")
fake = [
    {"name": "LVMH", "cur": "€", "ok": True, "price": 480.0, "pnl": 0.01, "signal": "BUY",
     "reason": "repli sur la MA50"},
    {"name": "Soitec", "cur": "€", "ok": True, "price": 180.0, "pnl": 0.16, "signal": "SELL",
     "reason": "objectif atteint"},
    {"name": "Sanofi", "cur": "€", "ok": True, "price": 75.0, "pnl": -0.06, "signal": "WAIT",
     "reason": "cassure MA50 mais rebond court terme"},
    {"name": "Tesla", "cur": "$", "ok": True, "price": 400.0, "pnl": -0.12, "signal": "HOLD",
     "reason": "rien"},
]
b = m.format_bulletin(fake)
check("section achat présente", "À ACHETER" in b and "LVMH" in b)
check("section vente présente", "À VENDRE" in b and "Soitec" in b)
check("section surveillance présente", "SOUS SURVEILLANCE" in b and "Sanofi" in b)
check("conserver listé avec PV", "Tesla" in b and "-12%" in b)
check("ordre net ACHÈTE en tête de ligne", "ACHÈTE LVMH" in b)
check("ordre net VENDS en tête de ligne", "VENDS Soitec" in b)
check("ordre net ATTENDS en tête de ligne", "ATTENDS Sanofi" in b)

print(SEP)
print("6. avis IA : interprétation vs signal technique")
check("IA bullish + signal achat -> confirment", "confirment l'achat" in m._interpret("BUY", 80, 3))
check("IA contre + signal achat -> n'achète pas", "n'achète pas" in m._interpret("BUY", 30, 0))
check("IA bearish + signal vente -> confirment", "confirment" in m._interpret("SELL", 30, 0))
check("IA bullish + signal vente -> vendre la moitié", "la moitié" in m._interpret("SELL", 85, 3))
check("IA partagées + achat -> avis tranché quand même", "je maintiens l'achat" in m._interpret("BUY", 55, 1))
check("IA partagées + vente -> avis tranché quand même", "je maintiens la vente" in m._interpret("SELL", 55, 1))

print(SEP)
print("7. extraction de tickers d'un tweet")
import tweet as tw
check("extrait $NVDA $AMD (dédupliqué)",
      tw.extract_tickers("J'aime $NVDA et $AMD, surtout $NVDA") == ["NVDA", "AMD"])
check("aucun ticker -> liste vide", tw.extract_tickers("rien ici") == [])
check("gère les tickers à suffixe ($AIR.PA)", "AIR.PA" in tw.extract_tickers("$AIR.PA monte"))

print(SEP)
print("8. watchlist dynamique (suivre / ne plus suivre)")
check("resolve_ticker reconnaît un ticker", m.resolve_ticker("$NVDA") == "NVDA")
check("resolve_ticker garde le suffixe", m.resolve_ticker("AGP.MI") == "AGP.MI")
check("devise déduite du suffixe", m._cur_for("MC.PA") == "€" and m._cur_for("PLTR") == "$")
from memory import state as _state
_store = {}
_og, _os = _state.get_state, _state.set_state
_state.get_state = lambda k, default=None: _store.get(k, default)
_state.set_state = lambda k, v: _store.__setitem__(k, v)
try:
    n0 = len(m.get_watchlist())
    m.follow("$PLTR", "spec")
    check("follow ajoute la valeur", any(s["ticker"] == "PLTR" for s in m.get_watchlist()))
    check("watchlist +1", len(m.get_watchlist()) == n0 + 1)
    m.unfollow("TSLA")
    check("unfollow retire une valeur de config", not any(s["ticker"] == "TSLA" for s in m.get_watchlist()))
    m.follow("TSLA", "conviction")
    check("re-follow réintègre", any(s["ticker"] == "TSLA" for s in m.get_watchlist()))
finally:
    _state.get_state, _state.set_state = _og, _os

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
