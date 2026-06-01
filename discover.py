"""
discover.py — Étude d'événements : qu'est-ce qui précède un bond de +10% en 1 jour ?

Méthode honnête (lift, pas "points communs") :
  1. Sur 2 ans × watchlist, calcule pour chaque jour des features de la VEILLE
     (aucune donnée du futur).
  2. Étiquette : le lendemain fait-il >= +10% (y1) ? un jour des 5 suivants
     fait-il >= +10% (y5) ?
  3. Pour chaque feature, découpe en quintiles et mesure le taux de +10% par
     quintile vs le TAUX DE BASE. Un "lift" > 1 = la feature augmente la proba.

Sortie : taux de base + tableaux de lift par feature + meilleures conjonctions.
Lancer : python discover.py [annees]   (défaut 2)
"""

import sys
import logging

import numpy as np
import pandas as pd

import data_fetcher
import watchlist

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("discover")

THRESHOLD = 0.10   # +10% en une journée


def features_for_ticker(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    """Construit le tableau (features de la veille) -> (label lendemain/5j)."""
    if df.empty or len(df) < 80:
        return pd.DataFrame()
    df = data_fetcher.add_indicators(df)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    daily_ret = c.pct_change()
    feat = pd.DataFrame(index=df.index)
    feat["ret_5d"] = c.pct_change(5)
    feat["ret_20d"] = c.pct_change(20)
    feat["rsi"] = df["rsi"]
    feat["vol_ratio"] = v / v.rolling(20).mean()
    feat["dist_ma20"] = c / df["ma20"] - 1
    feat["dist_ma50"] = c / df["ma50"] - 1
    feat["atr_pct"] = (h - l).rolling(14).mean() / c
    rng = h.rolling(20).max() - l.rolling(20).min()
    feat["range20_pos"] = (c - l.rolling(20).min()) / rng
    feat["up_days_5"] = (daily_ret > 0).rolling(5).sum()
    feat["vol_accel"] = v.rolling(5).mean() / v.rolling(20).mean()  # accumulation récente

    # Labels (futur — uniquement pour l'étiquette, jamais comme feature)
    feat["y1"] = (c.shift(-1) / c - 1 >= THRESHOLD).astype(float)
    fut5 = pd.concat([daily_ret.shift(-k) for k in range(1, 6)], axis=1).max(axis=1)
    feat["y5"] = (fut5 >= THRESHOLD).astype(float)

    feat["ticker"] = ticker
    return feat.dropna()


def lift_table(data: pd.DataFrame, feature: str, label: str, q: int = 5) -> pd.DataFrame:
    """Taux de +10% par quintile de la feature + lift vs taux de base."""
    base = data[label].mean()
    try:
        data = data.copy()
        data["bucket"] = pd.qcut(data[feature], q, duplicates="drop")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    g = data.groupby("bucket", observed=True)[label].agg(["mean", "count"])
    g["lift"] = g["mean"] / base if base > 0 else 0
    g["taux_%"] = (g["mean"] * 100).round(2)
    g["lift"] = g["lift"].round(2)
    return g[["count", "taux_%", "lift"]]


def main(years: int = 2):
    tickers = watchlist.get_full_watchlist()
    print(f"Étude sur {len(tickers)} tickers, {years} ans. Seuil = +{THRESHOLD*100:.0f}% en 1 jour.\n")
    data_map = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")

    frames = [features_for_ticker(tk, df) for tk, df in data_map.items()
              if df is not None and not df.empty]
    frames = [f for f in frames if not f.empty]
    if not frames:
        print("Pas de données.")
        return
    data = pd.concat(frames, ignore_index=True)

    n = len(data)
    base1, base5 = data["y1"].mean(), data["y5"].mean()
    print(f"Observations : {n:,}")
    print(f"TAUX DE BASE — un +10% le lendemain      : {base1*100:.2f}%  ({int(data['y1'].sum())} cas)")
    print(f"TAUX DE BASE — un +10% dans les 5 jours   : {base5*100:.2f}%  ({int(data['y5'].sum())} cas)")
    print("\nUn 'lift' de 2.0 = deux fois plus probable que la moyenne.\n")

    features = ["vol_ratio", "vol_accel", "rsi", "ret_5d", "dist_ma20",
                "range20_pos", "atr_pct", "up_days_5"]
    print("="*70)
    print("LIFT PAR FEATURE (cible : +10% dans les 5 jours)")
    print("="*70)
    best = []
    for feat in features:
        t = lift_table(data, feat, "y5")
        if t.empty:
            continue
        top_lift = t["lift"].iloc[-1]   # quintile le plus élevé
        best.append((feat, top_lift))
        print(f"\n● {feat}  (quintile haut lift = {top_lift})")
        print(t.to_string())

    print("\n" + "="*70)
    print("CLASSEMENT des features les plus prédictives (lift du quintile haut)")
    print("="*70)
    for feat, lift in sorted(best, key=lambda x: x[1], reverse=True):
        print(f"  {feat:14} : x{lift}")

    # Conjonctions (combiner les meilleurs signaux)
    print("\n" + "="*70)
    print("CONJONCTIONS (combiner plusieurs conditions)")
    print("="*70)
    cond_volume = data["vol_ratio"] > data["vol_ratio"].quantile(0.8)
    cond_accel = data["vol_accel"] > 1.2
    cond_tight = data["atr_pct"] < data["atr_pct"].quantile(0.4)
    cond_rs = data["ret_5d"] > 0.05
    for name, mask in [
        ("volume explosif (top 20%)", cond_volume),
        ("accumulation volume + base serrée", cond_accel & cond_tight),
        ("volume explosif + momentum 5j>5%", cond_volume & cond_rs),
        ("accumulation + serré + momentum", cond_accel & cond_tight & cond_rs),
    ]:
        sub = data[mask]
        if len(sub) > 50:
            rate = sub["y5"].mean()
            print(f"  {name:40} : {rate*100:.2f}%  (lift x{rate/base5:.2f}, n={len(sub)})")

    data.to_csv("discover_features.csv", index=False)
    print("\nDétail -> discover_features.csv")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
