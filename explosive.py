"""
explosive.py — Backtest du "signal explosif" issu de l'étude discover.py.

Entrée (combinaison la plus prédictive trouvée) :
  - explosion de volume (vol/moy20 > 1.3)
  - momentum récent (perf 5 jours > +5%)
  - volatilité suffisante pour bouger (ATR% > 5%)
  - marché porteur (S&P > MA50) — comme en prod

On teste la RENTABILITÉ réelle (pas juste le taux de +10%) avec 3 réglages de
sortie, à 1000 € par trade, frais inclus. Trades non chevauchants par ticker.

Lancer : python explosive.py [annees]
"""

import sys
import logging

import numpy as np
import pandas as pd

import data_fetcher
import watchlist

logging.basicConfig(level=logging.ERROR)

FEE_RT = 0.004          # frais aller-retour estimés (0,4%)
STAKE = 1000

# Réglages de sortie testés : (nom, mode, params)
CONFIGS = [
    ("Fixe +12% / -6% / 10j",  "fixed", {"target": 0.12, "stop": 0.06, "horizon": 10}),
    ("Fixe +20% / -8% / 15j",  "fixed", {"target": 0.20, "stop": 0.08, "horizon": 15}),
    ("ATR  +3xATR / -1.5xATR / 10j", "atr", {"t_mult": 3.0, "s_mult": 1.5, "horizon": 10}),
]


def _simulate(entry, atr_pct, future, mode, p):
    if mode == "fixed":
        target = entry * (1 + p["target"]); stop = entry * (1 - p["stop"]); horizon = p["horizon"]
    else:
        target = entry * (1 + p["t_mult"] * atr_pct); stop = entry * (1 - p["s_mult"] * atr_pct); horizon = p["horizon"]
    for d, (_, row) in enumerate(future.iterrows(), start=1):
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        if lo <= stop:
            return (stop - entry) / entry, "stop", d
        if hi >= target:
            return (target - entry) / entry, "objectif", d
        if d >= horizon:
            return (close - entry) / entry, "horizon", d
    if len(future):
        return (float(future.iloc[-1]["close"]) - entry) / entry, "horizon", len(future)
    return None


def backtest_config(data_map, regime, mode, p):
    trades = []
    for tk, df in data_map.items():
        if df is None or df.empty or len(df) < 80:
            continue
        df = data_fetcher.add_indicators(df)
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        vol_ratio = (v / v.rolling(20).mean()).values
        ret5 = c.pct_change(5).values
        atr_pct = ((h - l).rolling(14).mean() / c).values
        closes = c.values
        n = len(df)
        next_allowed = 60
        for i in range(60, n - 1):
            if i < next_allowed:
                continue
            if not (vol_ratio[i] > 1.3 and ret5[i] > 0.05 and atr_pct[i] > 0.05):
                continue
            date_str = df.index[i].strftime("%Y-%m-%d")
            if not regime.get(date_str, True):
                continue
            sim = _simulate(closes[i], atr_pct[i], df.iloc[i + 1:], mode, p)
            if not sim:
                continue
            pct, reason, days = sim
            trades.append({"ticker": tk, "pct": pct, "reason": reason, "days": days})
            next_allowed = i + days
    return trades


def report(name, trades):
    if not trades:
        print(f"\n### {name} : aucun trade"); return
    df = pd.DataFrame(trades)
    n = len(df)
    wr = (df["pct"] > 0).mean()
    avg = df["pct"].mean()
    gross = df["pct"].sum() * STAKE
    fees = n * STAKE * FEE_RT
    net = gross - fees
    print(f"\n### {name}")
    print(f"  Trades : {n} | Réussite : {wr*100:.1f}% | Gain moyen : {avg*100:+.2f}%/trade")
    print(f"  Profit BRUT (1000€/trade) : {gross:+,.0f} €")
    print(f"  Frais ({FEE_RT*100:.1f}%/trade) : -{fees:,.0f} €")
    print(f"  PROFIT NET : {net:+,.0f} €")
    print(f"  Sorties : {df['reason'].value_counts().to_dict()}")


def main(years=2):
    tickers = watchlist.get_full_watchlist()
    print(f"Backtest SIGNAL EXPLOSIF — {len(tickers)} tickers, {years} ans, {STAKE}€/trade\n"
          f"Entrée : volume>1.3x + perf5j>5% + ATR>5% + S&P>MA50")
    # régime marché
    spx = data_fetcher.fetch_ticker("^GSPC", period=f"{years+1}y", interval="1d")
    regime = {}
    if not spx.empty:
        ma = spx["close"].rolling(50).mean()
        regime = {d.strftime("%Y-%m-%d"): bool(x) for d, x in (spx["close"] >= ma).items()}
    data_map = data_fetcher.fetch_batch(tickers, period=f"{years}y", interval="1d")
    for name, mode, p in CONFIGS:
        report(name, backtest_config(data_map, regime, mode, p))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
