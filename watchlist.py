"""
watchlist.py — Gestion des 340 tickers à surveiller.

Composition :
  - 40 tickers FIXES (définis en dur, jamais modifiés automatiquement)
  - 300 tickers DYNAMIQUES (reconstruits chaque lundi par screening volume/variation)

La watchlist dynamique est persistée en base (Session 4/7). En attendant, on
fournit un cache fichier local (data_cache/dynamic_watchlist.json) pour pouvoir
travailler hors-ligne et tester.

Règle métier : un ticker blacklisté n'est jamais réintégré automatiquement.
"""

import os
import json
import logging

logger = logging.getLogger("watchlist")

CACHE_DIR = "data_cache"
DYNAMIC_CACHE = os.path.join(CACHE_DIR, "dynamic_watchlist.json")


# ─────────────────────────────────────────────────────────────
# WATCHLIST FIXE — 40 tickers
# ─────────────────────────────────────────────────────────────

# Small caps IA mondiales US (20)
AI_SMALL_CAPS_US = [
    "IONQ", "RGTI", "QBTS", "QUBT", "SOUN",
    "BBAI", "RXRX", "BTBT", "CIFR", "INOD",
    "AI", "PLTR", "ASTS", "OKLO", "APLD",
    "SMCI", "AMBA", "RFIL", "HOOD", "SOFI",
]

# Small caps françaises PEA IA (10)
AI_SMALL_CAPS_FR = [
    "AL2SI.PA",   # 2CRSi
    "ALKAL.PA",   # Kalray
    "ALRIB.PA",   # Riber
    "SOI.PA",     # Soitec
    "SMCO.PA",    # Semco Technologies
    "EXENS.PA",   # Exosens
    "EXXO.PA",    # Exail Technologies
    "LBIRD.PA",   # Lumibird
    "MEMS.PA",    # Memscap
    "EGDE.PA",    # Egide
]

# Mid caps européennes PEA (10)
# NOTE : SPECS.md liste "STM.PA" mais ce ticker est introuvable sur Yahoo.
# Le bon ticker Euronext Paris de STMicroelectronics est "STMPA.PA".
MID_CAPS_EU = [
    "ASML",       # ASML (Nasdaq)
    "STMPA.PA",   # STMicroelectronics (corrigé : STM.PA -> STMPA.PA)
    "CAP.PA",     # Capgemini
    "DSY.PA",     # Dassault Systèmes
    "OVH.PA",     # OVHcloud
    "HO.PA",      # Thales
    "SAP",        # SAP (NYSE)
    "AI.PA",      # Air Liquide
    "SOI.PA",     # Soitec
    "LR.PA",      # Legrand
]


def get_fixed_watchlist() -> list[str]:
    """Retourne les tickers fixes, dédupliqués en conservant l'ordre."""
    combined = AI_SMALL_CAPS_US + AI_SMALL_CAPS_FR + MID_CAPS_EU
    seen = set()
    out = []
    for t in combined:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ─────────────────────────────────────────────────────────────
# WATCHLIST DYNAMIQUE — 300 tickers (cache local en attendant Supabase)
# ─────────────────────────────────────────────────────────────

def load_dynamic_watchlist() -> list[str]:
    """Charge la watchlist dynamique depuis le cache local. Vide si absente."""
    if not os.path.exists(DYNAMIC_CACHE):
        return []
    try:
        with open(DYNAMIC_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tickers", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("Lecture cache watchlist dynamique échouée : %s", e)
        return []


def save_dynamic_watchlist(tickers: list[str]) -> None:
    """Persiste la watchlist dynamique dans le cache local."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(DYNAMIC_CACHE, "w", encoding="utf-8") as f:
        json.dump({"tickers": tickers, "count": len(tickers)}, f, ensure_ascii=False, indent=2)
    logger.info("Watchlist dynamique sauvegardée : %s tickers", len(tickers))


# ─────────────────────────────────────────────────────────────
# WATCHLIST COMPLÈTE
# ─────────────────────────────────────────────────────────────

def get_full_watchlist(blacklist: set[str] | None = None) -> list[str]:
    """
    Retourne la watchlist complète : fixes + dynamiques, dédupliquée.
    Exclut les tickers blacklistés (jamais réintégrés automatiquement).
    """
    blacklist = blacklist or set()
    fixed = get_fixed_watchlist()
    dynamic = load_dynamic_watchlist()

    seen = set()
    out = []
    for t in fixed + dynamic:
        if t in blacklist or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


# ─────────────────────────────────────────────────────────────
# RECONSTRUCTION DYNAMIQUE (chaque lundi) via screener Yahoo
# ─────────────────────────────────────────────────────────────

def _screen_region(region: str, size: int) -> list[str]:
    """
    Interroge le screener Yahoo Finance pour une région.

    Critères (approximation des specs avec les champs disponibles) :
      - capitalisation > 100M$
      - variation journalière > +3%
      - volume du jour > 100k actions
    Tri par variation décroissante.

    NB : Yahoo n'expose pas la variation hebdomadaire ni le ratio volume/4sem
    directement ; on récupère un univers momentum+volume large, affiné ensuite
    par le pré-filtre (prefilter.py) qui, lui, calcule la variation 5j réelle.
    """
    import yfinance as yf

    try:
        q = yf.EquityQuery("and", [
            yf.EquityQuery("gt", ["intradaymarketcap", 100_000_000]),
            yf.EquityQuery("gt", ["percentchange", 3]),
            yf.EquityQuery("gt", ["dayvolume", 100_000]),
            yf.EquityQuery("eq", ["region", region]),
        ])
        res = yf.screen(q, size=min(size, 250), sortField="percentchange", sortAsc=False)
        quotes = res.get("quotes", []) if isinstance(res, dict) else []
        return [x.get("symbol") for x in quotes if x.get("symbol")]
    except Exception as e:  # noqa: BLE001
        logger.warning("Screener région %s échoué : %s", region, e)
        return []


def rebuild_dynamic_watchlist(blacklist: set[str] | None = None, limit: int = 300) -> list[str]:
    """
    Reconstruit la watchlist dynamique (300 tickers) — appelé chaque lundi.

    Sources : screener Yahoo US (≈200) + Europe (≈100).
    Exclut les tickers fixes, les blacklistés et les doublons.
    Sauvegarde le résultat dans le cache local.
    """
    blacklist = blacklist or set()

    us = _screen_region("us", size=250)
    fr = _screen_region("fr", size=100)

    fixed = set(get_fixed_watchlist())
    seen = set()
    dynamic = []
    for t in us + fr:
        if t in fixed or t in blacklist or t in seen:
            continue
        seen.add(t)
        dynamic.append(t)
        if len(dynamic) >= limit:
            break

    save_dynamic_watchlist(dynamic)
    logger.info("Watchlist dynamique reconstruite : %s tickers (US=%s, FR=%s)",
                len(dynamic), len(us), len(fr))
    return dynamic


def classify_market(ticker: str) -> str:
    """Devine le marché d'un ticker : 'EU' (.PA, .AS...) ou 'US'."""
    eu_suffixes = (".PA", ".AS", ".DE", ".MI", ".BR", ".LS", ".MC", ".HE", ".ST")
    if any(ticker.endswith(s) for s in eu_suffixes):
        return "EU"
    return "US"


def filter_by_markets(tickers: list[str], markets: list[str]) -> list[str]:
    """Garde uniquement les tickers des marchés demandés (['EU','US'])."""
    return [t for t in tickers if classify_market(t) in markets]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fixed = get_fixed_watchlist()
    dyn = load_dynamic_watchlist()
    print(f"Fixes     : {len(fixed)} tickers")
    print(f"Dynamiques: {len(dyn)} tickers (cache local)")
    print(f"Total     : {len(get_full_watchlist())} tickers")
    print(f"US        : {len(filter_by_markets(fixed, ['US']))}")
    print(f"EU        : {len(filter_by_markets(fixed, ['EU']))}")
