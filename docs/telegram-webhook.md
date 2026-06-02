# Réponses instantanées Telegram (webhook Supabase)

Objectif : le bot répond à tes commandes (`/stats`, `/paper`…) en 1-2 secondes,
24h/24, sans dépendre de GitHub Actions. Telegram envoie chaque message à une
petite fonction hébergée sur ton Supabase.

À faire **une seule fois**. Compte ~10 minutes.

---

## 1. Déployer la fonction sur Supabase

La fonction est dans `supabase/functions/telegram-webhook/index.ts`.

### Option A — via le terminal (CLI Supabase)
```bash
# installer la CLI si besoin : https://supabase.com/docs/guides/cli
supabase login
supabase link --project-ref TON_PROJECT_REF      # ref visible dans l'URL du dashboard
supabase functions deploy telegram-webhook --no-verify-jwt
```

### Option B — via le dashboard Supabase (sans terminal)
1. Dashboard Supabase → **Edge Functions** → **Create a function**.
2. Nomme-la exactement `telegram-webhook`.
3. Colle le contenu de `supabase/functions/telegram-webhook/index.ts`.
4. **Désactive "Verify JWT"** (la fonction gère sa propre sécurité par secret).
5. Deploy.

L'URL de la fonction ressemble à :
`https://TON_PROJECT_REF.supabase.co/functions/v1/telegram-webhook`

---

## 2. Donner ses secrets à la fonction

Dans le dashboard → Edge Functions → telegram-webhook → **Secrets** (ou via CLI) :

```bash
supabase secrets set TELEGRAM_BOT_TOKEN="ton_token_bot"
supabase secrets set TELEGRAM_WEBHOOK_SECRET="invente_une_longue_chaine_aleatoire"
```

`SUPABASE_URL` et `SUPABASE_SERVICE_ROLE_KEY` sont déjà fournis automatiquement.

> Le `TELEGRAM_WEBHOOK_SECRET` est juste un mot de passe que tu inventes : il
> empêche n'importe qui d'appeler ta fonction. Garde-le, tu en as besoin à
> l'étape suivante.

---

## 3. Activer le webhook côté Telegram

Le plus simple : **ouvrir une adresse dans ton navigateur** (aucun terminal).

Prends cette adresse et remplace les 3 morceaux en MAJUSCULES :

```
https://api.telegram.org/botTON_TOKEN/setWebhook?url=https://TON_PROJECT_REF.supabase.co/functions/v1/telegram-webhook&secret_token=TON_SECRET
```

- `TON_TOKEN` = le token de ton bot (donné par @BotFather sur Telegram)
- `TON_PROJECT_REF` = la référence de ton projet Supabase (dans l'URL du dashboard)
- `TON_SECRET` = le même secret qu'à l'étape 2

Colle l'adresse complète dans la barre d'adresse d'un navigateur, appuie sur Entrée.
Si tu vois `{"ok":true,...}`, c'est gagné. Teste : envoie `/stats` à ton bot, la
réponse arrive en 1-2 s.

> Variante terminal (optionnelle) :
> `python main.py set-webhook "https://TON_PROJECT_REF.supabase.co/functions/v1/telegram-webhook" "TON_SECRET"`

---

## Revenir en arrière

Pour désactiver le webhook et revenir à la relève périodique :
```bash
python main.py delete-webhook
```

## Notes
- Tant que le webhook est actif, la relève par GitHub Actions ne reçoit plus les
  commandes (Telegram n'autorise qu'un seul mode à la fois) — c'est normal.
- Les **alertes** et le **bilan du soir** continuent de partir via GitHub Actions,
  indépendamment du webhook.
- Commandes gérées en instantané : `/stats`, `/paper`, `/diag`, `/status`,
  `/pause`, `/actif`, `/digest`, `/help` + les boutons Pris/Ignoré/Surveille.
