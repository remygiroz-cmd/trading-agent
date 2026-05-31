-- ════════════════════════════════════════════════════════════════
-- Migration 001 — Schéma initial de l'agent de surveillance boursière
-- À exécuter manuellement dans Supabase : SQL Editor → New query → Run
-- Projet dédié "trading-agent" — aucune table UpGraal n'est touchée.
-- ════════════════════════════════════════════════════════════════

-- Table 1 : Tous les signaux envoyés
CREATE TABLE IF NOT EXISTS trading_signals (
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

    -- Paper trading (30 premiers jours)
    is_paper BOOLEAN DEFAULT TRUE,

    -- Action de Rémy (via boutons Telegram)
    user_action VARCHAR(20),  -- 'pris', 'ignore', 'surveille'
    user_entry_price DECIMAL(12,4),
    user_exit_price DECIMAL(12,4),
    user_result DECIMAL(6,4)
);

-- Table 2 : Votes détaillés de chaque IA
CREATE TABLE IF NOT EXISTS ai_votes (
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
CREATE TABLE IF NOT EXISTS ai_weights (
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
CREATE TABLE IF NOT EXISTS learned_rules (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    rule_description TEXT NOT NULL,
    rule_type VARCHAR(50),  -- 'market_condition', 'volume', 'pattern', 'timing'
    reliability DECIMAL(4,3),
    sample_size INTEGER,
    active BOOLEAN DEFAULT TRUE
);

-- Table 5 : Performance par ticker
CREATE TABLE IF NOT EXISTS ticker_performance (
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
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON trading_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_created ON trading_signals(created_at);
CREATE INDEX IF NOT EXISTS idx_ai_votes_signal ON ai_votes(signal_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ticker_perf_ticker ON ticker_performance(ticker);

-- ════════════════════════════════════════════════════════════════
-- Note RLS : ce projet n'utilise QUE la clé service_role côté serveur,
-- jamais d'accès navigateur. On laisse RLS désactivé (par défaut) sur ces
-- tables. Ne pas exposer la clé anon publiquement.
-- ════════════════════════════════════════════════════════════════
