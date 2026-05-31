"""
data_fetcher.py — Récupération des données de marché (OHLCV).

Source principale : Yahoo Finance (yfinance).
Source de secours : Polygon.io (gratuit) si Yahoo échoue.

Fournit aussi le calcul des indicateurs techniques (RSI, MACD, moyennes
mobiles) en pandas pur — pas de dépendance à ta-lib.

Format de sortie standardisé : DataFrame pandas indexé par date, colonnes
minuscules : open, high, low, close, volume.
"""

import time
import logging

import pandas as pd
import requests

import config

logger = logging.getLogger("data_fetcher")


# ─────────────────────────────────────────────────────────────
# RÉCUPÉRATION OHLCV
# ─────────────────────────────────────────────────────────────

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise un DataFrame yfinance vers le format standard minuscule."""
    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance peut renvoyer un MultiIndex de colonnes pour un seul ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })

    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    df = df.dropna(subset=["close"]) if "close" in df.columns else df
    return df


def fetch_yahoo(ticker: str, period: str = "90d", interval: str = "1d") -> pd.DataFrame:
    """Récupère les données via yfinance. Retourne un DataFrame normalisé (vide si échec)."""
    import yfinance as yf

    last_err = None
    for attempt in range(config.DATA_SOURCE["max_retries"]):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            df = _normalize_df(df)
            if not df.empty:
                return df
            last_err = "DataFrame vide"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(config.DATA_SOURCE["retry_delay"])

    logger.warning("Yahoo échec %s (%s/%s) : %s", ticker, interval, period, last_err)
    return pd.DataFrame()


def _period_to_polygon_range(period: str):
    """Convertit une période yfinance ('90d', '60d', '5d') en nombre de jours."""
    period = period.strip().lower()
    if period.endswith("d"):
        return int(period[:-1])
    if period.endswith("mo"):
        return int(period[:-2]) * 30
    if period.endswith("y"):
        return int(period[:-1]) * 365
    return 90


def fetch_polygon(ticker: str, period: str = "90d", interval: str = "1d") -> pd.DataFrame:
    """
    Récupère les données via Polygon.io (backup). Nécessite POLYGON_API_KEY.
    Ne gère que le daily de façon fiable en plan gratuit.
    """
    if not config.POLYGON_API_KEY:
        return pd.DataFrame()

    # Polygon utilise des tickers US sans suffixe ; on ignore les .PA (Euronext non couvert en gratuit)
    if "." in ticker or ticker.startswith("^"):
        return pd.DataFrame()

    days = _period_to_polygon_range(period)
    # On reste sur le daily pour le backup (le 4h gratuit est limité)
    multiplier, timespan = 1, "day"

    import datetime as _dt
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days + 10)

    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/"
        f"{multiplier}/{timespan}/{start.isoformat()}/{end.isoformat()}"
    )
    params = {"adjusted": "true", "sort": "asc", "limit": 5000, "apiKey": config.POLYGON_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=config.DATA_SOURCE["request_timeout"])
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df["date"] = pd.to_datetime(df["t"], unit="ms")
        df = df.set_index("date")
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
        })
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:  # noqa: BLE001
        logger.warning("Polygon échec %s : %s", ticker, e)
        return pd.DataFrame()


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Ré-échantillonne un DataFrame OHLCV vers une fréquence supérieure (ex. '4h')."""
    if df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    agg = {k: v for k, v in agg.items() if k in df.columns}
    out = df.resample(rule).agg(agg).dropna(subset=["close"])
    return out


def fetch_ticker(ticker: str, period: str = "90d", interval: str = "1d") -> pd.DataFrame:
    """
    Point d'entrée principal. Tente Yahoo, bascule sur Polygon si échec.
    Retourne un DataFrame normalisé (potentiellement vide).

    Yahoo ne fournit pas d'intervalle '4h' : on récupère le '1h' puis on
    ré-échantillonne en 4h.
    """
    if interval == "4h":
        # 1h limité à ~730j chez Yahoo ; on borne la période demandée.
        h1 = fetch_yahoo(ticker, period=period, interval="1h")
        if h1.empty:
            return pd.DataFrame()
        return _resample_ohlcv(h1, "4h")

    df = fetch_yahoo(ticker, period=period, interval=interval)
    if df.empty:
        logger.info("Bascule Polygon pour %s", ticker)
        df = fetch_polygon(ticker, period=period, interval=interval)
    return df


def fetch_many(tickers, period: str = "90d", interval: str = "1d", pause: float = 0.0) -> dict:
    """Récupère plusieurs tickers. Retourne {ticker: DataFrame}."""
    out = {}
    for t in tickers:
        out[t] = fetch_ticker(t, period=period, interval=interval)
        if pause:
            time.sleep(pause)
    return out


def fetch_batch(tickers, period: str = "90d", interval: str = "1d", chunk_size: int = 50) -> dict:
    """
    Télécharge plusieurs tickers en une seule requête groupée (rapide).
    Découpe en lots de `chunk_size` pour éviter les requêtes trop lourdes.
    Retourne {ticker: DataFrame normalisé}. Les tickers en échec ont un DataFrame vide.
    """
    import yfinance as yf

    out = {}
    tickers = list(tickers)
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            raw = yf.download(
                chunk,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Batch échec %s : %s", chunk, e)
            for t in chunk:
                out[t] = pd.DataFrame()
            continue

        for t in chunk:
            try:
                if isinstance(raw.columns, pd.MultiIndex) and t in raw.columns.get_level_values(0):
                    sub = raw[t].copy()
                elif len(chunk) == 1:
                    sub = raw.copy()
                else:
                    sub = pd.DataFrame()
                out[t] = _normalize_df(sub)
            except Exception:  # noqa: BLE001
                out[t] = pd.DataFrame()

    return out


def fetch_current_price(ticker: str) -> float | None:
    """Dernier prix de clôture disponible (daily récent)."""
    df = fetch_ticker(ticker, period="5d", interval="1d")
    if df.empty:
        return None
    return float(df["close"].iloc[-1])


# ─────────────────────────────────────────────────────────────
# INDICATEURS TECHNIQUES (pandas pur)
# ─────────────────────────────────────────────────────────────

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI de Wilder."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Retourne (macd_line, signal_line, histogramme)."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrichit un DataFrame OHLCV avec les indicateurs configurés.
    Ajoute : ma10, ma20, ma50, rsi, macd, macd_signal, macd_hist, vol_avg20.
    """
    if df.empty or "close" not in df.columns:
        return df

    df = df.copy()
    ind = config.INDICATORS

    for p in ind["ma_periods"]:
        df[f"ma{p}"] = sma(df["close"], p)

    df["rsi"] = rsi(df["close"], ind["rsi_period"])

    macd_line, signal_line, hist = macd(
        df["close"], ind["macd_fast"], ind["macd_slow"], ind["macd_signal"]
    )
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = hist

    if "volume" in df.columns:
        df["vol_avg20"] = df["volume"].rolling(20).mean()

    return df


def latest_snapshot(df: pd.DataFrame) -> dict:
    """
    Renvoie un dict résumé de la dernière bougie (prix, indicateurs).
    Utile pour les prompts IA et le pré-filtre.
    """
    if df.empty:
        return {}

    df = add_indicators(df)
    last = df.iloc[-1]

    def val(col):
        v = last.get(col)
        return None if v is None or pd.isna(v) else float(v)

    macd_val = val("macd")
    macd_sig = val("macd_signal")
    macd_signal_state = None
    if macd_val is not None and macd_sig is not None:
        macd_signal_state = "haussier" if macd_val > macd_sig else "baissier"

    return {
        "price": val("close"),
        "ma10": val("ma10"),
        "ma20": val("ma20"),
        "ma50": val("ma50"),
        "rsi": val("rsi"),
        "macd": macd_val,
        "macd_signal_line": macd_sig,
        "macd_signal_state": macd_signal_state,
        "volume": val("volume"),
        "vol_avg20": val("vol_avg20"),
    }


if __name__ == "__main__":
    # Test rapide en ligne de commande
    logging.basicConfig(level=logging.INFO)
    import sys

    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    data = fetch_ticker(tk, period="90d", interval="1d")
    print(f"{tk} : {len(data)} bougies")
    if not data.empty:
        print(data.tail(3))
        print("Snapshot :", latest_snapshot(data))
