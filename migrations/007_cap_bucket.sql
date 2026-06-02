-- ════════════════════════════════════════════════════════════════
-- Migration 007 — Taille de capitalisation sur les signaux (méta-apprentissage)
-- Permet d'apprendre quelle IA est la meilleure selon le segment :
-- small / mid / large caps. Combiné au secteur (migration 006), le bot pondère
-- le débat selon là où chaque IA a fait ses preuves.
-- À exécuter dans Supabase : SQL Editor → New query → Run.
-- ════════════════════════════════════════════════════════════════

ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS cap_bucket VARCHAR(10);
CREATE INDEX IF NOT EXISTS idx_signals_cap_bucket ON trading_signals(cap_bucket);
