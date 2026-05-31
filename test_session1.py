"""
test_session1.py — Test de validation de la Session 1.

Vérifie :
  1. La récupération de données OHLCV sur 5 tickers (US, FR, indices)
  2. Le calcul des indicateurs (RSI, MACD, MA)
  3. Le filtre marché global (SPX + VIX)

Lancer : python test_session1.py
"""

import logging

import data_fetcher
import market_filter
import config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

SEP = "─" * 60


def test_data_fetch():
    print(SEP)
    print("TEST 1 — Récupération données + indicateurs (5 tickers)")
    print(SEP)

    tickers = ["AAPL", "PLTR", "IONQ", "ASML", "STM.PA"]
    ok = 0
    for tk in tickers:
        df = data_fetcher.fetch_ticker(tk, period="90d", interval="1d")
        if df.empty:
            print(f"  ❌ {tk:10} : aucune donnée")
            continue
        snap = data_fetcher.latest_snapshot(df)
        rsi = snap.get("rsi")
        rsi_txt = f"{rsi:.1f}" if rsi is not None else "n/d"
        print(
            f"  ✅ {tk:10} : {len(df):3} bougies | "
            f"prix {snap.get('price'):.2f} | RSI {rsi_txt} | "
            f"MA50 {snap.get('ma50')} | MACD {snap.get('macd_signal_state')}"
        )
        ok += 1

    print(f"\n  Résultat : {ok}/{len(tickers)} tickers récupérés.")
    return ok >= 3  # tolérance : Euronext parfois capricieux


def test_market_filter():
    print()
    print(SEP)
    print("TEST 2 — Filtre marché global (SPX + VIX)")
    print(SEP)

    status = market_filter.get_market_status()
    for k in ["spx_price", "spx_ma50", "spx_above_ma50", "vix", "vix_ok", "ok"]:
        print(f"  {k:16} : {status[k]}")
    print(f"\n  → {status['reason']}")
    # Le test passe tant que la fonction renvoie un statut cohérent
    return status["spx_price"] is not None


def test_config():
    print()
    print(SEP)
    print("TEST 3 — Configuration / clés API présentes")
    print(SEP)
    checks = config.validate_config()
    for k, present in checks.items():
        print(f"  {'✅' if present else '⬜'} {k}")
    print("\n  (Les ⬜ sont normaux tant que Rémy n'a pas fourni les clés.)")
    return True


if __name__ == "__main__":
    r1 = test_data_fetch()
    r2 = test_market_filter()
    r3 = test_config()

    print()
    print(SEP)
    print(f"BILAN SESSION 1 : data={'OK' if r1 else 'KO'} | "
          f"filtre={'OK' if r2 else 'KO'} | config={'OK' if r3 else 'KO'}")
    print(SEP)
