# Minuteur fiable via Supabase (fini les créneaux sautés)

GitHub Actions saute parfois ses horaires. On confie donc le **déclenchement** à
Supabase (fiable), qui réveille GitHub à l'heure pile. À faire **une fois**.

## 1. Créer un token GitHub (le « passe » pour réveiller GitHub)
1. https://github.com/settings/tokens?type=beta → **Generate new token** (fine-grained).
2. **Repository access** → Only select repositories → `remygiroz-cmd/trading-agent`.
3. **Permissions** → Repository permissions → **Actions** → **Read and write**.
4. Génère et **copie** le token (`github_pat_...`).

## 2. Déployer la fonction
Comme pour le webhook : Supabase → **Edge Functions** → **Create a function** →
nom `trigger-agent` → colle le contenu de
`supabase/functions/trigger-agent/index.ts` → **Verify JWT désactivé** → Deploy.

Puis ajoute le secret :
- Nom : `GH_TOKEN`  ·  Valeur : le token `github_pat_...` de l'étape 1.

## 3. Planifier (Supabase Cron)
Supabase → **Integrations → Cron** (ou « Schedules ») → **Create a new cron job** :
- Schedule : `*/15 6-22 * * 1-5`  (toutes les 15 min, en semaine, ~8h-minuit Paris)
- Type : **Supabase Edge Function** → `trigger-agent`

C'est tout. Supabase réveille GitHub toutes les 15 min ; le code Python (`run_due`)
décide alors quoi faire (buzz du matin, scans, bilan du soir) avec son rattrapage.
Plus aucun créneau sauté.

> Pourquoi toutes les 15 min plutôt qu'aux horaires exacts : une seule ligne à
> configurer, et le rattrapage Python gère l'horaire précis de chaque tâche.

## 4. (Optionnel) Alléger GitHub
Une fois ce minuteur en place, les `schedule:` du fichier `.github/workflows/agent.yml`
font doublon. On peut les retirer pour économiser des minutes GitHub — dis-le moi
et je m'en occupe.
