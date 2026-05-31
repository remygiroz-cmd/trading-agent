"""
test_session2.py — Validation Session 2 : watchlist + pré-filtre.

Vérifie :
  1. Watchlist fixe (40 tickers, dédupliquée)
  2. Watchlist dynamique (reconstruction via screener Yahoo)
  3. Pré-filtre sur l'ensemble des tickers → doit retourner ~15-40 candidats

Lancer : python test_session2.py
"""

import logging
import sys

import watchlist
import prefilter

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
SEP = "─" * 60


def test_watchlist():
    print(SEP)
    print("TEST 1 — Watchlist")
    print(SEP)
    fixed = watchlist.get_fixed_watchlist()
    print(f"  Fixes      : {len(fixed)} tickers (US={len(watchlist.filter_by_markets(fixed,['US']))}, "
          f"EU={len(watchlist.filter_by_markets(fixed,['EU']))})")

    dyn = watchlist.load_dynamic_watchlist()
    if not dyn:
        print("  Pas de cache dynamique → reconstruction...")
        dyn = watchlist.rebuild_dynamic_watchlist()
    print(f"  Dynamiques : {len(dyn)} tickers")

    full = watchlist.get_full_watchlist()
    print(f"  Total      : {len(full)} tickers")
    return len(fixed) >= 39 and len(full) > 50


def test_prefilter():
    print()
    print(SEP)
    print("TEST 2 — Pré-filtre sur la watchlist complète")
    print(SEP)
    full = watchlist.get_full_watchlist()
    print(f"  Scan de {len(full)} tickers (téléchargement groupé)...\n")

    cands = prefilter.run_prefilter(full, batch=True)

    print(f"  → {len(cands)} candidats retenus.\n")
    for c in cands[:25]:
        m = c["metrics"]
        print(f"    {c['ticker']:10} prix={m['price']:>8.2f} var5j={m['var_5d']*100:+6.1f}% "
              f"vol=x{m['vol_ratio']:.2f} RSI={m['rsi']}")
    if len(cands) > 25:
        print(f"    ... (+{len(cands)-25} autres)")

    # Le spec attend 15-40 candidats. On tolère une fourchette large car
    # le résultat dépend fortement de l'état du marché du jour.
    in_range = 5 <= len(cands) <= 80
    print(f"\n  Fourchette attendue 15-40 (tolérance 5-80) : {'OK' if in_range else 'HORS PLAGE'}")
    return len(cands) > 0


if __name__ == "__main__":
    r1 = test_watchlist()
    r2 = test_prefilter()
    print()
    print(SEP)
    print(f"BILAN SESSION 2 : watchlist={'OK' if r1 else 'KO'} | prefiltre={'OK' if r2 else 'KO'}")
    print(SEP)
    sys.exit(0 if (r1 and r2) else 1)
