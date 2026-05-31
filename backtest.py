"""
backtest.py — Validation historique de la partie ALGORITHMIQUE.

Rejoue sur l'historique : pré-filtre + détection des 7 figures + score de
qualité, puis simule la sortie (objectif / stop / horizon) sur les bougies
FUTURES (sans look-ahead à la détection). Mesure, par figure et par tranche de
score, le taux de réussite et l'espérance de gain.

Le débat des 3 IA n'est PAS rejoué (coût prohibitif sur des milliers de signaux) :
on valide ici l'édge de la détection, c.-à-d. la base sur laquelle les IA votent.

Hypothèses de sortie (ajustables en bas) : objectif +12%, stop -6%, horizon 10 j.
On filtre comme en prod : on ne prend un signal que si le marché est haussier
(S&P 500 au-dessus de sa MA50 ce jour-là). Trades non chevauchants par ticker.

Lancer : python backtest.py [annees]   (défaut 2)
"""

import sys
import logging

import pandas as pd

import config
import data_fetcher
import patterns
import watchlist

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backtest")

# Hypothèses de trade (mêmes pour toutes les figures, pour comparer équitablement)
TARGET_PCT = 0.12
STOP_PCT = 0.06
HORIZON = 10
WARMUP = 60          # bougies minimum avant de commencer à détecter
MIN_SETUP = config.ALERT_RULES["min_setup_score"]   # 30/50


def _simulate_forward(entry: float, future: pd.DataFrame):
    """Simule la sortie sur les bougies futures. Retourne (pct, raison, jours)."""
    target = entry * (1 + TARGET_PCT)
    stop = entry * (1 - STOP_PCT)
    for d, (_, row) in enumerate(future.iterrows(), start=1):
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        if lo <= stop:                      # stop prioritaire (prudence)
            return -STOP_PCT, "stop", d
        if hi >= target:
            return TARGET_PCT, "objectif", d
        if d >= HORIZON:
            return (close - entry) / entry, "horizon", d
    if len(future):
        last = float(future.iloc[-1]["close"])
        return (last - entry) / entry, "horizon", len(future)
    return None


def _market_regime(years: int) -> dict:
    """Dict date(str) -> True si S&P 500 > MA50 ce jour-là."""
    spx = data_fetcher.fetch_ticker("^GSPC", period=f"{years+1}y", interval="1d")
    if spx.empty:
        return {}
    ma = spx["close"].rolling(50).mean()
    bullish = spx["close"] >= ma
    return {d.strftime("%Y-%m-%d"): bool(v) for d, v in bullish.items()}


def backtest_ticker(ticker: str, df: pd.DataFrame, regime: dict,
                    spx_by_date: dict | None = None) -> list[dict]:
    """Backtest un ticker. Retourne la liste des trades simulés."""
    if df.empty or len(df) < WARMUP + HORIZON + 5:
        return []
    spx_by_date = spx_by_date or {}
    rs_lookback = config.RELATIVE_STRENGTH["lookback_days"]
    rs_enabled = config.RELATIVE_STRENGTH["enabled"]
    df = data_fetcher.add_indicators(df)
    trades = []
    next_allowed = WARMUP

    closes = df["close"].values
    ma20 = df["ma20"].values
    vol = df["volume"].values
    volavg = df["vol_avg20"].values

    n = len(df)
    for i in range(WARMUP, n - 1):
        if i < next_allowed:
            continue
        # Gate "pré-filtre" léger (sans recalcul d'indicateurs)
        price = closes[i]
        if pd.isna(ma20[i]) or price < ma20[i]:
            continue
        if i >= 6:
            var5 = (price - closes[i - 5]) / closes[i - 5]
        else:
            continue
        if var5 < config.PREFILTER_CRITERIA["min_variation_5d"]:
            continue
        if pd.isna(volavg[i]) or volavg[i] <= 0 or vol[i] / volavg[i] < config.PREFILTER_CRITERIA["min_volume_ratio"]:
            continue
        if volavg[i] < config.PREFILTER_CRITERIA["min_avg_volume"] or price < config.PREFILTER_CRITERIA["min_price"]:
            continue

        # Régime marché (comme en prod)
        date_str = df.index[i].strftime("%Y-%m-%d")
        bullish = regime.get(date_str, True)
        if not bullish:
            continue

        # #3 Force relative : le titre doit surperformer le S&P sur lookback
        if rs_enabled and i >= rs_lookback:
            prev_date = df.index[i - rs_lookback].strftime("%Y-%m-%d")
            spx_now, spx_prev = spx_by_date.get(date_str), spx_by_date.get(prev_date)
            if spx_now and spx_prev and spx_prev > 0:
                stock_ret = (price - closes[i - rs_lookback]) / closes[i - rs_lookback]
                mkt_ret = (spx_now - spx_prev) / spx_prev
                if (stock_ret - mkt_ret) < config.RELATIVE_STRENGTH["min_outperformance"]:
                    continue

        # Détection des figures sur la fenêtre jusqu'à i (pas de look-ahead)
        window = df.iloc[: i + 1]
        scan = patterns.scan_ticker(window, {"price": price, "ma50": df["ma50"].values[i]}, bullish)
        best = scan["best"]
        if not best or best.get("setup_score", 0) < MIN_SETUP:
            continue

        # Simulation de la sortie sur les bougies futures
        future = df.iloc[i + 1:]
        sim = _simulate_forward(price, future)
        if not sim:
            continue
        pct, reason, days = sim
        trades.append({
            "ticker": ticker, "date": date_str, "pattern": best["pattern"],
            "setup_score": round(best["setup_score"], 1), "entry": round(price, 2),
            "result_pct": round(pct, 4), "exit_reason": reason, "hold_days": days,
        })
        next_allowed = i + days  # pas de chevauchement sur ce ticker

    return trades


def summarize(trades: list[dict]) -> None:
    if not trades:
        print("Aucun trade simulé.")
        return
    df = pd.DataFrame(trades)
    n = len(df)
    wr = (df["result_pct"] > 0).mean()
    avg = df["result_pct"].mean()
    exp = avg  # espérance par trade (déjà la moyenne des résultats)
    print(f"\n{'='*64}\nRÉSULTAT GLOBAL : {n} trades")
    print(f"  Taux de réussite : {wr*100:.1f}%")
    print(f"  Gain moyen/trade : {avg*100:+.2f}%  (espérance)")
    print(f"  Gain médian      : {df['result_pct'].median()*100:+.2f}%")
    print(f"  Meilleur / pire  : {df['result_pct'].max()*100:+.1f}% / {df['result_pct'].min()*100:+.1f}%")

    print(f"\nPAR FIGURE :")
    g = df.groupby("pattern")["result_pct"]
    table = pd.DataFrame({
        "trades": g.count(),
        "réussite_%": (df.groupby("pattern")["result_pct"].apply(lambda s: (s > 0).mean()) * 100).round(1),
        "gain_moy_%": (g.mean() * 100).round(2),
    }).sort_values("gain_moy_%", ascending=False)
    print(table.to_string())

    print(f"\nPAR TRANCHE DE SCORE SETUP :")
    df["bande"] = pd.cut(df["setup_score"], [29, 35, 40, 45, 50],
                         labels=["30-35", "35-40", "40-45", "45-50"])
    gb = df.groupby("bande", observed=True)["result_pct"]
    tb = pd.DataFrame({
        "trades": gb.count(),
        "réussite_%": (df.groupby("bande", observed=True)["result_pct"].apply(lambda s: (s > 0).mean()) * 100).round(1),
        "gain_moy_%": (gb.mean() * 100).round(2),
    })
    print(tb.to_string())

    print(f"\nPAR RAISON DE SORTIE :")
    print(df["exit_reason"].value_counts().to_string())

    df.to_csv("backtest_results.csv", index=False)
    print(f"\nDétail complet -> backtest_results.csv")
    print("="*64)


def run_backtest(tickers: list[str], years: int = 2) -> None:
    print(f"Backtest sur {len(tickers)} tickers, {years} an(s) "
          f"(objectif +{TARGET_PCT*100:.0f}%, stop -{STOP_PCT*100:.0f}%, horizon {HORIZON}j)")
    print("Hypothèse : signaux pris uniquement quand S&P > MA50.\n")
    regime = _market_regime(years)
    spx = data_fetcher.fetch_ticker(config.RELATIVE_STRENGTH["market_ticker"],
                                    period=f"{years+1}y", interval="1d")
    spx_by_date = {d.strftime("%Y-%m-%d"): float(c) for d, c in spx["close"].items()} if not spx.empty else {}
    if config.RELATIVE_STRENGTH["enabled"]:
        print("Filtre force relative ACTIVÉ (titre doit surperformer le S&P).\n")

    data = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")
    all_trades = []
    for tk in tickers:
        df = data.get(tk)
        if df is None or df.empty:
            continue
        t = backtest_ticker(tk, df, regime, spx_by_date)
        all_trades.extend(t)
        if t:
            wr = sum(1 for x in t if x["result_pct"] > 0) / len(t)
            print(f"  {tk:10} : {len(t):3} trades, réussite {wr*100:.0f}%")
    summarize(all_trades)


if __name__ == "__main__":
    years = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    # Par défaut : watchlist fixe (40). Pour un test plus large, passer plus de tickers.
    tickers = watchlist.get_fixed_watchlist()
    run_backtest(tickers, years=years)
