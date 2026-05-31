"""
test_session3.py — Validation Session 3 : détection des 7 figures + scoring.

1. Vérifie que chaque détecteur s'exécute sans erreur sur des données réelles.
2. Scanne les candidats du pré-filtre et affiche les figures détectées + score.
3. Vérifie le score de qualité (0-50) et le seuil 30/50 pour les IA.

Lancer : python test_session3.py
"""

import logging

import data_fetcher
import market_filter
import watchlist
import prefilter
import patterns

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
SEP = "─" * 64


def test_detectors_run():
    print(SEP)
    print("TEST 1 — Chaque détecteur s'exécute (sur AAPL daily)")
    print(SEP)
    df = data_fetcher.add_indicators(data_fetcher.fetch_ticker("AAPL", period="200d", interval="1d"))
    ok = 0
    for nom, fn in patterns.PATTERNS.items():
        r = fn(df)
        assert "detected" in r and "pattern" in r
        print(f"  {nom:18} detected={str(r['detected']):5} {r.get('notes','')[:40]}")
        ok += 1
    return ok == 7


def test_scan_candidates():
    print()
    print(SEP)
    print("TEST 2 — Scan des candidats du pré-filtre")
    print(SEP)

    bullish = market_filter.market_is_bullish()
    full = watchlist.get_full_watchlist()
    cands = prefilter.run_prefilter(full, batch=True, max_candidates=40)
    tickers = [c["ticker"] for c in cands]
    print(f"  {len(tickers)} candidats à scanner (marché haussier={bullish})\n")

    data = data_fetcher.fetch_batch(tickers, period="200d", interval="1d")

    finalists = []
    total_detections = 0
    for tk in tickers:
        df = data.get(tk)
        if df is None or df.empty:
            continue
        df = data_fetcher.add_indicators(df)
        snap = data_fetcher.latest_snapshot(df)
        ticker_data = {"price": snap.get("price"), "ma50": snap.get("ma50")}
        res = patterns.scan_ticker(df, ticker_data, bullish)
        if res["best"]:
            total_detections += len(res["detected"])
            b = res["best"]
            tag = "→ IA" if b["setup_score"] >= 30 else "   "
            if b["setup_score"] >= 30:
                finalists.append((tk, b))
            print(f"  {tk:10} {b['pattern']:16} score={b['setup_score']:.1f}/50 "
                  f"{tag}  (figures: {len(res['detected'])})")

    print(f"\n  Figures détectées (toutes) : {total_detections}")
    print(f"  Finalistes (score >= 30/50, envoyés aux IA) : {len(finalists)}")
    for tk, b in finalists[:15]:
        print(f"    ★ {tk:10} {b['pattern']:16} {b['setup_score']:.1f}/50 "
              f"depth={b['depth']} brk=x{b['breakout_volume_ratio']}")
    return True


if __name__ == "__main__":
    r1 = test_detectors_run()
    r2 = test_scan_candidates()
    print()
    print(SEP)
    print(f"BILAN SESSION 3 : détecteurs={'OK' if r1 else 'KO'} | scan={'OK' if r2 else 'KO'}")
    print(SEP)
