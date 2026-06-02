-- ════════════════════════════════════════════════════════════════
-- Migration 006 — Secteur sur les signaux (clustering sectoriel)
-- Permet de repérer quand plusieurs alertes tombent dans le même secteur le
-- même jour : secteur qui décolle (confirmation) vs bruit sectoriel isolé.
-- À exécuter dans Supabase : SQL Editor → New query → Run.
-- ════════════════════════════════════════════════════════════════

ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS sector VARCHAR(80);
CREATE INDEX IF NOT EXISTS idx_signals_sector ON trading_signals(sector);
