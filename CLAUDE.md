# CLAUDE.md — Agent de Surveillance Boursière

## Qui est Rémy

Rémy est le gérant de Frenchy Sushi, un restaurant japonais en activité depuis 2013 près d'Aix-en-Provence. Il a aussi fondé UpGraal, un SaaS de gestion de restaurant qu'il a construit avec de l'IA et qu'il commercialise. Il se décrit lui-même comme un "vibecoder" — il délègue toute la technique à l'IA, il ne code pas lui-même.

Il est investisseur particulier avec une bonne connaissance des marchés (analyse technique, RSI, MACD, supports/résistances), un PEA, un CTO, et des positions crypto. Il investit uniquement à la hausse, jamais en short.

Il a un emploi du temps chargé entre le restaurant et ses projets. Il ne peut pas être disponible en permanence.

## Comment lui parler

- Réponses courtes, simples, en français
- Zéro jargon technique
- Zéro grandes phrases d'introduction
- Si tu dois lui poser une question, une seule à la fois
- Ne jamais lui expliquer ce que tu vas faire — fais-le directement
- Ne jamais lui demander confirmation pour des décisions techniques — décide toi-même
- Si tu as le choix entre deux approches techniques, choisis la meilleure et avance

## Règle principale de travail

Travailler en autonomie maximale. Ne solliciter Rémy que si :
- Une clé API ou un identifiant lui appartenant est nécessaire
- Une décision métier impacte son argent réel
- Un choix irréversible doit être validé avant exécution

Pour tout le reste : décider, coder, tester, corriger, avancer.

## Stack technique du projet

- **Hébergement** : Supabase Edge Functions (Rémy a déjà un compte Supabase via UpGraal)
- **Base de données** : Supabase PostgreSQL (même instance qu'UpGraal si possible, sinon nouvelle)
- **Données marché** : Yahoo Finance (yfinance) en priorité, Polygon.io gratuit en backup
- **Alertes** : Telegram Bot (à créer)
- **IA analyse** : DeepSeek API (V4 Flash), Grok API (xAI), Claude API (Sonnet)
- **Langage** : Python 3.11+
- **Dépendances** : yfinance, pandas, ta-lib, requests, supabase-py, python-telegram-bot

## Règles de développement

- Toujours pousser sur la branche main sauf instruction contraire
- Les migrations SQL sont fournies en blocs bruts pour exécution manuelle via dashboard Supabase
- Commiter de façon incrémentale avec des messages clairs en français
- Tester chaque module avant de passer au suivant
- En cas d'erreur : corriger autonomement sans demander à Rémy
- Ne jamais toucher à la logique UpGraal si les projets partagent une instance Supabase
