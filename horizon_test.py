"""
horizon_test.py — Effet de la durée de détention sur les résultats.

Mêmes signaux d'entrée que le système (préfiltre + force relative + figures
score>=35), mais on évalue chaque trade sous plusieurs horizons :
  ~2 semaines (10 j), 1 mois (21 j), 2 mois (42 j), 3 mois (63 j).

Deux modes de sortie :
  A) ATR : stop/objectif calés sur la volatilité, avec plus de temps pour se déclencher
  B) HOLD : conservation pure — on vend pile à N jours, sans stop ni objectif

Lancer : python horizon_test.py [annees]
"""

import sys
import logging

import numpy as np
import pandas as pd

import config
import data_fetcher
import patterns
import watchlist
import market_context

logging.basicConfig(level=logging.ERROR)

HORIZONS = [10, 21, 42, 63]
LABELS = {10: "~2 sem", 21: "1 mois", 42: "2 mois", 63: "3 mois"}
MIN_SETUP = config.ALERT_RULES["min_setup_score"]
STAKE = 1000
FEE_RT = 0.004


def collect_signals(df, regime, spx_by_date):
    df = data_fetcher.add_indicators(df)
    c = df["close"].values; ma20 = df["ma20"].values; ma50 = df["ma50"].values
    vol = df["volume"].values; volavg = df["vol_avg20"].values; atrp = df["atr_pct"].values
    rs_lb = config.RELATIVE_STRENGTH["lookback_days"]
    n = len(df); sigs = []; next_allowed = 60
    for i in range(60, n - 1):
        if i < next_allowed:
            continue
        price = c[i]
        if pd.isna(ma20[i]) or price < ma20[i] or i < 6:
            continue
        if (price - c[i - 5]) / c[i - 5] < config.PREFILTER_CRITERIA["min_variation_5d"]:
            continue
        if pd.isna(volavg[i]) or volavg[i] <= 0 or vol[i] / volavg[i] < config.PREFILTER_CRITERIA["min_volume_ratio"]:
            continue
        if volavg[i] < config.PREFILTER_CRITERIA["min_avg_volume"] or price < config.PREFILTER_CRITERIA["min_price"]:
            continue
        date_str = df.index[i].strftime("%Y-%m-%d")
        if not regime.get(date_str, True):
            continue
        if i >= rs_lb:
            pds = df.index[i - rs_lb].strftime("%Y-%m-%d")
            sn, sp = spx_by_date.get(date_str), spx_by_date.get(pds)
            if sn and sp and sp > 0:
                if (price - c[i - rs_lb]) / c[i - rs_lb] - (sn - sp) / sp < config.RELATIVE_STRENGTH["min_outperformance"]:
                    continue
        scan = patterns.scan_ticker(df.iloc[: i + 1], {"price": price, "ma50": ma50[i]}, True)
        best = scan["best"]
        if not best or best.get("setup_score", 0) < MIN_SETUP:
            continue
        sigs.append((i, price, atrp[i] if not pd.isna(atrp[i]) else None))
        next_allowed = i + 10   # cooldown fixe -> mêmes signaux pour tous les horizons
    return df, sigs


def eval_atr(df, i, entry, atr_pct, horizon):
    future = df.iloc[i + 1:]
    lv = market_context.compute_levels(entry, atr_pct)
    target, stop = lv["target"], lv["stop"]
    for d, (_, row) in enumerate(future.iterrows(), start=1):
        if float(row["low"]) <= stop:
            return (stop - entry) / entry
        if float(row["high"]) >= target:
            return (target - entry) / entry
        if d >= horizon:
            return (float(row["close"]) - entry) / entry
    return (float(future.iloc[-1]["close"]) - entry) / entry if len(future) else None


def eval_hold(df, i, entry, horizon):
    future = df.iloc[i + 1:]
    if len(future) >= horizon:
        return (float(future.iloc[horizon - 1]["close"]) - entry) / entry
    return (float(future.iloc[-1]["close"]) - entry) / entry if len(future) else None


def main(years=2):
    tickers = watchlist.get_full_watchlist()
    print(f"Test des horizons — {len(tickers)} tickers, {years} ans, {STAKE}€/trade\n")
    spx = data_fetcher.fetch_ticker("^GSPC", period=f"{years+1}y", interval="1d")
    regime, spx_by_date = {}, {}
    if not spx.empty:
        ma = spx["close"].rolling(50).mean()
        regime = {d.strftime("%Y-%m-%d"): bool(x) for d, x in (spx["close"] >= ma).items()}
        spx_by_date = {d.strftime("%Y-%m-%d"): float(x) for d, x in spx["close"].items()}

    data = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")
    all_sigs = []
    for tk, df in data.items():
        if df is None or df.empty or len(df) < 80:
            continue
        d2, sigs = collect_signals(df, regime, spx_by_date)
        all_sigs.append((d2, sigs))

    total = sum(len(s) for _, s in all_sigs)
    print(f"Signaux d'entrée détectés : {total}\n")

    def summarize(results, title):
        r = [x for x in results if x is not None]
        if not r:
            print(f"{title}: aucun"); return
        arr = np.array(r); n = len(arr)
        wr = (arr > 0).mean() * 100
        avg = arr.mean() * 100
        net = arr.sum() * STAKE - n * STAKE * FEE_RT
        print(f"  {title:9} | trades {n:4} | réussite {wr:4.1f}% | gain moy {avg:+5.2f}%/trade | net {net:+8,.0f} €")

    print("="*78)
    print("MODE A — stop/objectif ATR (plus de temps pour se déclencher)")
    print("="*78)
    for h in HORIZONS:
        res = [eval_atr(df, i, e, a, h) for df, sigs in all_sigs for (i, e, a) in sigs]
        summarize(res, LABELS[h])

    print("\n" + "="*78)
    print("MODE B — conservation pure (vendu pile à l'échéance, sans stop)")
    print("="*78)
    for h in HORIZONS:
        res = [eval_hold(df, i, e, h) for df, sigs in all_sigs for (i, e, a) in sigs]
        summarize(res, LABELS[h])


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
