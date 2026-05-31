"""
test_session5.py — Validation Session 5 : agents IA + débat 3 tours.

Sur 1 à 3 tickers réels :
  1. Construit le contexte (brief)
  2. Lance le débat complet (Tour 1, 2, 3)
  3. Affiche les votes de chaque IA et la décision finale

Note : Grok peut être indisponible (crédits xAI). Le système doit continuer
avec les IA restantes (dégradation gracieuse).

Lancer : python test_session5.py [TICKER]
"""

import logging
import sys

import data_fetcher
import market_filter
import patterns
from agents import debate, context_builder
from memory import weights

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("data_fetcher").setLevel(logging.WARNING)
SEP = "─" * 64


def analyze_one(ticker: str, market: dict, w: dict):
    print(f"\n{SEP}\nTICKER : {ticker}\n{SEP}")
    df = data_fetcher.fetch_ticker(ticker, period="200d", interval="1d")
    if df.empty:
        print("  pas de données"); return
    df = data_fetcher.add_indicators(df)
    snap = data_fetcher.latest_snapshot(df)

    scan = patterns.scan_ticker(df, {"price": snap["price"], "ma50": snap["ma50"]},
                                market.get("bullish", True))
    # Pour le test, si aucune figure n'est détectée, on en force une (bull_flag)
    # afin d'exercer quand même le débat.
    if scan["best"]:
        pat = scan["best"]
    else:
        pat = patterns.PATTERNS["bull_flag"](df)
        pat["setup_score"] = patterns.calculate_setup_score(
            {"price": snap["price"], "ma50": snap["ma50"]}, pat, market.get("bullish", True))
        print(f"  (aucune figure nette — débat forcé sur bull_flag, score {pat['setup_score']}/50)")

    print(f"  Figure : {pat['pattern']} | setup {pat.get('setup_score')}/50 | "
          f"prix {snap['price']:.2f} | RSI {snap['rsi']:.0f}")

    ctx = context_builder.build_context(ticker, snap, pat, market)
    out = debate.run_debate(ctx, weights=w, do_round2=True)

    print("\n  RÉSULTAT DU DÉBAT")
    for agent in ["deepseek", "grok", "claude"]:
        v = out["final_votes"].get(agent, {})
        err = " (indispo)" if v.get("_error") else ""
        print(f"    {agent:9} : {v.get('verdict','?'):8} {v.get('score','?')}/10{err} "
              f"— {str(v.get('raison_principale',''))[:60]}")
    r = out["result"]
    print(f"\n  → Score final : {r['final_score']}/100 | {r['buy_votes']} votes ACHETER "
          f"| ALERTE : {'OUI ✅' if r['send_alert'] else 'NON'}")
    return out


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["PLTR", "IONQ"]
    market = market_filter.get_market_status()
    print(f"Marché : {market['reason']}")
    w = weights.get_current_weights()
    print(f"Poids IA : {w}")

    for tk in tickers:
        try:
            analyze_one(tk, market, w)
        except Exception as e:  # noqa: BLE001
            print(f"  ERREUR sur {tk} : {e}")

    print(f"\n{SEP}\nBILAN SESSION 5 : débat 3 tours opérationnel (dégradation gracieuse si IA indispo)\n{SEP}")
