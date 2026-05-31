-- ════════════════════════════════════════════════════════════════
-- Migration 003 — Clôture simulée des positions (paper trading)
-- Ajoute le résultat "vente simulée" : sortie à l'objectif, au stop, ou à la
-- fin de l'horizon (le premier atteint), avec prix/%/plus-value.
-- À exécuter dans Supabase : SQL Editor → New query → Run.
-- ════════════════════════════════════════════════════════════════

ALTER TABLE trading_signals
    ADD COLUMN IF NOT EXISTS closed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS exit_price DECIMAL(12,4),
    ADD COLUMN IF NOT EXISTS exit_date TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS exit_reason VARCHAR(20),   -- 'objectif' | 'stop' | 'horizon'
    ADD COLUMN IF NOT EXISTS realized_pct DECIMAL(8,4),
    ADD COLUMN IF NOT EXISTS realized_pnl_eur DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS hold_days INTEGER;
