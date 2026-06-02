"""
test_sector.py — Validation du clustering sectoriel (sans réseau ni DB).

Lancer : python test_sector.py
"""

import sector_cluster as SC

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
print("1. _tally : comptage, ignore n/d et None")
counts = SC._tally(["Technology", "Technology", "Healthcare", "n/d", None, "Technology"])
check("Technology compté 3 fois", counts.get("Technology") == 3)
check("Healthcare compté 1 fois", counts.get("Healthcare") == 1)
check("n/d et None ignorés", "n/d" not in counts and None not in counts)

print(SEP)
print("2. cluster_note : paliers")
check("1 signal -> pas de note", SC.cluster_note(1, "Technology") == "")
check("2 signaux -> confirmation", "confirmation" in SC.cluster_note(2, "Technology"))
check("3 signaux -> secteur qui décolle", "décolle" in SC.cluster_note(3, "Technology"))
check("secteur dans la note", "Technology" in SC.cluster_note(3, "Technology"))
check("secteur n/d -> pas de note", SC.cluster_note(3, "n/d") == "")
check("secteur None -> pas de note", SC.cluster_note(3, None) == "")

print(SEP)
print("3. breakdown_text : n'affiche que les clusters (>=2)")
txt = SC.breakdown_text({"Technology": 3, "Healthcare": 2, "Energy": 1})
check("Technology et Healthcare affichés", "Technology ×3" in txt and "Healthcare ×2" in txt)
check("Energy (isolé) masqué", "Energy" not in txt)
check("tri par fréquence (Techno avant Santé)",
      txt.index("Technology") < txt.index("Healthcare"))
check("aucun cluster -> vide", SC.breakdown_text({"Energy": 1, "Bank": 1}) == "")

print(SEP)
print("4. breakdown_from_signals : à partir de signaux")
signals = [
    {"ticker": "NVDA", "sector": "Technology"},
    {"ticker": "AMD", "sector": "Technology"},
    {"ticker": "PFE", "sector": "Healthcare"},
    {"ticker": "XOM", "sector": None},
]
bd = SC.breakdown_from_signals(signals)
check("cluster Technology détecté", "Technology ×2" in bd)
check("Healthcare isolé masqué", "Healthcare" not in bd)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
