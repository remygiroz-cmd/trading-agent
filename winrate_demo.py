"""
winrate_demo.py — Démonstration : taux de réussite élevé != stratégie gagnante.

Mêmes signaux d'entrée que le système, mais on teste plusieurs réglages de
sortie pour montrer que :
  - on peut atteindre un TAUX DE RÉUSSITE très élevé avec un objectif minuscule
    et un stop énorme... au prix de pertes catastrophiques (espérance < 0)
  - ce qui compte vraiment, c'est le gain moyen par trade et le pire cas.

Lancer : python winrate_demo.py [annees]
"""

import sys
import logging

import numpy as np

import config
import data_fetcher
import watchlist
import market_context
from horizon_test import collect_signals

logging.basicConfig(level=logging.ERROR)
STAKE = 1000
FEE_RT = 0.004

# (nom, objectif%, stop%, horizon) — None pour ATR
CONFIGS = [
    ("Mini-obj +3% / stop -30% / 40j", 0.03, 0.30, 40),
    ("Petit obj +5% / stop -20% / 30j", 0.05, 0.20, 30),
    ("Classique +12% / -6% / 10j", 0.12, 0.06, 10),
    ("ATR équilibré (actuel)", None, None, 21),
]


def eval_fixed(df, i, entry, atr_pct, target_pct, stop_pct, horizon):
    future = df.iloc[i + 1:]
    if target_pct is None:  # mode ATR
        lv = market_context.compute_levels(entry, atr_pct)
        target, stop = lv["target"], lv["stop"]
    else:
        target, stop = entry * (1 + target_pct), entry * (1 - stop_pct)
    for d, (_, row) in enumerate(future.iterrows(), start=1):
        if float(row["low"]) <= stop:
            return (stop - entry) / entry
        if float(row["high"]) >= target:
            return (target - entry) / entry
        if d >= horizon:
            return (float(row["close"]) - entry) / entry
    return (float(future.iloc[-1]["close"]) - entry) / entry if len(future) else None


def main(years=2):
    tickers = watchlist.get_full_watchlist()
    spx = data_fetcher.fetch_ticker("^GSPC", period=f"{years+1}y", interval="1d")
    regime, spx_by_date = {}, {}
    if not spx.empty:
        ma = spx["close"].rolling(50).mean()
        regime = {d.strftime("%Y-%m-%d"): bool(x) for d, x in (spx["close"] >= ma).items()}
        spx_by_date = {d.strftime("%Y-%m-%d"): float(x) for d, x in spx["close"].items()}

    data = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")
    sigs_all = []
    for tk, df in data.items():
        if df is None or df.empty or len(df) < 80:
            continue
        d2, sigs = collect_signals(df, regime, spx_by_date)
        for (i, e, a) in sigs:
            sigs_all.append((d2, i, e, a))
    print(f"Signaux : {len(sigs_all)}\n")
    print(f"{'Configuration':32} | réussite | gain moy | PIRE trade | net (1000€/tr)")
    print("-" * 92)
    for name, tp, sp, h in CONFIGS:
        res = [eval_fixed(df, i, e, a, tp, sp, h) for (df, i, e, a) in sigs_all]
        res = [x for x in res if x is not None]
        arr = np.array(res); n = len(arr)
        wr = (arr > 0).mean() * 100
        avg = arr.mean() * 100
        worst = arr.min() * 100
        net = arr.sum() * STAKE - n * STAKE * FEE_RT
        print(f"{name:32} | {wr:6.1f}% | {avg:+6.2f}% | {worst:+7.1f}% | {net:+9,.0f} €")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
