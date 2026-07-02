"""
pepites.py — Radar quotidien des valeurs susceptibles d'exploser à la hausse.

Le signal vient de l'étude d'événements discover.py (qu'est-ce qui précède un
bond de +10% ?) et a été validé par le backtest explosive.py :
  - volume du jour > 1.3x sa moyenne 20 jours (l'argent entre)
  - momentum : +5% ou plus sur 5 jours (le mouvement a déjà commencé)
  - ATR% > 5% (assez de volatilité pour faire un vrai mouvement)
  - marché porteur (S&P 500 au-dessus de sa MA50) — sinon on ne propose RIEN

Priorité aux valeurs éligibles PEA (Euronext), complété par les US (CTO).
Chaque pépite arrive avec un plan complet : entrée, stop, objectif (calés ATR,
mêmes règles que config.RISK). Anti-répétition : un ticker proposé n'est pas
reproposé pendant PEPITES["cooldown_days"] jours.

Honnêteté : c'est un signal statistique — toutes ne montent pas. Le message le
rappelle et impose le stop.
"""

import logging
import datetime as dt

import config
import data_fetcher
import watchlist

logger = logging.getLogger("pepites")

STATE_KEY = "pepites_recent"


# ─────────────────────────────────────────────────────────────
# ÉVALUATION D'UN TICKER (pur, testable)
# ─────────────────────────────────────────────────────────────

def evaluate(df) -> dict | None:
    """Calcule les métriques du signal explosif sur la DERNIÈRE bougie daily.

    Retourne {price, vol_ratio, ret5, atr_pct, atr, score} ou None si données
    insuffisantes. Le score sert au classement : plus le volume explose et plus
    le momentum est fort, plus la pépite est prometteuse.
    """
    if df is None or df.empty or len(df) < 30:
        return None
    try:
        c, v = df["close"], df["volume"]
        price = float(c.iloc[-1])
        vol_avg20 = float(v.rolling(20).mean().iloc[-1])
        if not vol_avg20 or vol_avg20 != vol_avg20:
            return None
        vol_ratio = float(v.iloc[-1]) / vol_avg20
        ret5 = float(c.iloc[-1] / c.iloc[-6] - 1)
        atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
        atr_pct = atr / price if price else 0.0
        if any(x != x for x in (vol_ratio, ret5, atr_pct)):  # NaN
            return None
        return {
            "price": price, "vol_ratio": vol_ratio, "ret5": ret5,
            "atr": atr, "atr_pct": atr_pct,
            "score": vol_ratio * (1 + ret5),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("evaluate KO : %s", e)
        return None


def passes(m: dict | None) -> bool:
    """Le ticker déclenche-t-il le signal explosif (seuils config.PEPITES) ?"""
    if not m:
        return False
    p = config.PEPITES
    return (m["vol_ratio"] > p["min_vol_ratio"]
            and m["ret5"] > p["min_ret5"]
            and m["atr_pct"] > p["min_atr_pct"])


def plan(price: float, atr: float) -> dict:
    """Plan de trade : stop et objectif calés sur l'ATR (bornes de config.RISK)."""
    r = config.RISK
    stop_pct = min(max(r["atr_stop_mult"] * atr / price, r["min_stop_pct"]), r["max_stop_pct"])
    target_pct = min(r["atr_target_mult"] * atr / price, r["max_target_pct"])
    return {
        "stop": price * (1 - stop_pct), "stop_pct": stop_pct,
        "target": price * (1 + target_pct), "target_pct": target_pct,
    }


def select(cands: list[dict], top_n: int, pea_first: bool = True) -> list[dict]:
    """Classe par score décroissant, priorité PEA (Euronext) si pea_first."""
    ranked = sorted(cands, key=lambda x: x["score"], reverse=True)
    if not pea_first:
        return ranked[:top_n]
    eu = [c for c in ranked if c["market"] == "EU"]
    us = [c for c in ranked if c["market"] != "EU"]
    return (eu + us)[:top_n]


# ─────────────────────────────────────────────────────────────
# MESSAGE
# ─────────────────────────────────────────────────────────────

def _fmt_pick(c: dict) -> str:
    tag = "🇫🇷 PEA" if c["market"] == "EU" else "🇺🇸 CTO"
    cur = "€" if c["market"] == "EU" else "$"
    p = c["plan"]
    return (f"{tag} · ACHÈTE {c['ticker']} — {c['price']:.2f}{cur}\n"
            f"   Stop {p['stop']:.2f}{cur} ({-p['stop_pct']*100:.0f}%) · "
            f"Objectif {p['target']:.2f}{cur} (+{p['target_pct']*100:.0f}%)\n"
            f"   Pourquoi : volume x{c['vol_ratio']:.1f}, {c['ret5']*100:+.0f}% en 5j, "
            f"volatilité {c['atr_pct']*100:.0f}%")


def format_message(picks: list[dict], market_reason: str = "") -> str:
    today = dt.date.today().isoformat()
    lines = [f"🚀 PÉPITES DU JOUR — {today}", ""]
    if market_reason:
        lines.append(f"❌ Rien aujourd'hui : {market_reason}")
        lines.append("Le signal perd son avantage quand le marché est défavorable — "
                     "je préfère te proposer zéro pépite qu'une fausse.")
        return "\n".join(lines)
    if not picks:
        lines.append("❌ Rien de convaincant aujourd'hui — aucune valeur ne déclenche "
                     "le signal (volume + momentum + volatilité).")
        lines.append("Pas de pépite plutôt qu'une fausse pépite.")
        return "\n".join(lines)
    lines.append("Candidates à une forte hausse dans les heures/jours à venir "
                 "(signal volume + momentum, validé par backtest) :")
    lines.append("")
    for c in picks:
        lines.append(_fmt_pick(c))
        lines.append("")
    lines.append("⚠️ Signal statistique : toutes ne montent pas. Stop OBLIGATOIRE, "
                 "mise limitée par position.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# SCAN QUOTIDIEN
# ─────────────────────────────────────────────────────────────

def _recent_tickers(today: dt.date) -> set:
    """Tickers déjà proposés il y a moins de cooldown_days (anti-répétition)."""
    from memory import state
    hist = state.get_state(STATE_KEY, default={}) or {}
    keep = set()
    cd = config.PEPITES["cooldown_days"]
    for tk, d in hist.items():
        try:
            if (today - dt.date.fromisoformat(d)).days < cd:
                keep.add(tk)
        except Exception:  # noqa: BLE001
            continue
    return keep


def _remember(picks: list[dict], today: dt.date) -> None:
    from memory import state
    hist = state.get_state(STATE_KEY, default={}) or {}
    # purge des entrées expirées + ajout des picks du jour
    cd = config.PEPITES["cooldown_days"]
    fresh = {}
    for tk, d in hist.items():
        try:
            if (today - dt.date.fromisoformat(d)).days < cd:
                fresh[tk] = d
        except Exception:  # noqa: BLE001
            continue
    for c in picks:
        fresh[c["ticker"]] = today.isoformat()
    state.set_state(STATE_KEY, fresh)


def scan() -> dict:
    """Scanne la watchlist complète et retourne {picks, market_reason}."""
    # 1. Filtre marché : pas de pépites en marché baissier (règle du backtest)
    market_reason = ""
    try:
        import market_filter
        st = market_filter.get_market_status()
        if not st["ok"]:
            market_reason = st["reason"]
    except Exception as e:  # noqa: BLE001
        logger.warning("Filtre marché indisponible (%s) — on continue sans.", e)

    if market_reason:
        return {"picks": [], "market_reason": market_reason}

    # 2. Univers : watchlist complète (fixes + dynamiques ≈ 340 tickers)
    tickers = watchlist.get_full_watchlist()
    today = dt.date.today()
    skip = _recent_tickers(today)

    data_map = data_fetcher.fetch_batch(tickers, period="90d", interval="1d")
    cands = []
    for tk, df in data_map.items():
        if tk in skip:
            continue
        m = evaluate(df)
        if not passes(m):
            continue
        cands.append({
            "ticker": tk, "market": watchlist.classify_market(tk),
            "plan": plan(m["price"], m["atr"]), **m,
        })

    p = config.PEPITES
    picks = select(cands, p["top_n"], p["pea_first"])
    logger.info("Pépites : %s candidates, %s retenues", len(cands), len(picks))
    return {"picks": picks, "market_reason": ""}


def run(send: bool = True) -> dict:
    """Scan + envoi Telegram du message quotidien."""
    out = scan()
    msg = format_message(out["picks"], out["market_reason"])
    print(msg)
    if out["picks"]:
        _remember(out["picks"], dt.date.today())
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi pépites échoué : %s", e)
    return {"picks": len(out["picks"]), "message": msg}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run(send=False)
