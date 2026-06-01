-- ════════════════════════════════════════════════════════════════
-- Migration 004 — Mémoire des actualités (RAG financier)
-- Stocke les news par ticker pour les RETROUVER et les injecter dans le
-- contexte des IA (retrieval-augmented). La mémoire s'accumule dans le temps :
-- l'agent ne repart pas de zéro à chaque scan.
-- À exécuter dans Supabase : SQL Editor → New query → Run.
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS news_items (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    publisher VARCHAR(160),
    url TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    sentiment VARCHAR(10),            -- 'positif' / 'negatif' / 'neutre'
    sentiment_score DECIMAL(4,3),     -- -1.000 à +1.000
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_ticker ON news_items(ticker);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at);

-- Dé-duplication : une même URL n'est stockée qu'une fois par ticker.
-- (PostgreSQL traite les NULL comme distincts : les news sans URL ne bloquent pas.)
CREATE UNIQUE INDEX IF NOT EXISTS idx_news_ticker_url ON news_items(ticker, url);
