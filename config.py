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

# Interrupteur général. False = l'agent ne fait PLUS RIEN.
AGENT_ENABLED = True

# Mode de fonctionnement :
#   "monitor" = suivi du portefeuille de Rémy (signaux achat/vente sur SA liste)
#   "scan"    = ancien mode (screener momentum sur tout le marché) — désactivé
MODE = "monitor"

TIMEZONE = "Europe/Paris"


# ─────────────────────────────────────────────────────────────
# MODE SUIVI DE PORTEFEUILLE (cf. monitor.py)
# Le bot surveille les valeurs de Rémy et indique quand acheter/vendre.
#   type "conviction" : long terme -> signaux pour RENFORCER sur repli
#   type "spec"       : spéculatif -> signaux d'ENTRÉE et de SORTIE actifs
# ─────────────────────────────────────────────────────────────
MONITOR = {
    "enabled": True,
    "check_times": ["09:00", "13:00", "17:35"],  # bulletin à 09:00, re-checks ensuite
    "rsi_oversold": 35,
    "rsi_overbought": 72,
    "conviction_trim_rsi": 78,        # alléger une conviction seulement si TRÈS suracheté
    "conviction_trim_above_ma": 0.15,  # ET > 15% au-dessus de la MA50
    "near_ma_pct": 0.03,              # "sur la MA50" = à moins de 3%
    "spec_take_profit": 0.15,         # spéculatif : +15% depuis l'achat -> prendre les bénéfices
    "ai_confirm": True,               # les 3 IA confirment/nuancent chaque signal actionnable
    "ai_max_per_run": 6,              # plafond de débats IA par exécution (coût maîtrisé)
}

WATCHLIST_MONITOR = [
    # Convictions (long terme — renforcer sur repli)
    {"name": "Hermès",      "ticker": "RMS.PA",   "type": "conviction", "entry": 1690.0,  "cur": "€"},
    {"name": "LVMH",        "ticker": "MC.PA",    "type": "conviction", "entry": 476.95,  "cur": "€"},
    {"name": "Air Liquide", "ticker": "AI.PA",    "type": "conviction", "entry": 173.08,  "cur": "€"},
    {"name": "Microsoft",   "ticker": "MSFT",     "type": "conviction", "entry": 394.24,  "cur": "$"},
    {"name": "Tesla",       "ticker": "TSLA",     "type": "conviction", "entry": 441.28,  "cur": "$"},
    {"name": "IonQ",        "ticker": "IONQ",     "type": "conviction", "entry": 39.97,   "cur": "$"},
    # Spéculatives (entrer / sortir)
    {"name": "Sanofi",            "ticker": "SAN.PA",   "type": "spec", "entry": 80.04,  "cur": "€"},
    {"name": "Sartorius Stedim",  "ticker": "DIM.PA",   "type": "spec", "entry": 184.70, "cur": "€"},
    {"name": "Riber",             "ticker": "ALRIB.PA", "type": "spec", "entry": 13.22,  "cur": "€"},
    {"name": "2CRSI",             "ticker": "AL2SI.PA", "type": "spec", "entry": 49.22,  "cur": "€"},
    {"name": "Soitec",            "ticker": "SOI.PA",   "type": "spec", "entry": 157.30, "cur": "€"},
]

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
    "permanent": True,               # True = pas de limite 7 jours (bilan du soir chaque jour)
    "trial_days": 7,                 # durée de l'essai si permanent=False
    "max_picks": 4,
    "eu_time": "08:30",              # buzz Europe + US ensemble le matin (avant ouverture)
    "us_time": "08:30",              # même horaire que l'EU (les 2 récaps au même moment)
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
# CONVICTION COMPOSITE + DIMENSIONNEMENT (cf. conviction.py)
# Croise technique / fondamental / sentiment en une conviction 0-100, détecte
# les divergences, et en déduit une taille de position avec gestion du risque.
# ─────────────────────────────────────────────────────────────
CONVICTION = {
    "enabled": True,
    # Poids des trois piliers (renormalisés sur ceux réellement disponibles)
    "weights": {"technique": 0.50, "fondamental": 0.30, "sentiment": 0.20},
    # Seuils de divergence (sur axes normalisés 0-1)
    "strong": 0.65,            # un pilier est "fort" au-dessus de ce seuil
    "weak": 0.40,              # un pilier est "faible" en dessous
}

SIZING = {
    "min_pct": 1.0,            # taille plancher d'une position (% du portefeuille)
    "max_pct": 10.0,           # taille plafond
    "conviction_floor": 60.0,  # conviction en deçà de laquelle on reste au plancher
    "max_risk_per_trade_pct": 1.0,  # risque max par trade (perte au stop) en % du portefeuille
    "divergence_factor": 0.6,  # réduction de taille en cas de divergence
}


# ─────────────────────────────────────────────────────────────
# RÉGIME DE MARCHÉ (cf. market_regime.py)
# Au lieu d'un simple "marché ok / pas ok", on détecte le régime et on adapte
# la stratégie : seuil d'alerte, nombre de finalistes, taille des positions.
# Le filtre dur SPX<MA50 / VIX>30 reste non négociable (géré dans market_filter).
# ─────────────────────────────────────────────────────────────
REGIMES = {
    "haussier": {     # tendance saine : on joue normalement
        "label": "📈 Haussier",
        "min_final_score": 75,
        "max_finalists": 8,
        "size_mult": 1.0,
    },
    "prudent": {      # au-dessus de la MA50 mais signaux mitigés (sous MA200, VIX élevé…)
        "label": "⚠️ Prudent",
        "min_final_score": 82,    # on exige plus de conviction
        "max_finalists": 5,
        "size_mult": 0.6,         # on réduit la taille
    },
    "defavorable": {  # repli (normalement déjà bloqué par le filtre dur)
        "label": "🛑 Défavorable",
        "min_final_score": 90,
        "max_finalists": 2,
        "size_mult": 0.3,
    },
}

REGIME_PARAMS = {
    "ma_trend": 50,          # MA de tendance courte
    "ma_long": 200,          # MA de tendance longue (golden/death cross)
    "slope_lookback": 10,    # pente de la MA50 sur ~2 semaines
    "vix_calm": 22.0,        # VIX en deçà = serein
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
    # Envoi auto du récap (actions étudiées + scores) quand un scan ne déclenche
    # AUCUNE alerte — pour ne jamais rester sans nouvelles. Respecte le mode pause/digest.
    "recap_when_no_alert": True,
    # Tour 2 du débat uniquement si les IA ne sont pas unanimes au Tour 1
    # (la lecture croisée ne change presque jamais un verdict unanime ; ÷2 sur le coût IA)
    "round2_only_on_disagreement": True,
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
# SUIVI BITCOIN — MVRV Z-Score + calendrier halving (cf. btc_mvrv.py, halving.py)
# Vérifiés 1x/jour. Alertes uniquement au franchissement de seuil (anti-spam).
# ─────────────────────────────────────────────────────────────
BTC_MVRV = {
    "enabled": True,
    # API publique gratuite (bitcoin-data.com). Renvoie la dernière valeur du MVRV Z-Score.
    "api_url": "https://bitcoin-data.com/v1/mvrv-zscore/last",
}

HALVING = {
    "enabled": True,
    # Estimation du prochain halving (ajustable). Le signal ACHAT = halving - 500 j
    # (~nov. 2026), le signal VENTE = halving + 500 j (~août 2029).
    "halving_date": "2028-03-29",
    "offset_days": 500,
    "milestones": [30, 7, 0],   # J-30, J-7, J-0
}


# ─────────────────────────────────────────────────────────────
# SIMULATION BUDGET RÉEL (cf. budget_sim.py)
# Un porte-monnaie unique au budget FIXE qui suit les signaux du bot, sans
# pouvoir dépasser le budget. Une simulation par seuil pour comparer.
# ─────────────────────────────────────────────────────────────
BUDGET_SIM = {
    "budget": 1500.0,            # capital de départ simulé
    "levels": [75, 70, 65, 60],  # seuils comparés (un porte-monnaie chacun)
    "per_trade_pct": 0.25,       # part du budget engagée par trade (~4 positions max en //)
}


# ─────────────────────────────────────────────────────────────
# RESTRICTION TRADE REPUBLIC
# TR n'a pas d'API publique de catalogue : on ne peut pas vérifier la dispo par
# programme. On s'en approche : (1) consigne forte dans le buzz (grandes bourses,
# liquide, pas d'OTC/penny), (2) liste d'exclusion curée que Rémy complète.
# ─────────────────────────────────────────────────────────────
TRADE_REPUBLIC = {
    # Tickers connus comme NON disponibles sur Trade Republic (à compléter au fil
    # de l'eau). Exclus à la fois du radar buzz et de la watchlist surveillée.
    "exclude": ["NUVL", "VTYX", "TNGX", "AKTS", "HQ", "GTBIF", "WBI",
                "HOOD", "TLN", "ELVN", "SENEA"],
}


# ─────────────────────────────────────────────────────────────
# GESTIONNAIRE DE PORTEFEUILLE (cf. portfolio.py)
# Raisonne au niveau du PORTEFEUILLE, pas seulement signal par signal : limite
# le nombre de positions, l'exposition par secteur et l'exposition totale, pour
# éviter de tout miser sur le même thème (inspiré de TradingAgents).
# ─────────────────────────────────────────────────────────────
PORTFOLIO = {
    "enabled": True,
    "max_concurrent": 8,              # nb max de positions ouvertes en même temps
    "max_per_sector": 3,              # nb max de positions par secteur
    "max_total_exposure_pct": 80.0,   # % max du capital engagé au total
    "max_sector_exposure_pct": 35.0,  # % max du capital engagé sur un seul secteur
}


# ─────────────────────────────────────────────────────────────
# PORTEFEUILLE RÉEL DE RÉMY (cf. holdings.py) — suivi en TEMPS RÉEL
# Deux comptes : CTO (Trade Republic) et PEA. Pour chaque ligne on note ce que
# montre l'appli au moment du relevé : la VALEUR actuelle de la position (en €)
# et la plus/moins-value DEPUIS L'ACHAT (en % côté CTO, en € côté PEA).
# holdings.py en déduit le prix de revient et la quantité, puis recalcule la
# valeur live à partir du cours du jour (Yahoo).
#
# Pour mettre à jour : remplace value_eur + pl_pct/pl_eur par ce qu'affiche
# l'appli (et buy_price si tu renforces à un autre cours).
# ─────────────────────────────────────────────────────────────
HOLDINGS = [
    # ── CTO (Trade Republic) — P/L affichée en % ──
    {"account": "CTO", "name": "Tesla",                  "ticker": "TSLA",  "cur": "$", "value_eur": 3496.70, "pl_pct": -0.1258, "buy_price": 441.28},
    {"account": "CTO", "name": "Microsoft",              "ticker": "MSFT",  "cur": "$", "value_eur":  959.94, "pl_pct": -0.0402, "buy_price": 394.24},
    {"account": "CTO", "name": "Gold 3x Lev USD (Acc)",  "ticker": "3GOL.L", "cur": "$", "value_eur": 518.48, "pl_pct": -0.6549, "buy_price": None},
    {"account": "CTO", "name": "IonQ",                   "ticker": "IONQ",  "cur": "$", "value_eur":   95.32, "pl_pct": -0.0470, "buy_price": 39.97},
    {"account": "CTO", "name": "Physical Gold USD (Acc)", "ticker": "SGLD.L", "cur": "$", "value_eur":  70.31, "pl_pct": -0.0914, "buy_price": None},

    # ── PEA — P/L affichée en € ──
    {"account": "PEA", "name": "Hermès",             "ticker": "RMS.PA",   "cur": "€", "value_eur": 3276.00, "pl_eur":  -99.00, "buy_price": 1690.00},
    {"account": "PEA", "name": "Sartorius Stedim",   "ticker": "DIM.PA",   "cur": "€", "value_eur": 1046.40, "pl_eur":  -62.80, "buy_price":  184.70},
    {"account": "PEA", "name": "LVMH",               "ticker": "MC.PA",    "cur": "€", "value_eur":  988.80, "pl_eur":  +34.90, "buy_price":  476.95},
    {"account": "PEA", "name": "Sanofi",             "ticker": "SAN.PA",   "cur": "€", "value_eur":  977.86, "pl_eur":  -62.62, "buy_price":   80.04},
    {"account": "PEA", "name": "Riber",              "ticker": "ALRIB.PA", "cur": "€", "value_eur":  946.00, "pl_eur": -190.20, "buy_price":   13.22},
    {"account": "PEA", "name": "Air Liquide",        "ticker": "AI.PA",    "cur": "€", "value_eur":  568.52, "pl_eur":  -12.72, "buy_price":  173.08},
    {"account": "PEA", "name": "2CRSI",              "ticker": "AL2SI.PA", "cur": "€", "value_eur":  563.64, "pl_eur": -476.02, "buy_price":   49.22},
    {"account": "PEA", "name": "Soitec",             "ticker": "SOI.PA",   "cur": "€", "value_eur":  227.30, "pl_eur":  -88.30, "buy_price":  157.30},
]

# Liquidités par compte (espèces non investies).
CASH = {
    "CTO": 0.0,
    "PEA": 1745.45,
}

# Date du relevé ci-dessus (captures du portefeuille). Les transactions ANTÉRIEURES
# à cette date sont déjà incluses dans HOLDINGS : on les journalise sans toucher
# aux parts (sinon double comptage). Les transactions postérieures, elles, mettent
# bien à jour le portefeuille.
HOLDINGS_SNAPSHOT_DATE = "2026-06-28"


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
