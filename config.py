"""
config.py — Configuration centrale de l'agent de surveillance boursière.

Toutes les constantes, paramètres et clés API sont regroupés ici.
Les clés sensibles sont lues depuis les variables d'environnement (.env).
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv optionnel : en production les variables sont déjà dans l'environnement
    pass


# ─────────────────────────────────────────────────────────────
# CLÉS API ET SECRETS (depuis variables d'environnement)
# ─────────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")


# ─────────────────────────────────────────────────────────────
# FUSEAU HORAIRE ET PLANIFICATION
# ─────────────────────────────────────────────────────────────

TIMEZONE = "Europe/Paris"

SCAN_SCHEDULE = [
    {"time": "09:35", "label": "ouverture", "markets": ["EU", "US"]},
    {"time": "13:30", "label": "mi-journee", "markets": ["EU", "US"]},
    {"time": "17:35", "label": "cloture_eu", "markets": ["EU", "US"]},
    {"time": "22:15", "label": "cloture_us", "markets": ["US"]},
]

# Heure du bilan quotidien et de la mise à jour des résultats
DAILY_REPORT_TIME = "22:30"
# Reconstruction de la watchlist dynamique
WATCHLIST_REBUILD_TIME = "08:00"  # chaque lundi


# ─────────────────────────────────────────────────────────────
# FILTRE MARCHÉ GLOBAL
# ─────────────────────────────────────────────────────────────

MARKET_FILTER = {
    "spx_ticker": "^GSPC",
    "vix_ticker": "^VIX",
    "spx_ma_period": 50,       # SPX doit être au-dessus de sa MA50
    "vix_max": 30.0,           # VIX max toléré
}


# ─────────────────────────────────────────────────────────────
# PRÉ-FILTRE ALGORITHMIQUE
# ─────────────────────────────────────────────────────────────

PREFILTER_CRITERIA = {
    "min_variation_5d": 0.02,        # +2% sur 5 jours minimum
    "min_volume_ratio": 1.3,         # Volume aujourd'hui > moyenne x1.3
    "price_above_ma20": True,        # Prix au-dessus de la MA20
    "min_price": 1.0,                # Pas de penny stocks < 1$
    "min_avg_volume": 100000,        # Volume moyen > 100k actions/jour
}

# Plafond du nombre de candidats transmis à la détection de figures + IA.
# La watchlist dynamique étant déjà issue d'un screener momentum, le pré-filtre
# peut retourner beaucoup de candidats les jours de forte hausse. On borne donc
# au top-N (tri par qualité momentum) pour maîtriser le coût des appels IA.
PREFILTER_MAX_CANDIDATES = 40


# ─────────────────────────────────────────────────────────────
# TIMEFRAMES ET HISTORIQUE
# ─────────────────────────────────────────────────────────────

TIMEFRAMES = ["4h", "1d"]
LOOKBACK_PERIODS = {
    "4h": 120,    # 120 bougies 4H ≈ 30 jours
    "1d": 90,     # 90 jours
}

# Indicateurs techniques
INDICATORS = {
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "ma_periods": [10, 20, 50],
}


# ─────────────────────────────────────────────────────────────
# POIDS INITIAUX DES IA
# ─────────────────────────────────────────────────────────────

INITIAL_WEIGHTS = {
    "deepseek": 0.33,
    "grok": 0.33,
    "claude": 0.34,
}

WEIGHT_MIN = 0.15
WEIGHT_MAX = 0.55


# ─────────────────────────────────────────────────────────────
# RÈGLES MÉTIER (seuils d'alerte)
# ─────────────────────────────────────────────────────────────

ALERT_RULES = {
    "min_setup_score": 30,       # /50 — seuil pour envoyer aux IA
    "min_final_score": 75,       # /100 — seuil pour envoyer une alerte
    "min_buy_votes": 2,          # minimum 2 IA sur 3 votent ACHETER
    "high_conviction_score": 85, # /100 — alerte ✅ vs ⚡
}


# ─────────────────────────────────────────────────────────────
# PAPER TRADING
# ─────────────────────────────────────────────────────────────

PAPER_TRADING_CONFIG = {
    "enabled": True,
    "virtual_capital": 10000,
    "max_position_pct": 0.05,
    "start_date": None,
}


# ─────────────────────────────────────────────────────────────
# DONNÉES MARCHÉ (sources)
# ─────────────────────────────────────────────────────────────

DATA_SOURCE = {
    "primary": "yahoo",
    "backup": "polygon",
    "request_timeout": 20,       # secondes
    "max_retries": 3,
    "retry_delay": 2,            # secondes entre tentatives
}


def validate_config(strict: bool = False) -> dict:
    """
    Vérifie quelles clés sont présentes. Ne lève pas d'erreur par défaut
    (les modules de données fonctionnent sans clés IA/Telegram).

    Retourne un dict {nom_cle: bool présent}.
    """
    checks = {
        "DEEPSEEK_API_KEY": bool(DEEPSEEK_API_KEY),
        "GROK_API_KEY": bool(GROK_API_KEY),
        "ANTHROPIC_API_KEY": bool(ANTHROPIC_API_KEY),
        "SUPABASE_URL": bool(SUPABASE_URL),
        "SUPABASE_SERVICE_KEY": bool(SUPABASE_SERVICE_KEY),
        "TELEGRAM_BOT_TOKEN": bool(TELEGRAM_BOT_TOKEN),
        "TELEGRAM_CHAT_ID": bool(TELEGRAM_CHAT_ID),
        "POLYGON_API_KEY": bool(POLYGON_API_KEY),
    }
    if strict:
        missing = [k for k, present in checks.items() if not present]
        if missing:
            raise RuntimeError(f"Clés manquantes : {', '.join(missing)}")
    return checks
