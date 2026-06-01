"""
news.py — Mémoire des actualités financières + récupération (RAG).

Pipeline retrieval-augmented :
  1. INGESTION : on récupère les news par ticker (Yahoo Finance, gratuit) et on
     les stocke dans Supabase (table news_items), dédupliquées par URL. La mémoire
     s'accumule : l'agent garde une trace des catalyseurs passés.
  2. RÉCUPÉRATION : pour une décision, on retrouve les news récentes les plus
     pertinentes (récence + correspondance de mots-clés), façon BM25 léger.
  3. AUGMENTATION : ces news (+ un sentiment agrégé) sont injectées dans le
     contexte des trois IA avant le débat -> décision étayée par l'actualité réelle.

Choix de conception : récupération LEXICALE (pas d'embeddings) pour rester sans
clé API supplémentaire ni dépendance lourde, tout en étant robuste. Les news étant
déjà filtrées par ticker, le lexical suffit pour hiérarchiser pertinence/récence.
Un backend vectoriel (pgvector) pourra être branché plus tard sans changer l'API.

Dégradation gracieuse : si Supabase est indisponible, on récupère les news en
direct (sans persistance) ; si le réseau échoue, on renvoie un contexte vide.
"""

import logging
import datetime as dt

logger = logging.getLogger("news")

TABLE = "news_items"

# Lexiques de sentiment (FR + EN) — léger, déterministe, sans appel IA.
POSITIVE = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "jump", "jumps",
    "record", "upgrade", "upgraded", "outperform", "buy", "bullish", "growth",
    "profit", "profits", "wins", "win", "contract", "deal", "partnership", "approval",
    "approved", "breakthrough", "raises", "raise", "boost", "strong", "gains", "gain",
    "hausse", "bond", "record", "contrat", "partenariat", "rachat", "relèvement",
    "dépasse", "croissance", "bénéfice", "bénéfices", "succès", "feu vert", "positif",
}
NEGATIVE = {
    "miss", "misses", "plunge", "plunges", "drop", "drops", "fall", "falls", "crash",
    "downgrade", "downgraded", "underperform", "sell", "bearish", "loss", "losses",
    "lawsuit", "probe", "investigation", "recall", "cuts", "cut", "warning", "warns",
    "fraud", "weak", "decline", "declines", "bankruptcy", "default", "halt", "delay",
    "baisse", "chute", "perte", "pertes", "enquête", "plainte", "procès", "alerte",
    "avertissement", "rappel", "faible", "recul", "négatif", "fraude", "sanction",
}


# ─────────────────────────────────────────────────────────────
# RÉCUPÉRATION BRUTE (Yahoo Finance, gratuit)
# ─────────────────────────────────────────────────────────────

def _parse_pubdate(raw) -> str | None:
    """Normalise une date de publication (epoch int ou ISO str) en ISO 8601."""
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            return dt.datetime.fromtimestamp(raw, dt.timezone.utc).isoformat()
        s = str(raw).replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _parse_item(raw: dict, ticker: str) -> dict | None:
    """
    Normalise une news yfinance. Gère les DEUX schémas connus :
      - ancien : {title, publisher, link, providerPublishTime}
      - récent : {content: {title, summary, pubDate, provider:{displayName},
                            canonicalUrl:{url}}}
    """
    if not isinstance(raw, dict):
        return None
    content = raw.get("content") if isinstance(raw.get("content"), dict) else None

    if content:  # schéma récent
        title = content.get("title")
        summary = content.get("summary") or content.get("description")
        prov = content.get("provider") or {}
        publisher = prov.get("displayName") if isinstance(prov, dict) else None
        cu = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        url = cu.get("url") if isinstance(cu, dict) else None
        published = _parse_pubdate(content.get("pubDate") or content.get("displayTime"))
    else:  # ancien schéma
        title = raw.get("title")
        summary = raw.get("summary")
        publisher = raw.get("publisher")
        url = raw.get("link")
        published = _parse_pubdate(raw.get("providerPublishTime"))

    if not title:
        return None
    text = f"{title} {summary or ''}"
    label, score = _sentiment(text)
    return {
        "ticker": ticker,
        "title": title.strip()[:500],
        "summary": (summary or "").strip()[:1000] or None,
        "publisher": (publisher or "")[:160] or None,
        "url": url,
        "published_at": published,
        "sentiment": label,
        "sentiment_score": score,
    }


def fetch_ticker_news(ticker: str, limit: int = 12) -> list[dict]:
    """Récupère les news brutes d'un ticker via yfinance (normalisées)."""
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).news or []
    except Exception as e:  # noqa: BLE001
        logger.debug("news %s indisponibles : %s", ticker, str(e)[:80])
        return []
    items = []
    for r in raw[:limit]:
        it = _parse_item(r, ticker)
        if it:
            items.append(it)
    return items


# ─────────────────────────────────────────────────────────────
# SENTIMENT LEXICAL
# ─────────────────────────────────────────────────────────────

def _tokens(text: str) -> list[str]:
    return [t.strip(".,!?;:()[]\"'").lower() for t in (text or "").split()]


def _sentiment(text: str) -> tuple[str, float]:
    """Sentiment lexical -> (label, score dans [-1, +1])."""
    toks = _tokens(text)
    if not toks:
        return "neutre", 0.0
    pos = sum(1 for t in toks if t in POSITIVE)
    neg = sum(1 for t in toks if t in NEGATIVE)
    if pos == neg:
        return "neutre", 0.0
    score = (pos - neg) / (pos + neg)
    label = "positif" if score > 0 else "negatif"
    return label, round(score, 3)


def aggregate_sentiment(items: list[dict]) -> dict:
    """Sentiment global d'un lot de news (moyenne pondérée simple)."""
    if not items:
        return {"label": "n/d", "score": 0.0, "pos": 0, "neg": 0, "n": 0}
    scores = [float(i.get("sentiment_score") or 0) for i in items]
    pos = sum(1 for s in scores if s > 0)
    neg = sum(1 for s in scores if s < 0)
    avg = sum(scores) / len(scores)
    label = "positif" if avg > 0.1 else "negatif" if avg < -0.1 else "neutre"
    return {"label": label, "score": round(avg, 3), "pos": pos, "neg": neg, "n": len(items)}


# ─────────────────────────────────────────────────────────────
# PERSISTANCE (Supabase)
# ─────────────────────────────────────────────────────────────

def _existing_urls(ticker: str) -> set:
    try:
        from memory import database
        rows = (database.table(TABLE).select("url")
                .eq("ticker", ticker).limit(500).execute()).data or []
        return {r["url"] for r in rows if r.get("url")}
    except Exception as e:  # noqa: BLE001
        logger.debug("lecture urls %s KO : %s", ticker, str(e)[:60])
        return set()


def ingest(ticker: str) -> int:
    """Récupère + stocke les news nouvelles d'un ticker. Retourne le nb stockées."""
    items = fetch_ticker_news(ticker)
    if not items:
        return 0
    try:
        from memory import database
        known = _existing_urls(ticker)
        fresh = [i for i in items if not i.get("url") or i["url"] not in known]
        if not fresh:
            return 0
        database.table(TABLE).insert(fresh).execute()
        logger.info("News %s : %s stockées", ticker, len(fresh))
        return len(fresh)
    except Exception as e:  # noqa: BLE001
        logger.debug("Persistance news %s KO : %s", ticker, str(e)[:80])
        return 0


def get_recent(ticker: str, days: int = 10, limit: int = 20) -> list[dict]:
    """News récentes d'un ticker depuis la base. Repli : récupération en direct."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    try:
        from memory import database
        rows = (database.table(TABLE).select("*")
                .eq("ticker", ticker)
                .gte("published_at", cutoff)
                .order("published_at", desc=True)
                .limit(limit).execute()).data or []
        if rows:
            return rows
    except Exception as e:  # noqa: BLE001
        logger.debug("get_recent %s DB KO : %s", ticker, str(e)[:60])
    # Repli sans persistance
    return fetch_ticker_news(ticker, limit=limit)


# ─────────────────────────────────────────────────────────────
# RÉCUPÉRATION PERTINENTE (RAG)
# ─────────────────────────────────────────────────────────────

def _recency_weight(published_at: str | None) -> float:
    """1.0 pour aujourd'hui -> décroît vers 0 sur ~14 jours."""
    if not published_at:
        return 0.3
    try:
        d = dt.datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
        age = (dt.datetime.now(dt.timezone.utc) - d).days
        return max(0.1, 1.0 - age / 14.0)
    except Exception:  # noqa: BLE001
        return 0.3


def _score_relevance(item: dict, terms: set) -> float:
    """Score = pertinence lexicale (recouvrement de mots-clés) x récence + |sentiment|."""
    text_toks = set(_tokens(f"{item.get('title','')} {item.get('summary','')}"))
    overlap = len(text_toks & terms) if terms else 0
    base = 1.0 + overlap  # toujours >0 pour garder la récence comme tri par défaut
    rec = _recency_weight(item.get("published_at"))
    senti = abs(float(item.get("sentiment_score") or 0))
    return base * rec + 0.5 * senti


def retrieve(ticker: str, terms: set | None = None, days: int = 10, k: int = 4) -> list[dict]:
    """Récupère les k news les plus pertinentes (pertinence x récence)."""
    items = get_recent(ticker, days=days, limit=30)
    ranked = sorted(items, key=lambda i: _score_relevance(i, terms or set()), reverse=True)
    return ranked[:k]


def format_for_prompt(items: list[dict]) -> str:
    """Formate les news pour injection dans un prompt IA."""
    if not items:
        return "Aucune actualité récente trouvée."
    lines = []
    for it in items:
        d = (it.get("published_at") or "")[:10]
        pub = it.get("publisher") or "?"
        senti = it.get("sentiment") or "neutre"
        tag = {"positif": "▲", "negatif": "▼", "neutre": "•"}.get(senti, "•")
        lines.append(f"{tag} [{d}] {it.get('title')} ({pub})")
    return "\n".join(lines)


def news_context(ticker: str, company_name: str = "", terms: set | None = None,
                 ingest_first: bool = True, k: int = 4) -> dict:
    """
    Bloc d'actualités prêt pour le contexte IA :
      - ingère les news fraîches (mémoire),
      - récupère les plus pertinentes,
      - calcule un sentiment agrégé.
    Retourne {"text", "sentiment_text", "sentiment", "items"}.
    """
    base_terms = set(_tokens(f"{ticker} {company_name}"))
    terms = (terms or set()) | base_terms

    if ingest_first:
        try:
            ingest(ticker)
        except Exception as e:  # noqa: BLE001
            logger.debug("ingest %s KO : %s", ticker, str(e)[:60])

    items = retrieve(ticker, terms=terms, k=k)
    agg = aggregate_sentiment(items)
    sentiment_text = (
        f"Sentiment actualités : {agg['label']} (score {agg['score']:+.2f}, "
        f"{agg['pos']} positives / {agg['neg']} négatives sur {agg['n']})"
        if agg["n"] else "Sentiment actualités : pas de données."
    )
    return {
        "text": format_for_prompt(items),
        "sentiment_text": sentiment_text,
        "sentiment": agg,
        "items": items,
    }


def refresh_watchlist_news(tickers: list[str], max_tickers: int = 40) -> int:
    """Ingestion quotidienne pour accumuler la mémoire au-delà des finalistes."""
    total = 0
    for tk in tickers[:max_tickers]:
        try:
            total += ingest(tk)
        except Exception:  # noqa: BLE001
            continue
    logger.info("Refresh news watchlist : %s news stockées (%s tickers)",
                total, min(len(tickers), max_tickers))
    return total


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    out = news_context(tk)
    print(f"\n=== ACTUALITÉS {tk} ===")
    print(out["sentiment_text"])
    print(out["text"])
