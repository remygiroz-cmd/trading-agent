-- ════════════════════════════════════════════════════════════════
-- Migration 005 — Conviction composite, divergences, dimensionnement
-- Ajoute à trading_signals les colonnes analytiques croisant les 3 piliers
-- (technique / fondamental / sentiment). Permet aussi de MESURER, signal après
-- signal, lequel prédit le mieux les gains (attribution sans biais).
-- À exécuter dans Supabase : SQL Editor → New query → Run.
-- ════════════════════════════════════════════════════════════════

ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS news_sentiment DECIMAL(4,3);
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS fundamental_score INTEGER;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS conviction INTEGER;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS divergence BOOLEAN DEFAULT FALSE;
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS suggested_position_pct DECIMAL(5,2);
