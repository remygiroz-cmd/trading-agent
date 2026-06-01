"""
test_news.py — Validation de la mémoire actualités / RAG (sans réseau ni DB).

Teste le parsing (2 schémas yfinance), le sentiment lexical, le classement par
pertinence (RAG) et l'intégration dans les prompts. Aucune dépendance externe.

Lancer : python test_news.py
"""

import datetime as dt

import news
from agents import prompts

SEP = "─" * 60
ok = 0
ko = 0


def check(name, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        ko += 1
        print(f"  ❌ {name}")


print(SEP)
print("1. _parse_item : ancien schéma yfinance")
old = {"title": "Nvidia beats earnings, stock surges to record",
       "publisher": "Reuters", "link": "http://x/1",
       "providerPublishTime": 1_700_000_000}
it = news._parse_item(old, "NVDA")
check("titre extrait", it["title"].startswith("Nvidia beats"))
check("publisher extrait", it["publisher"] == "Reuters")
check("url extraite", it["url"] == "http://x/1")
check("date ISO", it["published_at"] and "T" in it["published_at"])
check("sentiment positif (beats/surges/record)", it["sentiment"] == "positif")

print(SEP)
print("2. _parse_item : schéma récent (content{})")
new = {"content": {"title": "SEC opens probe into company, shares plunge",
                   "summary": "A regulatory investigation was announced.",
                   "pubDate": "2026-05-30T12:00:00Z",
                   "provider": {"displayName": "Bloomberg"},
                   "canonicalUrl": {"url": "http://x/2"}}}
it2 = news._parse_item(new, "ABC")
check("titre extrait (content)", it2["title"].startswith("SEC opens probe"))
check("publisher extrait (content)", it2["publisher"] == "Bloomberg")
check("résumé extrait", "investigation" in (it2["summary"] or ""))
check("sentiment négatif (probe/plunge)", it2["sentiment"] == "negatif")

print(SEP)
print("3. _parse_item : robustesse")
check("dict vide -> None", news._parse_item({}, "X") is None)
check("non-dict -> None", news._parse_item("oops", "X") is None)
check("sans titre -> None", news._parse_item({"publisher": "x"}, "X") is None)

print(SEP)
print("4. sentiment lexical")
check("neutre si rien", news._sentiment("the company released a report")[0] == "neutre")
check("score borné [-1,1]", -1 <= news._sentiment("surge surge crash")[1] <= 1)
lbl, sc = news._sentiment("record contract win deal partnership")
check("positif net", lbl == "positif" and sc > 0)

print(SEP)
print("5. aggregate_sentiment")
items = [{"sentiment_score": 0.5}, {"sentiment_score": 0.7}, {"sentiment_score": -0.2}]
agg = news.aggregate_sentiment(items)
check("compte positifs/négatifs", agg["pos"] == 2 and agg["neg"] == 1)
check("label positif (moyenne > 0.1)", agg["label"] == "positif")
check("liste vide -> n/d", news.aggregate_sentiment([])["label"] == "n/d")

print(SEP)
print("6. classement RAG (pertinence x récence)")
today = dt.datetime.now(dt.timezone.utc)
recent = (today - dt.timedelta(days=1)).isoformat()
old_d = (today - dt.timedelta(days=12)).isoformat()
a = {"title": "bull flag breakout on strong volume", "summary": "",
     "published_at": recent, "sentiment_score": 0.4}
b = {"title": "company announces dividend", "summary": "",
     "published_at": old_d, "sentiment_score": 0.0}
terms = {"bull", "flag", "breakout"}
sa = news._score_relevance(a, terms)
sb = news._score_relevance(b, terms)
check("news pertinente+récente mieux notée", sa > sb)
check("récence : récent > ancien (mêmes termes)",
      news._score_relevance({"title": "x", "published_at": recent}, set())
      > news._score_relevance({"title": "x", "published_at": old_d}, set()))

print(SEP)
print("7. format_for_prompt")
txt = news.format_for_prompt([it, it2])
check("contient les titres", "Nvidia" in txt and "SEC opens probe" in txt)
check("vide -> message lisible", "Aucune actualité" in news.format_for_prompt([]))

print(SEP)
print("8. intégration prompts (champs news présents, pas de KeyError)")
ctx = {"ticker": "NVDA", "company_name": "Nvidia",
       "news_context": "▲ [2026-05-30] Big news (Reuters)",
       "news_sentiment": "Sentiment actualités : positif"}
for name, tmpl in [("deepseek", prompts.DEEPSEEK_PROMPT_T1),
                   ("grok", prompts.GROK_PROMPT_T1),
                   ("claude", prompts.CLAUDE_PROMPT_T1)]:
    filled = prompts.fill(tmpl, ctx)
    check(f"{name} : bloc actualités injecté", "Big news" in filled)
    check(f"{name} : pas de placeholder {{news_context}} résiduel",
          "{news_context}" not in filled)

print(SEP)
print(f"RÉSULTAT : {ok} OK, {ko} KO")
if ko:
    raise SystemExit(1)
print("Tous les tests passent ✅")
