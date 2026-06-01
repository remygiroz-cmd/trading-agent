"""
optimize.py — Recherche de configuration robuste (walk-forward, anti-overfit).

Objectif de Rémy : taux de réussite élevé ET gains des gagnants >= 10%.
On teste ~90 réglages de sortie (objectif / stop / durée), en séparant :
  - période d'APPRENTISSAGE (ancienne moitié) : pour repérer les bons réglages
  - période de TEST (moitié récente, jamais utilisée pour régler) : vérité

Un réglage qui brille sur l'apprentissage MAIS s'effondre en test = sur-mesure
inutile (overfitting). On ne garde que ce qui tient en TEST.

Métriques : réussite %, gain moyen des gagnants %, % de trades >= +10%,
espérance, net (1000€/trade, frais 0,4%), pire trade.

Lancer : python optimize.py [annees]
"""

import sys
import logging

import numpy as np
import pandas as pd

import config
import data_fetcher
import watchlist
from horizon_test import collect_signals

logging.basicConfig(level=logging.ERROR)
STAKE = 1000
FEE_RT = 0.004

TARGETS = [("pct", 0.10), ("pct", 0.15), ("pct", 0.20), ("pct", 0.30),
           ("atr", 3.0), ("atr", 4.0)]
STOPS = [("pct", 0.06), ("pct", 0.10), ("pct", 0.15), ("atr", 1.5), ("atr", 2.5)]
HORIZONS = [21, 42, 63]


def _level(entry, atr, spec, default_pct, sign):
    kind, val = spec
    if kind == "pct":
        pct = val
    else:  # atr
        pct = (val * atr) if (atr and atr > 0) else default_pct
    return entry * (1 + sign * pct)


def simulate(entry, atr, future, target_spec, stop_spec, horizon):
    target = _level(entry, atr, target_spec, 0.12, +1)
    stop = _level(entry, atr, stop_spec, 0.06, -1)
    for d, (_, row) in enumerate(future.iterrows(), start=1):
        if float(row["low"]) <= stop:
            return (stop - entry) / entry
        if float(row["high"]) >= target:
            return (target - entry) / entry
        if d >= horizon:
            return (float(row["close"]) - entry) / entry
    return (float(future.iloc[-1]["close"]) - entry) / entry if len(future) else None


def metrics(results):
    arr = np.array([r for r in results if r is not None])
    if len(arr) == 0:
        return None
    wins = arr[arr > 0]
    return {
        "n": len(arr),
        "win": (arr > 0).mean() * 100,
        "avg_win": (wins.mean() * 100) if len(wins) else 0,
        "pct_ge10": (arr >= 0.10).mean() * 100,
        "exp": arr.mean() * 100,
        "net": arr.sum() * STAKE - len(arr) * STAKE * FEE_RT,
        "worst": arr.min() * 100,
    }


def main(years=2):
    tickers = watchlist.get_full_watchlist()
    spx = data_fetcher.fetch_ticker("^GSPC", period=f"{years+1}y", interval="1d")
    regime, spx_by_date = {}, {}
    if not spx.empty:
        ma = spx["close"].rolling(50).mean()
        regime = {d.strftime("%Y-%m-%d"): bool(x) for d, x in (spx["close"] >= ma).items()}
        spx_by_date = {d.strftime("%Y-%m-%d"): float(x) for d, x in spx["close"].items()}

    data = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")
    signals = []  # (df, i, entry, atr, date)
    for tk, df in data.items():
        if df is None or df.empty or len(df) < 80:
            continue
        d2, sigs = collect_signals(df, regime, spx_by_date)
        for (i, e, a) in sigs:
            signals.append((d2, i, e, a, d2.index[i]))
    if not signals:
        print("Aucun signal."); return

    dates = sorted(s[4] for s in signals)
    cutoff = dates[len(dates) // 2]
    train = [s for s in signals if s[4] <= cutoff]
    test = [s for s in signals if s[4] > cutoff]
    print(f"Signaux : {len(signals)} (apprentissage {len(train)} jusqu'au {cutoff.date()}, "
          f"test {len(test)} après)\n")

    # Évaluer toutes les configs sur train + test
    rows = []
    for ts in TARGETS:
        for ss in STOPS:
            for h in HORIZONS:
                tr = metrics([simulate(e, a, df.iloc[i + 1:], ts, ss, h) for (df, i, e, a, _) in train])
                te = metrics([simulate(e, a, df.iloc[i + 1:], ts, ss, h) for (df, i, e, a, _) in test])
                if tr and te:
                    rows.append({"cfg": f"obj {ts[0]}{ts[1]} / stop {ss[0]}{ss[1]} / {h}j",
                                 "tr": tr, "te": te})

    # 1) Meilleure espérance en TEST (robuste)
    rows.sort(key=lambda r: r["te"]["exp"], reverse=True)
    print("="*100)
    print("TOP 8 par ESPÉRANCE en TEST (le plus robuste) — train -> test")
    print("="*100)
    print(f"{'Configuration':34} | réuss tr→te | gain gagnants | %≥+10% | espér tr→te | net test | pire")
    for r in rows[:8]:
        tr, te = r["tr"], r["te"]
        print(f"{r['cfg']:34} | {tr['win']:4.0f}→{te['win']:4.0f}% | "
              f"{te['avg_win']:5.1f}% | {te['pct_ge10']:5.1f}% | "
              f"{tr['exp']:+5.2f}→{te['exp']:+5.2f}% | {te['net']:+8,.0f}€ | {te['worst']:+5.0f}%")

    # 2) Le critère de Rémy : réussite élevée ET gains gagnants >= 10%
    print("\n" + "="*100)
    print("CONFIGS qui visent TON critère : réussite TEST >= 55% ET gain des gagnants >= 10%")
    print("="*100)
    crit = [r for r in rows if r["te"]["win"] >= 55 and r["te"]["avg_win"] >= 10]
    crit.sort(key=lambda r: r["te"]["net"], reverse=True)
    if not crit:
        print("AUCUNE configuration n'atteint réussite>=55% ET gagnants>=10% en test.")
        # montrer le plus proche
        near = sorted(rows, key=lambda r: -(r["te"]["win"] + (r["te"]["avg_win"] >= 10) * 20))[:5]
        print("Les plus proches :")
        for r in near[:5]:
            te = r["te"]
            print(f"  {r['cfg']:34} | réuss {te['win']:.0f}% | gagnants {te['avg_win']:.1f}% | "
                  f"%≥10% {te['pct_ge10']:.0f}% | net {te['net']:+,.0f}€")
    else:
        for r in crit[:8]:
            te = r["te"]
            print(f"  {r['cfg']:34} | réuss {te['win']:.0f}% | gagnants {te['avg_win']:.1f}% | "
                  f"%≥10% {te['pct_ge10']:.0f}% | net {te['net']:+,.0f}€ | pire {te['worst']:.0f}%")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
