"""
fundamentals.py — Analyse fondamentale (santé financière de l'entreprise).

Complète l'analyse technique + le sentiment : avant le débat, on fournit aux IA
les fondamentaux réels de la société (croissance, marges, rentabilité, dette,
consensus analystes). Source : Yahoo Finance (yfinance), gratuit.

On calcule un score de santé fondamentale (0-100) transparent et heuristique,
qui sert de contexte aux IA — pas de boîte noire. Les fondamentaux évoluent
lentement : on met en cache par ticker (agent_state) pour éviter de re-télécharger
à chaque scan.

Dégradation gracieuse : toute donnée absente est ignorée (fail-open) ; si rien
n'est disponible, on renvoie un contexte "n/d" sans bloquer la décision.
"""

import logging
import datetime as dt

import config

logger = logging.getLogger("fundamentals")

# Champs yfinance utiles (info). Tous optionnels.
_FIELDS = [
    "sector", "industry", "marketCap", "trailingPE", "forwardPE", "pegRatio",
    "profitMargins", "grossMargins", "revenueGrowth", "earningsGrowth",
    "earningsQuarterlyGrowth", "returnOnEquity", "debtToEquity", "freeCashflow",
    "recommendationKey", "numberOfAnalystOpinions", "targetMeanPrice",
]


# ─────────────────────────────────────────────────────────────
# RÉCUPÉRATION (avec cache)
# ─────────────────────────────────────────────────────────────

def _fetch_raw(ticker: str) -> dict:
    """Télécharge les fondamentaux bruts via yfinance (dict des champs utiles)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("fundamentals %s indisponibles : %s", ticker, str(e)[:80])
        return {}
    return {k: info.get(k) for k in _FIELDS if info.get(k) is not None}


def get_fundamentals(ticker: str, use_cache: bool = True) -> dict:
    """Fondamentaux d'un ticker, avec cache TTL (agent_state)."""
    cache_key = f"fund:{ticker}"
    if use_cache:
        try:
            from memory import state
            cached = state.get_state(cache_key, default=None)
            if cached and _fresh(cached.get("fetched_at")):
                return cached.get("data", {})
        except Exception:  # noqa: BLE001
            pass

    data = _fetch_raw(ticker)
    if data:
        try:
            from memory import state
            state.set_state(cache_key, {
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "data": data,
            })
        except Exception:  # noqa: BLE001
            pass
    return data


def _fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        d = dt.datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        age = (dt.datetime.now(dt.timezone.utc) - d).days
        return age < config.FUNDAMENTALS["cache_days"]
    except Exception:  # noqa: BLE001
        return False


# ─────────────────────────────────────────────────────────────
# SCORE DE SANTÉ FONDAMENTALE (0-100, heuristique transparente)
# ─────────────────────────────────────────────────────────────

def _tiered(value, t_high, t_mid, t_low, pts_high, pts_mid, pts_low) -> tuple[float, float]:
    """Attribue des points par paliers. Retourne (points, max_points)."""
    if value is None:
        return 0.0, 0.0  # composante absente -> ignorée du dénominateur
    if value >= t_high:
        return pts_high, pts_high
    if value >= t_mid:
        return pts_mid, pts_high
    if value >= t_low:
        return pts_low, pts_high
    return 0.0, pts_high


def score_fundamentals(data: dict) -> dict:
    """
    Score 0-100 + label, à partir de croissance, marges, rentabilité, dette, FCF.
    Normalisé sur les composantes RÉELLEMENT disponibles (None ignoré).
    """
    if not data:
        return {"score": None, "label": "n/d", "available": 0}

    got, total = 0.0, 0.0
    comps = []

    rg = data.get("revenueGrowth")
    p, m = _tiered(rg, 0.15, 0.05, 0.0, 20, 12, 6)
    got += p; total += m
    if rg is not None:
        comps.append(f"croissance CA {rg*100:+.0f}%")

    eg = data.get("earningsGrowth") if data.get("earningsGrowth") is not None else data.get("earningsQuarterlyGrowth")
    p, m = _tiered(eg, 0.15, 0.05, 0.0, 20, 12, 6)
    got += p; total += m
    if eg is not None:
        comps.append(f"croissance bénéfices {eg*100:+.0f}%")

    pm = data.get("profitMargins")
    p, m = _tiered(pm, 0.15, 0.05, 0.0, 20, 12, 6)
    got += p; total += m
    if pm is not None:
        comps.append(f"marge nette {pm*100:.0f}%")

    roe = data.get("returnOnEquity")
    p, m = _tiered(roe, 0.15, 0.05, 0.0, 15, 8, 4)
    got += p; total += m
    if roe is not None:
        comps.append(f"ROE {roe*100:.0f}%")

    # Dette/fonds propres : PLUS BAS = MIEUX (yfinance en %, ex. 80 = 80%)
    dte = data.get("debtToEquity")
    if dte is not None:
        total += 15
        got += 15 if dte < 50 else 8 if dte < 100 else 2
        comps.append(f"dette/FP {dte:.0f}%")

    fcf = data.get("freeCashflow")
    if fcf is not None:
        total += 10
        got += 10 if fcf > 0 else 0
        comps.append("FCF positif" if fcf > 0 else "FCF négatif")

    if total == 0:
        return {"score": None, "label": "n/d", "available": 0, "components": comps}

    score = round(got / total * 100)
    label = "solide" if score >= 70 else "correct" if score >= 45 else "fragile"
    return {"score": score, "label": label, "available": len(comps), "components": comps}


# ─────────────────────────────────────────────────────────────
# CONSENSUS ANALYSTES
# ─────────────────────────────────────────────────────────────

_RECO_FR = {
    "strong_buy": "achat fort", "buy": "achat", "hold": "conserver",
    "underperform": "sous-performance", "sell": "vente", "none": "n/d",
}


def analyst_view(data: dict, price: float | None = None) -> str:
    """Phrase de consensus analystes (reco + nb d'avis + potentiel vs objectif)."""
    reco = data.get("recommendationKey")
    n = data.get("numberOfAnalystOpinions")
    target = data.get("targetMeanPrice")
    if not reco and not target:
        return "Consensus analystes : n/d."
    parts = []
    if reco:
        parts.append(f"avis {_RECO_FR.get(reco, reco)}")
    if n:
        parts.append(f"{n} analystes")
    if target and price:
        upside = (target - price) / price * 100
        parts.append(f"objectif moyen {target:.2f} ({upside:+.0f}%)")
    elif target:
        parts.append(f"objectif moyen {target:.2f}")
    return "Consensus analystes : " + ", ".join(parts) + "."


# ─────────────────────────────────────────────────────────────
# BLOC DE CONTEXTE POUR LES IA
# ─────────────────────────────────────────────────────────────

def _fmt_cap(cap) -> str:
    if not cap:
        return "n/d"
    for unit, div in (("Md", 1e9), ("M", 1e6)):
        if cap >= div:
            return f"{cap/div:.1f} {unit}$"
    return f"{cap:.0f}$"


def cap_bucket(market_cap) -> str | None:
    """Catégorie de capitalisation (small / mid / large) en USD. None si inconnu."""
    if not market_cap:
        return None
    if market_cap < 2e9:
        return "small"
    if market_cap < 10e9:
        return "mid"
    return "large"


def fundamentals_context(ticker: str, price: float | None = None) -> dict:
    """
    Bloc fondamentaux prêt pour les prompts IA.
    Retourne {"text", "score_text", "analyst_text", "sector", "industry",
              "market_cap", "market_cap_value", "cap_bucket", "score"}.
    """
    data = get_fundamentals(ticker)
    if not data:
        return {
            "text": "Fondamentaux non disponibles.",
            "score_text": "Santé fondamentale : n/d.",
            "analyst_text": "Consensus analystes : n/d.",
            "sector": "n/d", "industry": "n/d", "market_cap": "n/d",
            "market_cap_value": None, "cap_bucket": None, "score": None,
        }

    sc = score_fundamentals(data)
    score_txt = (f"Santé fondamentale : {sc['label']} ({sc['score']}/100)"
                 if sc["score"] is not None else "Santé fondamentale : n/d")
    detail = " · ".join(sc.get("components", [])) or "détails indisponibles"

    pe = data.get("trailingPE") or data.get("forwardPE")
    peg = data.get("pegRatio")
    valo = []
    if pe:
        valo.append(f"PER {pe:.0f}")
    if peg:
        valo.append(f"PEG {peg:.2f}")
    valo_txt = (" | " + ", ".join(valo)) if valo else ""

    return {
        "text": f"{detail}{valo_txt}",
        "score_text": score_txt,
        "analyst_text": analyst_view(data, price),
        "sector": data.get("sector") or "n/d",
        "industry": data.get("industry") or "n/d",
        "market_cap": _fmt_cap(data.get("marketCap")),
        "market_cap_value": data.get("marketCap"),
        "cap_bucket": cap_bucket(data.get("marketCap")),
        "score": sc["score"],
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    out = fundamentals_context(tk)
    print(f"\n=== FONDAMENTAUX {tk} ===")
    print(out["score_text"])
    print(out["text"])
    print(out["analyst_text"])
    print(f"Secteur : {out['sector']} / {out['industry']} — capi {out['market_cap']}")
