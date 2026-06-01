"""
config.py — Configuration centrale de l'agent de surveillance boursière.

Toutes les constantes, paramètres et clés API sont regroupés ici.
Les clés sensibles sont lues depuis les variables d'environnement (.env).
"""

import os

try:
    from dotenv import load_dotenv
    # override=True : le .env du projet prime sur d'éventuelles variables d'env
    # ambiantes (ex. ANTHROPIC_API_KEY déjà posée par l'environnement de dev).
    # En production il n'y a pas de .env -> les vraies variables d'env sont utilisées.
    load_dotenv(override=True)
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

# ─────────────────────────────────────────────────────────────
# FILTRES DE QUALITÉ SUPPLÉMENTAIRES (#2 résultats, #3 force relative)
# ─────────────────────────────────────────────────────────────

RELATIVE_STRENGTH = {
    "enabled": True,
    "lookback_days": 63,          # ~3 mois
    "min_outperformance": 0.0,    # le titre doit au moins égaler le marché
    "market_ticker": "^GSPC",
}

EARNINGS_FILTER = {
    "enabled": True,
    "buffer_days": 2,             # marge de sécurité autour de la date de résultats
}

# ─────────────────────────────────────────────────────────────
# RADAR DE BUZZ (essai) — récap sentiment X/analystes avant ouverture
# Module SÉPARÉ du système de trading : info sentiment, PAS une reco d'achat.
# ─────────────────────────────────────────────────────────────
BUZZ = {
    "enabled": True,
    "trial_days": 7,                 # durée de l'essai (jours calendaires)
    "max_picks": 4,
    "eu_time": "08:30",              # avant ouverture Euronext (09:00 Paris)
    "us_time": "09:00",              # le matin, avant la préouverture US (~10:00 Paris)
    # Recherche en direct via la nouvelle API xAI "Responses" + outils serveur
    # (web_search + x_search). L'ancienne Live Search (search_parameters) est dépréciée.
    "responses_url": "https://api.x.ai/v1/responses",
    "model": "grok-4.3",             # modèle compatible outils serveur
    "max_tool_calls": 6,             # plafond d'appels d'outils (maîtrise du coût)
    "usd_per_tick": 1e-10,           # conversion estimée cost_in_usd_ticks -> USD (à vérifier)
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
    "atr_period": 14,
}

# Gestion du risque : stops/objectifs adaptés à la volatilité (ATR).
# Le backtest montre que des stops fixes serrés (-6%) font perdre sur les valeurs
# nerveuses ; un stop calé sur l'ATR (réussite 42%, +1,69%/trade) est bien meilleur.
RISK = {
    "mode": "atr",            # 'atr' ou 'fixed'
    "atr_stop_mult": 1.5,     # stop = entrée - 1.5 x ATR
    "atr_target_mult": 3.0,   # objectif = entrée + 3 x ATR
    "min_stop_pct": 0.04,     # bornes de sécurité
    "max_stop_pct": 0.15,
    "max_target_pct": 0.45,
    "default_horizon": 10,
    # repli si ATR indisponible (mode 'fixed')
    "fixed_stop_pct": 0.06,
    "fixed_target_pct": 0.12,
}


# ─────────────────────────────────────────────────────────────
# AUTO-RÉGLAGE DES SORTIES (boucle fermée objectif/stop/horizon)
# Ré-optimisation walk-forward périodique ; l'agent applique tout seul le
# meilleur réglage validé en TEST (cf. autotune.py). Garde-fous inclus.
# ─────────────────────────────────────────────────────────────
AUTOTUNE = {
    "enabled": True,
    "time": "07:30",            # heure de lancement (matin, avant les scans)
    "min_interval_days": 28,    # ~1x/mois (gros calcul : watchlist complète sur 2 ans)
    "years": 2,                 # profondeur d'historique pour le backtest
    "min_signals": 60,          # en deçà, on ne touche à rien (pas assez de preuve)
    "min_winrate": 55.0,        # critère cible : réussite TEST >= 55%
    "min_avg_win": 10.0,        # critère cible : gain moyen des gagnants >= 10%
    "min_test_winrate": 50.0,   # garde-fou : réussite TEST mini pour appliquer
    "min_improvement_pp": 0.5,  # garde-fou : marge d'espérance vs réglage actif (points de %)
}


# ─────────────────────────────────────────────────────────────
# ANALYSE FONDAMENTALE (santé financière de l'entreprise)
# Données yfinance (gratuit), mises en cache par ticker. Injectées dans le
# contexte des IA pour étayer la décision (cf. fundamentals.py).
# ─────────────────────────────────────────────────────────────
FUNDAMENTALS = {
    "enabled": True,
    "cache_days": 5,            # les fondamentaux bougent lentement -> cache 5 jours
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
# ENDPOINTS ET MODÈLES DES IA
# ─────────────────────────────────────────────────────────────

AI_CONFIG = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "api_key": DEEPSEEK_API_KEY,
    },
    "grok": {
        "url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-3",
        "api_key": GROK_API_KEY,
        "live_search": True,   # Grok peut chercher sur X/actus en temps réel
    },
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "api_key": ANTHROPIC_API_KEY,
        "anthropic_version": "2023-06-01",
    },
}

AI_REQUEST = {
    "timeout": 60,          # secondes
    "max_tokens": 1024,
    "temperature": 0.4,
    "max_retries": 2,
}


# ─────────────────────────────────────────────────────────────
# RÈGLES MÉTIER (seuils d'alerte)
# ─────────────────────────────────────────────────────────────

# Figures activées. Le high_tight_flag est désactivé : le backtest montre qu'il
# fait perdre de l'argent sur cette watchlist (31,7% de réussite, espérance < 0).
# À réactiver si sa détection est améliorée (cf. backtest.py).
ENABLED_PATTERNS = [
    "bull_flag", "cup_handle", "vcp", "pocket_pivot", "flat_base", "double_bottom",
    "momentum_pop",   # signal explosif (volume+momentum+volatilité), stops ATR
]

ALERT_RULES = {
    "min_setup_score": 35,       # /50 — relevé de 30 à 35 : le backtest montre que
                                 # la tranche 30-35 est à espérance nulle, 40+ excellent
    "min_final_score": 75,       # /100 — seuil pour envoyer une alerte
    "min_buy_votes": 2,          # minimum 2 IA sur 3 votent ACHETER
    "high_conviction_score": 85, # /100 — alerte ✅ vs ⚡
    # Plafond de débats IA par scan : borne le coût et le temps d'exécution
    # (un run GitHub Actions est limité à 20 min). Les finalistes sont déjà triés
    # par qualité (meilleurs en premier).
    "max_finalists_per_scan": 8,
}


# ─────────────────────────────────────────────────────────────
# PAPER TRADING
# ─────────────────────────────────────────────────────────────

PAPER_TRADING_CONFIG = {
    "enabled": True,
    "virtual_capital": 10000,
    "max_position_pct": 0.05,
    "fixed_position_eur": 1000,   # on simule 1000 € investis sur CHAQUE signal
    "start_date": None,
    "duration_days": 30,
}

# Webhook Google Sheets (Apps Script). Vide = export désactivé.
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "")


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
