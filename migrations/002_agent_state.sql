-- ════════════════════════════════════════════════════════════════
-- Migration 002 — Table d'état persistant (clé-valeur)
-- Nécessaire pour le déploiement cloud (GitHub Actions = FS éphémère).
-- Stocke : watchlist dynamique, état paper trading, mode d'alerte,
-- offset Telegram, marqueurs anti-doublon des scans.
-- À exécuter dans Supabase : SQL Editor → New query → Run.
-- ════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_state (
    key TEXT PRIMARY KEY,
    value JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
