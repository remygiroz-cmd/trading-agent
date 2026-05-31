# Déploiement de l'agent

## Pourquoi pas Supabase Edge Functions

Les specs prévoyaient un hébergement sur Supabase Edge Functions. **Ce n'est pas
possible** : les Edge Functions tournent en Deno/TypeScript, alors que tout
l'agent est en Python (et `yfinance` n'existe qu'en Python). Supabase reste
utilisé pour la **base de données** (c'est fait), mais pas pour l'exécution.

## Solution retenue : GitHub Actions (cron) — gratuit

L'agent tourne par à-coups (4 scans/jour + bilan), pas en continu : c'est le cas
d'usage idéal pour un cron planifié. GitHub Actions est gratuit pour ça.

Le workflow `.github/workflows/agent.yml` :
- se déclenche aux horaires des scans (été + hiver, fuseau Paris géré par le code)
- exécute `python main.py cron` qui choisit la tâche selon l'heure de Paris
- lit les clés depuis les **GitHub Secrets** (jamais dans le code)

### Activation (à faire une fois)

1. Créer un repo GitHub privé et y pousser ce projet
   (le `.env` est ignoré par git — les secrets n'y montent pas).
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**,
   ajouter :
   - `DEEPSEEK_API_KEY`, `GROK_API_KEY`, `ANTHROPIC_API_KEY`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - (`POLYGON_API_KEY` optionnel)
3. Onglet **Actions** → activer les workflows.
4. Tester via **workflow_dispatch** (bouton "Run workflow").

## Alternative : machine toujours allumée

Si tu préfères un serveur perso / Raspberry Pi / petit VPS, lancer simplement :

```bash
python scheduler.py        # boucle continue, déclenche les scans aux horaires
```

## Commandes manuelles utiles

```bash
python main.py scan ouverture     # un scan immédiat
python main.py test-cycle         # cycle complet sans envoyer d'alerte
python main.py report             # bilan quotidien
python main.py rebuild-watchlist  # reconstruit la watchlist dynamique
python main.py cron               # dispatcher horaire (utilisé par GitHub Actions)
```
