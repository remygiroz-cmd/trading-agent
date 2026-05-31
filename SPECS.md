# SPECS — Agent de Surveillance Boursière Multi-Agents
# Version 1.0 — Document de référence complet

---

## VUE D'ENSEMBLE

Un agent Python qui tourne en permanence sur Supabase Edge Functions. Il scanne 340 tickers toutes les 4 heures pendant les heures de marché, détecte les meilleures figures chartistes haussières, fait débattre trois IA (DeepSeek, Grok, Claude), et envoie une alerte Telegram uniquement quand le consensus est fort.

Tout est enregistré en base de données de façon permanente et cumulative. Le système s'améliore seul chaque jour grâce à la mémoire de ses décisions passées. Rémy ne short jamais — uniquement des signaux haussiers.

---

## PHASE 1 — SOCLE (construire en premier)

### 1.1 Structure des fichiers

```
trading-agent/
├── CLAUDE.md
├── SPECS.md
├── main.py                  # Point d'entrée principal
├── config.py                # Configuration et constantes
├── watchlist.py             # Gestion des 340 tickers
├── market_filter.py         # Filtre SPX + VIX global
├── data_fetcher.py          # Récupération données OHLCV
├── prefilter.py             # Pré-filtre algorithmique
├── patterns/
│   ├── __init__.py
│   ├── bull_flag.py
│   ├── cup_handle.py
│   ├── vcp.py
│   ├── high_tight_flag.py
│   ├── pocket_pivot.py
│   ├── flat_base.py
│   └── double_bottom.py
├── agents/
│   ├── __init__.py
│   ├── deepseek_agent.py
│   ├── grok_agent.py
│   ├── claude_agent.py
│   └── debate.py            # Orchestration du débat en 3 tours
├── memory/
│   ├── __init__.py
│   ├── database.py          # Connexion Supabase
│   ├── signals.py           # Enregistrement des signaux
│   ├── performance.py       # Calcul des performances
│   └── weights.py           # Gestion des poids des IA
├── alerts/
│   ├── __init__.py
│   ├── telegram_bot.py
│   └── daily_report.py
├── scheduler.py             # Planification des 4 scans/jour
└── requirements.txt
```

### 1.2 Watchlist des 340 tickers

#### Watchlist fixe — 40 tickers

**Small caps IA mondiales US (20)**
```python
AI_SMALL_CAPS_US = [
    "IONQ", "RGTI", "QBTS", "QUBT", "SOUN",
    "BBAI", "RXRX", "BTBT", "CIFR", "INOD",
    "AI", "PLTR", "ASTS", "OKLO", "APLD",
    "SMCI", "AMBA", "RFIL", "HOOD", "SOFI"
]
```

**Small caps françaises PEA IA (10)**
```python
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
    "EGDE.PA"     # Egide
]
```

**Mid caps européennes PEA (10)**
```python
MID_CAPS_EU = [
    "ASML",       # ASML (Nasdaq)
    "STM.PA",     # STMicroelectronics
    "CAP.PA",     # Capgemini
    "DSY.PA",     # Dassault Systèmes
    "OVH.PA",     # OVHcloud
    "HO.PA",      # Thales
    "SAP",        # SAP (NYSE)
    "AI.PA",      # Air Liquide
    "SOI.PA",     # Soitec
    "LR.PA"       # Legrand
]
```

#### Watchlist dynamique — 300 tickers
Reconstruite chaque lundi matin automatiquement.
Critères de sélection :
- Volume de la semaine > 150% de la moyenne 4 semaines
- Variation hebdomadaire > +3%
- Capitalisation boursière > 100M$
- Sources : screener Nasdaq small caps + Euronext Growth

### 1.3 Planification des scans

```python
SCAN_SCHEDULE = [
    {"time": "09:35", "label": "ouverture", "markets": ["EU", "US"]},
    {"time": "13:30", "label": "mi-journee", "markets": ["EU", "US"]},
    {"time": "17:35", "label": "cloture_eu", "markets": ["EU", "US"]},
    {"time": "22:15", "label": "cloture_us", "markets": ["US"]}
]
# Timezone : Europe/Paris
# Uniquement jours ouvrés (lundi-vendredi)
# Suspension automatique si SPX < MA50 ou VIX > 30
```

### 1.4 Filtre marché global

Vérifier en premier avant tout scan :

```python
def check_market_conditions():
    spx = fetch_ticker("^GSPC", period="60d", interval="1d")
    vix = fetch_ticker("^VIX", period="5d", interval="1d")
    
    spx_price = spx['close'].iloc[-1]
    spx_ma50 = spx['close'].rolling(50).mean().iloc[-1]
    vix_current = vix['close'].iloc[-1]
    
    if spx_price < spx_ma50:
        send_telegram("⚠️ SPX sous MA50 — scans suspendus. Marché défavorable.")
        return False
    
    if vix_current > 30:
        send_telegram("⚠️ VIX > 30 — scans suspendus. Volatilité trop élevée.")
        return False
    
    return True
```

### 1.5 Pré-filtre algorithmique (Python pur, sans IA)

Appliqué sur les 340 tickers. Garde uniquement les candidats qui passent tous les critères :

```python
PREFILTER_CRITERIA = {
    "min_variation_5d": 0.02,        # +2% sur 5 jours minimum
    "min_volume_ratio": 1.3,         # Volume aujourd'hui > moyenne x1.3
    "price_above_ma20": True,        # Prix au-dessus de la MA20
    "min_price": 1.0,                # Pas de penny stocks < 1$
    "min_avg_volume": 100000,        # Volume moyen > 100k actions/jour
}
# Résultat attendu : 15-40 candidats selon état du marché
```

---

## PHASE 2 — DÉTECTION DES FIGURES

### 2.1 Paramètres communs

```python
TIMEFRAMES = ["4h", "1d"]  # Analyse sur 4H et Daily
LOOKBACK_PERIODS = {
    "4h": 120,    # 120 bougies 4H = 30 jours
    "1d": 90      # 90 jours
}
```

### 2.2 Bull Flag

```python
BULL_FLAG_PARAMS = {
    "pole_min_gain": 0.10,           # Mât minimum +10%
    "pole_max_candles": 15,          # Mât en 15 bougies max
    "flag_max_depth": 0.50,          # Correction max 50% du mât
    "flag_min_candles": 3,           # Drapeau minimum 3 bougies
    "flag_max_candles": 20,          # Drapeau maximum 20 bougies
    "volume_contraction_ratio": 0.7, # Volume drapeau < 70% du mât
    "breakout_volume_ratio": 1.5,    # Cassure volume > x1.5 moyenne
}
```

### 2.3 Cup & Handle

```python
CUP_HANDLE_PARAMS = {
    "cup_min_weeks": 4,              # Durée tasse minimum 4 semaines
    "cup_max_weeks": 65,             # Durée tasse maximum 65 semaines
    "cup_max_depth": 0.50,           # Profondeur tasse max -50%
    "cup_rounding_score": 0.7,       # Score d'arrondi minimum (0-1)
    "handle_max_depth": 0.15,        # Anse max -15%
    "handle_max_weeks": 5,           # Durée anse max 5 semaines
    "breakout_volume_ratio": 1.5,
}
```

### 2.4 VCP (Volatility Contraction Pattern)

```python
VCP_PARAMS = {
    "min_contractions": 3,           # Minimum 3 contractions
    "max_contractions": 6,
    "contraction_ratio": 0.6,        # Chaque contraction < 60% de la précédente
    "final_depth_max": 0.10,         # Dernière contraction < 10%
    "volume_dry_up": 0.5,            # Volume final < 50% de la moyenne
}
```

### 2.5 High Tight Flag

```python
HIGH_TIGHT_FLAG_PARAMS = {
    "pole_min_gain": 0.90,           # Mât minimum +90% (quasi doublement)
    "pole_max_weeks": 8,             # En 8 semaines max
    "flag_max_depth": 0.25,          # Correction max -25%
    "flag_max_weeks": 5,
    "breakout_volume_ratio": 1.5,
}
```

### 2.6 Pocket Pivot

```python
POCKET_PIVOT_PARAMS = {
    "lookback_down_days": 10,        # Comparer aux 10 jours baissiers précédents
    "min_volume_vs_down_days": 1.0,  # Volume > max des jours baissiers
    "price_above_ma10": True,
    "price_above_ma50": True,
}
```

### 2.7 Flat Base

```python
FLAT_BASE_PARAMS = {
    "min_weeks": 5,                  # Minimum 5 semaines
    "max_depth": 0.15,               # Amplitude max 15%
    "volume_quiet": 0.8,             # Volume calme pendant la base
    "breakout_volume_ratio": 1.4,
}
```

### 2.8 Double Bottom

```python
DOUBLE_BOTTOM_PARAMS = {
    "tolerance": 0.03,               # Les deux creux à 3% près
    "second_bottom_higher": True,    # 2ème creux légèrement plus haut = idéal
    "min_distance_candles": 10,      # Minimum 10 bougies entre les deux creux
    "breakout_level": "mid_peak",    # Cassure du pic médian
    "breakout_volume_ratio": 1.5,
}
```

### 2.9 Score de qualité du setup (0-50)

Pour chaque figure détectée, calculer un score objectif avant d'appeler les IA :

```python
def calculate_setup_score(ticker_data, pattern_data):
    score = 0
    
    # Profondeur du drapeau/correction (0-10)
    score += min(10, (1 - pattern_data['depth'] / pattern_data['max_depth']) * 10)
    
    # Contraction du volume (0-10)
    score += min(10, (1 - pattern_data['volume_ratio']) * 10)
    
    # Propreté de la cassure (0-10)
    score += min(10, pattern_data['breakout_volume_ratio'] * 3.5)
    
    # Alignement avec tendance générale (0-10)
    score += 10 if ticker_data['price'] > ticker_data['ma50'] else 0
    
    # Contexte marché (0-10)
    score += 10 if market_is_bullish() else 5
    
    return score  # /50 — envoyer aux IA si score >= 30/50
```

---

## PHASE 3 — SYSTÈME MULTI-AGENTS

### 3.1 Architecture du débat

Le débat se déroule en 3 tours pour chaque ticker finaliste (score setup >= 30/50).

```
TOUR 1 : Analyses indépendantes (sans se voir)
TOUR 2 : Lecture croisée + révision possible
TOUR 3 : Vote final pondéré
```

### 3.2 Prompt DeepSeek (Tour 1)

```python
DEEPSEEK_PROMPT_T1 = """
Tu es un analyste technique expert. Analyse ce setup boursier et donne ton verdict.

TICKER : {ticker}
FIGURE DÉTECTÉE : {pattern_name}
DONNÉES TECHNIQUES :
- Prix actuel : {price}
- Mât : {pole_gain}% en {pole_candles} bougies
- Profondeur correction : {depth}%
- Ratio volume cassure : x{volume_ratio}
- RSI : {rsi}
- MACD : {macd_signal}
- MA20 : {ma20} | MA50 : {ma50}
- Score setup : {setup_score}/50

TON HISTORIQUE SUR CE TICKER :
{ticker_history}

TES PERFORMANCES RÉCENTES :
{agent_performance}

RÈGLES APPRISES PAR LE SYSTÈME :
{learned_rules}

Réponds UNIQUEMENT avec ce JSON :
{{
  "verdict": "ACHETER" ou "ATTENDRE" ou "IGNORER",
  "score": [0-10],
  "objectif_prix": [float],
  "stop_loss": [float],
  "horizon_jours": [int],
  "raison_principale": "[1 phrase courte]",
  "risque_principal": "[1 phrase courte]"
}}
"""
```

### 3.3 Prompt Grok (Tour 1)

```python
GROK_PROMPT_T1 = """
Tu es un analyste spécialisé dans le sentiment des réseaux sociaux et les actualités financières.

TICKER : {ticker} ({company_name})
SECTEUR : {sector}

Recherche sur X (Twitter) les informations des dernières 48h sur ce ticker.
Cherche aussi les actualités financières récentes.

Analyse :
1. Le sentiment général sur X (bullish/bearish/neutre)
2. Les catalyseurs positifs récents (annonces, partenariats, résultats)
3. Les risques mentionnés (rumeurs négatives, problèmes)
4. Le nombre de mentions et leur évolution
5. Les comptes influents qui ont pris position

RÈGLES APPRISES PAR LE SYSTÈME :
{learned_rules}

Réponds UNIQUEMENT avec ce JSON :
{{
  "verdict": "ACHETER" ou "ATTENDRE" ou "IGNORER",
  "score": [0-10],
  "sentiment_score": [-1 à +1],
  "mentions_24h": [int estimé],
  "catalyseur_positif": "[description ou null]",
  "risque_detecte": "[description ou null]",
  "confiance": [0-10],
  "raison_principale": "[1 phrase courte]"
}}
"""
```

### 3.4 Prompt Claude (Tour 1)

```python
CLAUDE_PROMPT_T1 = """
Tu es un analyste macro et fondamental prudent. Tu cherches les raisons pour lesquelles
un setup techniquement valide pourrait QUAND MÊME échouer.

TICKER : {ticker} ({company_name})
SECTEUR : {sector}
CAPITALISATION : {market_cap}
FIGURE : {pattern_name}
SCORE TECHNIQUE : {setup_score}/50

CONTEXTE MARCHÉ :
- SPX vs MA50 : {spx_status}
- VIX : {vix}
- Secteur en tendance : {sector_trend}
- Saison des résultats : {earnings_season}
- Prochains résultats : {next_earnings}

HISTORIQUE SYSTÈME :
{agent_performance}
{learned_rules}

Analyse les risques macro et fondamentaux. Sois le "avocat du diable" du système.

Réponds UNIQUEMENT avec ce JSON :
{{
  "verdict": "ACHETER" ou "ATTENDRE" ou "IGNORER",
  "score": [0-10],
  "taille_position_max_pct": [1-10],
  "risque_macro": "[1 phrase ou null]",
  "risque_fondamental": "[1 phrase ou null]",
  "risque_calendrier": "[1 phrase ou null]",
  "raison_principale": "[1 phrase courte]",
  "conseil_specifique": "[1 phrase courte]"
}}
"""
```

### 3.5 Tour 2 — Lecture croisée

Chaque IA reçoit les analyses des deux autres et peut réviser :

```python
DEBATE_ROUND2_PROMPT = """
Tu es {agent_name}. Voici ton analyse initiale :
{own_analysis}

Voici ce que les deux autres analystes ont dit :

{other_agent_1_name} : {other_analysis_1}
{other_agent_2_name} : {other_analysis_2}

Tu peux maintenir ta position ou la réviser si leurs arguments sont convaincants.
Ne cède pas à la pression sociale — révise uniquement si les arguments sont solides.

Réponds avec le même format JSON qu'au Tour 1, en ajoutant :
"position_changed": true/false,
"reason_for_change": "[explication si changement]"
"""
```

### 3.6 Tour 3 — Vote final pondéré

```python
def calculate_final_score(votes, weights):
    """
    votes = {
        "deepseek": {"verdict": "ACHETER", "score": 9},
        "grok": {"verdict": "ACHETER", "score": 8},
        "claude": {"verdict": "ATTENDRE", "score": 5}
    }
    weights = récupérés depuis Supabase (historique performances)
    """
    
    weighted_score = 0
    for agent, vote in votes.items():
        numeric = {"ACHETER": vote["score"], "ATTENDRE": 5, "IGNORER": 0}
        weighted_score += numeric[vote["verdict"]] * weights[agent]
    
    # Score final sur 100
    final_score = weighted_score * 10
    
    # Règle de consensus
    buy_votes = sum(1 for v in votes.values() if v["verdict"] == "ACHETER")
    
    return {
        "final_score": final_score,
        "buy_votes": buy_votes,
        "send_alert": final_score >= 75 and buy_votes >= 2
    }
```

### 3.7 Poids initiaux des IA

```python
INITIAL_WEIGHTS = {
    "deepseek": 0.33,
    "grok": 0.33,
    "claude": 0.34
}
# Les poids évoluent automatiquement chaque semaine
# selon les performances réelles de chaque IA
```

---

## PHASE 4 — MÉMOIRE CUMULATIVE (Supabase)

### 4.1 Migrations SQL

```sql
-- Table 1 : Tous les signaux envoyés
CREATE TABLE trading_signals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ticker VARCHAR(20) NOT NULL,
    pattern_name VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    entry_price DECIMAL(12,4) NOT NULL,
    target_price DECIMAL(12,4),
    stop_loss DECIMAL(12,4),
    setup_score INTEGER,
    final_score INTEGER,
    buy_votes INTEGER,
    horizon_days INTEGER,
    
    -- Résultat (rempli automatiquement J+1, J+3, J+7)
    result_1d DECIMAL(6,4),
    result_3d DECIMAL(6,4),
    result_7d DECIMAL(6,4),
    target_reached BOOLEAN DEFAULT FALSE,
    stop_reached BOOLEAN DEFAULT FALSE,
    
    -- Action de Rémy (via boutons Telegram)
    user_action VARCHAR(20),  -- 'pris', 'ignore', 'surveille'
    user_entry_price DECIMAL(12,4),
    user_exit_price DECIMAL(12,4),
    user_result DECIMAL(6,4)
);

-- Table 2 : Votes détaillés de chaque IA
CREATE TABLE ai_votes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    signal_id UUID REFERENCES trading_signals(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    agent_name VARCHAR(20) NOT NULL,  -- 'deepseek', 'grok', 'claude'
    tour INTEGER NOT NULL,             -- 1, 2, ou 3
    verdict VARCHAR(10) NOT NULL,
    score INTEGER NOT NULL,
    position_changed BOOLEAN DEFAULT FALSE,
    raw_response JSONB,
    weight_at_time DECIMAL(4,3)
);

-- Table 3 : Poids des IA (historique complet)
CREATE TABLE ai_weights (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    agent_name VARCHAR(20) NOT NULL,
    weight DECIMAL(4,3) NOT NULL,
    win_rate DECIMAL(4,3),
    total_signals INTEGER,
    correct_signals INTEGER,
    reason VARCHAR(200)
);

-- Table 4 : Règles apprises (jamais supprimées)
CREATE TABLE learned_rules (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    rule_description TEXT NOT NULL,
    rule_type VARCHAR(50),  -- 'market_condition', 'volume', 'pattern', 'timing'
    reliability DECIMAL(4,3),
    sample_size INTEGER,
    active BOOLEAN DEFAULT TRUE
);

-- Table 5 : Performance par ticker
CREATE TABLE ticker_performance (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    total_signals INTEGER DEFAULT 0,
    correct_signals INTEGER DEFAULT 0,
    win_rate DECIMAL(4,3),
    avg_gain DECIMAL(6,4),
    avg_loss DECIMAL(6,4),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    blacklisted BOOLEAN DEFAULT FALSE,
    blacklist_reason TEXT
);

-- Index pour les performances
CREATE INDEX idx_signals_ticker ON trading_signals(ticker);
CREATE INDEX idx_signals_created ON trading_signals(created_at);
CREATE INDEX idx_ai_votes_signal ON ai_votes(signal_id);
```

### 4.2 Brief quotidien envoyé à chaque IA

```python
def build_agent_brief(agent_name: str, ticker: str) -> str:
    """
    Construit le brief historique personnalisé pour chaque IA.
    Appelé à chaque analyse. Données récupérées depuis Supabase.
    """
    
    # Performance globale de l'agent
    global_perf = get_agent_performance(agent_name)
    
    # Performance de l'agent sur ce ticker spécifique
    ticker_perf = get_agent_ticker_performance(agent_name, ticker)
    
    # Règles apprises pertinentes (actives + fiabilité > 65%)
    rules = get_relevant_rules(ticker=ticker, agent=agent_name)
    
    return f"""
TON HISTORIQUE GLOBAL ({agent_name}) :
- Signaux analysés : {global_perf['total']}
- Taux de réussite : {global_perf['win_rate']*100:.1f}%
- Tes meilleures conditions : {global_perf['best_conditions']}
- Tes pires conditions : {global_perf['worst_conditions']}
- Ton poids actuel dans le vote : {global_perf['current_weight']*100:.0f}%

SUR CE TICKER ({ticker}) :
- Signaux passés : {ticker_perf['total']}
- Taux de réussite : {ticker_perf['win_rate']*100:.1f}%
- Résultats : {ticker_perf['summary']}

RÈGLES APPRISES PAR LE SYSTÈME (à respecter absolument) :
{chr(10).join([f"- {r['description']} (fiabilité {r['reliability']*100:.0f}%)" for r in rules])}
"""
```

### 4.3 Mise à jour automatique des résultats

```python
# Tâche quotidienne à 22h30 — vérifier les signaux ouverts
async def update_signal_results():
    open_signals = get_open_signals()
    
    for signal in open_signals:
        current_price = fetch_current_price(signal['ticker'])
        days_elapsed = (now() - signal['created_at']).days
        
        # Calculer le résultat
        result = (current_price - signal['entry_price']) / signal['entry_price']
        
        # Mettre à jour J+1, J+3, J+7
        update_signal_result(signal['id'], days_elapsed, result)
        
        # Vérifier si stop ou objectif atteint
        if current_price <= signal['stop_loss']:
            mark_stop_reached(signal['id'])
        if current_price >= signal['target_price']:
            mark_target_reached(signal['id'])
        
        # Recalculer les poids des IA si assez de données
        if len(open_signals) > 10:
            recalculate_ai_weights()
```

### 4.4 Recalcul hebdomadaire des poids des IA

```python
def recalculate_ai_weights():
    """Appelé chaque lundi matin"""
    
    for agent in ["deepseek", "grok", "claude"]:
        # Prendre les 30 derniers signaux où l'IA a voté ACHETER
        recent_votes = get_recent_buy_votes(agent, limit=30)
        
        if len(recent_votes) < 5:
            continue  # Pas assez de données
        
        # Calculer le taux de réussite
        correct = sum(1 for v in recent_votes if v['signal']['result_7d'] > 0)
        win_rate = correct / len(recent_votes)
        
        # Calculer le nouveau poids (entre 0.15 et 0.55)
        new_weight = max(0.15, min(0.55, win_rate))
        
        # Normaliser pour que la somme = 1
        save_new_weight(agent, new_weight)
        normalize_weights()
        
        log_weight_change(agent, new_weight, win_rate, len(recent_votes))
```

---

## PHASE 5 — ALERTES TELEGRAM

### 5.1 Configuration du bot

```python
TELEGRAM_CONFIG = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
}
```

### 5.2 Format de l'alerte principale

```python
def format_alert(signal_data: dict) -> str:
    
    verdict_emoji = "✅" if signal_data['final_score'] >= 85 else "⚡"
    
    message = f"""
{verdict_emoji} {signal_data['pattern_name'].upper()} — {signal_data['ticker']} | {signal_data['final_score']}/100
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 DeepSeek : {signal_data['deepseek_verdict']} {signal_data['deepseek_score']}/10
🐦 Grok     : {signal_data['grok_verdict']} {signal_data['grok_score']}/10
🧠 Claude   : {signal_data['claude_verdict']} {signal_data['claude_score']}/10

💰 Prix actuel  : {signal_data['price']}
🎯 Objectif     : {signal_data['target']} (+{signal_data['upside']:.1f}%)
🛑 Stop         : {signal_data['stop']} (-{signal_data['downside']:.1f}%)
⚖️  Position max : {signal_data['max_position_pct']}% du portefeuille
⏱️  Horizon      : {signal_data['horizon_days']} jours
📈 Timeframe    : {signal_data['timeframe']}

💬 DeepSeek : {signal_data['deepseek_reason']}
💬 Grok     : {signal_data['grok_reason']}
💬 Claude   : {signal_data['claude_reason']}
"""
    
    if signal_data['claude_warning']:
        message += f"\n⚠️ Claude : {signal_data['claude_warning']}"
    
    return message

# Boutons inline
ALERT_BUTTONS = [
    [("✅ Pris", "action_taken"), ("❌ Ignoré", "action_ignored")],
    [("⏳ Je surveille", "action_watching")]
]
```

### 5.3 Bilan quotidien (22h30)

```python
def format_daily_report(date: str) -> str:
    signals = get_today_signals()
    perf = calculate_today_performance()
    adjustments = get_today_adjustments()
    
    message = f"""
📊 BILAN DU {date}
━━━━━━━━━━━━━━━━━━━━━━━

Signaux envoyés : {len(signals)}
"""
    for s in signals:
        emoji = "✅" if s['result_1d'] > 0 else "❌" if s['result_1d'] < 0 else "⏳"
        message += f"{emoji} {s['ticker']} : {s['result_1d']*100:+.1f}%\n"
    
    message += f"""
Taux réussite semaine : {perf['week_win_rate']*100:.0f}%
Meilleure IA semaine  : {perf['best_agent']}

🔧 Ajustements automatiques :
{adjustments}
"""
    return message
```

### 5.4 Messages de mode (commandes Telegram)

```python
TELEGRAM_COMMANDS = {
    "/pause":   "Alertes suspendues. Tape /actif pour reprendre.",
    "/digest":  "Mode résumé activé. Une seule alerte à 22h.",
    "/actif":   "Alertes en temps réel activées.",
    "/bilan":   "Génère le bilan de la semaine en cours.",
    "/stats":   "Affiche les performances globales du système.",
    "/status":  "État actuel du système et prochain scan."
}
```

---

## PHASE 6 — PAPER TRADING (30 premiers jours)

```python
PAPER_TRADING_CONFIG = {
    "enabled": True,           # Désactivé manuellement par Rémy après validation
    "virtual_capital": 10000,  # Capital virtuel de référence
    "max_position_pct": 0.05,  # 5% max par position
    "start_date": None,        # Rempli automatiquement au premier lancement
}

# Chaque alerte → position virtuelle créée automatiquement
# Résultats calculés en temps réel
# Bilan complet à J+30 avec recommandation Go/No-Go argent réel
```

---

## PHASE 7 — WATCHLIST DYNAMIQUE

```python
# Chaque lundi à 8h00, reconstruire les 300 tickers dynamiques
async def rebuild_dynamic_watchlist():
    
    # Récupérer les actions avec volume inhabituel cette semaine
    high_volume_us = screen_high_volume_nasdaq(
        min_volume_ratio=1.5,
        min_variation_week=0.03,
        min_market_cap=100_000_000,
        limit=200
    )
    
    high_volume_eu = screen_high_volume_euronext(
        min_volume_ratio=1.5,
        min_variation_week=0.03,
        limit=100
    )
    
    # Exclure les tickers blacklistés en mémoire
    blacklisted = get_blacklisted_tickers()
    
    dynamic_tickers = [
        t for t in high_volume_us + high_volume_eu 
        if t not in blacklisted
    ][:300]
    
    save_dynamic_watchlist(dynamic_tickers)
    
    log(f"Watchlist dynamique reconstruite : {len(dynamic_tickers)} tickers")
```

---

## VARIABLES D'ENVIRONNEMENT REQUISES

```env
# APIs IA
DEEPSEEK_API_KEY=sk-...
GROK_API_KEY=xai-...
ANTHROPIC_API_KEY=sk-ant-...

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# Telegram
TELEGRAM_BOT_TOKEN=xxx:yyy
TELEGRAM_CHAT_ID=xxx

# Optionnel
POLYGON_API_KEY=xxx
```

---

## ORDRE DE CONSTRUCTION

### Session 1 — Fondations
1. Créer la structure des fichiers
2. Installer les dépendances (requirements.txt)
3. Configurer config.py et les variables d'environnement
4. Implémenter data_fetcher.py (Yahoo Finance + Polygon backup)
5. Implémenter market_filter.py (SPX + VIX)
6. Tester : récupérer des données sur 5 tickers, vérifier le filtre marché
7. Commit : "feat: fondations data et filtre marché"

### Session 2 — Watchlist et pré-filtre
1. Implémenter watchlist.py (fixe + dynamique)
2. Implémenter prefilter.py
3. Tester sur l'ensemble des 340 tickers
4. Vérifier que le pré-filtre retourne 15-40 candidats
5. Commit : "feat: watchlist et préfiltre algorithmique"

### Session 3 — Détection des figures
1. Implémenter les 7 fichiers dans patterns/
2. Implémenter le score de qualité setup
3. Tester chaque figure sur données historiques
4. Valider visuellement sur TradingView quelques détections
5. Commit : "feat: détection des 7 figures chartistes"

### Session 4 — Base de données
1. Exécuter les migrations SQL sur Supabase (fournir les blocs à Rémy)
2. Implémenter memory/database.py
3. Implémenter memory/signals.py et memory/weights.py
4. Tester les insertions et lectures
5. Commit : "feat: mémoire cumulative Supabase"

### Session 5 — Agents IA
1. Implémenter deepseek_agent.py
2. Implémenter grok_agent.py
3. Implémenter claude_agent.py
4. Implémenter debate.py (3 tours)
5. Tester sur 3 tickers réels avec logs détaillés
6. Commit : "feat: système multi-agents et débat"

### Session 6 — Telegram et alertes
1. Créer le bot Telegram (instructions à Rémy pour récupérer le token)
2. Implémenter telegram_bot.py avec boutons interactifs
3. Implémenter daily_report.py
4. Tester l'envoi d'une alerte complète
5. Commit : "feat: alertes Telegram et boutons feedback"

### Session 7 — Scheduler et intégration
1. Implémenter scheduler.py (4 scans/jour)
2. Implémenter main.py (boucle principale)
3. Implémenter le paper trading
4. Test complet end-to-end (un cycle complet simulé)
5. Déployer sur Supabase Edge Functions
6. Commit : "feat: scheduler et déploiement complet"

### Session 8 — Boucle d'apprentissage
1. Implémenter la mise à jour automatique des résultats (22h30)
2. Implémenter le recalcul hebdomadaire des poids
3. Implémenter la génération des règles apprises
4. Implémenter la watchlist dynamique hebdomadaire
5. Tester la boucle complète sur données simulées
6. Commit : "feat: boucle d'apprentissage et mémoire cumulative"

---

## RÈGLES MÉTIER NON NÉGOCIABLES

1. Jamais de signal baissier (short) — uniquement haussier
2. Jamais d'alerte si SPX < MA50 ou VIX > 30
3. Jamais d'alerte si score final < 75/100
4. Jamais d'alerte si moins de 2 IA sur 3 votent ACHETER
5. Toujours afficher un stop loss dans l'alerte
6. Toujours afficher une taille de position maximum
7. Paper trading obligatoire les 30 premiers jours
8. Jamais supprimer un enregistrement en base de données
9. Les poids des IA ne peuvent pas descendre sous 0.15 ni dépasser 0.55
10. Un ticker blacklisté ne peut pas être réintégré automatiquement
    (décision manuelle de Rémy uniquement)
