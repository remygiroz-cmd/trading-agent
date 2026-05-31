"""
test_patterns_synthetic.py — Vérifie le chemin POSITIF des détecteurs.

On fabrique des séries de prix qui contiennent volontairement chaque figure,
pour s'assurer que les détecteurs renvoient bien detected=True (et pas False
en permanence à cause d'un bug).
"""

import numpy as np
import pandas as pd

import data_fetcher
import patterns.bull_flag as bf
import patterns.flat_base as fb
import patterns.high_tight_flag as htf
import patterns.double_bottom as db


def _mkdf(closes, volumes=None):
    closes = np.array(closes, dtype=float)
    if volumes is None:
        volumes = np.full(len(closes), 1_000_000.0)
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame({
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": volumes,
    }, index=idx)
    return data_fetcher.add_indicators(df)


def test_bull_flag():
    # mât +30% en 10 bougies, drapeau plat 6 bougies, cassure finale
    pole = list(np.linspace(100, 130, 10))
    flag = [129, 127, 126, 127, 126, 128]
    breakout = [131]
    closes = [100] * 20 + pole + flag + breakout
    vols = [1e6] * 20 + [3e6] * 10 + [8e5] * 6 + [4e6]
    r = bf.detect(_mkdf(closes, vols))
    print(f"  bull_flag       detected={r['detected']} depth={r['depth']} "
          f"vol_ratio={r['volume_ratio']} brk=x{r['breakout_volume_ratio']}")
    return r["detected"]


def test_flat_base():
    # base plate ~5% d'amplitude sur 30 bougies, puis cassure en volume
    rng = np.random.RandomState(0)
    base = 100 + rng.uniform(-2.5, 2.5, 30)
    closes = list(np.linspace(80, 100, 30)) + list(base) + [106]
    vols = [1e6] * 30 + [5e5] * 30 + [2e6]
    r = fb.detect(_mkdf(closes, vols))
    print(f"  flat_base       detected={r['detected']} depth={r['depth']} "
          f"vol_ratio={r['volume_ratio']} brk=x{r['breakout_volume_ratio']}")
    return r["detected"]


def test_high_tight_flag():
    # mât +100% en 25 bougies, drapeau serré -12% sur 8 bougies, cassure
    pole = list(np.linspace(50, 100, 25))
    flag = [98, 95, 92, 90, 91, 92, 93, 94]
    closes = [50] * 15 + pole + flag + [101]
    vols = [1e6] * 15 + [3e6] * 25 + [9e5] * 8 + [4e6]
    r = htf.detect(_mkdf(closes, vols))
    print(f"  high_tight_flag detected={r['detected']} depth={r['depth']} "
          f"pole_gain={r['pole_gain']} brk=x{r['breakout_volume_ratio']}")
    return r["detected"]


def test_double_bottom():
    # deux creux proches (~100), pic médian ~115, cassure au-dessus
    closes = (list(np.linspace(130, 100, 12)) +   # descente vers creux 1
              list(np.linspace(101, 115, 10)) +   # remontée pic médian
              list(np.linspace(114, 101, 12)) +   # redescente creux 2
              list(np.linspace(102, 118, 8)))      # cassure
    vols = [1e6] * 42 + [3e6] * 2
    vols = (vols + [1e6] * (len(closes) - len(vols)))[:len(closes)]
    r = db.detect(_mkdf(closes, vols))
    print(f"  double_bottom   detected={r['detected']} depth={r['depth']} "
          f"brk=x{r['breakout_volume_ratio']} {r.get('notes','')}")
    return r["detected"]


if __name__ == "__main__":
    print("Test chemin POSITIF des détecteurs (données synthétiques)\n")
    results = {
        "bull_flag": test_bull_flag(),
        "flat_base": test_flat_base(),
        "high_tight_flag": test_high_tight_flag(),
        "double_bottom": test_double_bottom(),
    }
    print()
    ok = sum(results.values())
    print(f"Détecteurs déclenchés : {ok}/{len(results)}")
    for k, v in results.items():
        print(f"  {'✅' if v else '❌'} {k}")
