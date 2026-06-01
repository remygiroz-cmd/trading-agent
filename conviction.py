"""
conviction.py — Conviction composite, divergences, dimensionnement.

Croise les TROIS piliers de la décision en un seul indice 0-100 :
  - technique  : score final du débat des IA (/100)
  - fondamental: score de santé financière (/100)
  - sentiment  : sentiment des actualités (-1..+1)

Puis :
  1. DIVERGENCES — détecte les contradictions entre piliers (ex. technique forte
     mais fondamental fragile, ou sentiment négatif). Souvent les meilleurs
     filtres : un beau graphique sur une société qui se dégrade = piège fréquent.
  2. DIMENSIONNEMENT — déduit une taille de position avec vraie gestion du risque
     (risque max par trade plafonné, réduction si divergence, cap des IA).

Tout est transparent et borné par config.CONVICTION / config.SIZING.
"""

import config


# ─────────────────────────────────────────────────────────────
# NORMALISATION DES PILIERS (-> 0..1)
# ─────────────────────────────────────────────────────────────

def _norm_technique(final_score) -> float | None:
    if final_score is None:
        return None
    return max(0.0, min(1.0, float(final_score) / 100.0))


def _norm_fondamental(fund_score) -> float | None:
    if fund_score is None:
        return None
    return max(0.0, min(1.0, float(fund_score) / 100.0))


def _norm_sentiment(sentiment_score) -> float | None:
    if sentiment_score is None:
        return None
    return max(0.0, min(1.0, (float(sentiment_score) + 1.0) / 2.0))


# ─────────────────────────────────────────────────────────────
# CONVICTION COMPOSITE
# ─────────────────────────────────────────────────────────────

def compute_conviction(final_score=None, fundamental_score=None,
                       sentiment_score=None) -> dict:
    """
    Conviction 0-100 = moyenne pondérée des piliers DISPONIBLES (poids
    renormalisés). Retourne le détail par axe (valeur normalisée 0-1) + label.
    """
    w = config.CONVICTION["weights"]
    axes = {
        "technique": (_norm_technique(final_score), w["technique"]),
        "fondamental": (_norm_fondamental(fundamental_score), w["fondamental"]),
        "sentiment": (_norm_sentiment(sentiment_score), w["sentiment"]),
    }
    avail = {k: (v, wt) for k, (v, wt) in axes.items() if v is not None}
    total_w = sum(wt for _, wt in avail.values())
    if not avail or total_w == 0:
        return {"conviction": None, "label": "n/d", "axes": {}, "available": 0}

    score = sum(v * wt for v, wt in avail.values()) / total_w * 100
    conviction = round(score)
    label = ("très forte" if conviction >= 80 else "forte" if conviction >= 65
             else "moyenne" if conviction >= 50 else "faible")
    return {
        "conviction": conviction,
        "label": label,
        "axes": {k: round(v, 3) for k, (v, _) in avail.items()},
        "available": len(avail),
    }


# ─────────────────────────────────────────────────────────────
# DÉTECTION DE DIVERGENCES
# ─────────────────────────────────────────────────────────────

def detect_divergences(axes: dict) -> list[str]:
    """
    Compare les piliers normalisés et signale les contradictions notables.
    `axes` : {nom: valeur 0-1} (issu de compute_conviction).
    """
    c = config.CONVICTION
    strong, weak = c["strong"], c["weak"]
    tech = axes.get("technique")
    fond = axes.get("fondamental")
    senti = axes.get("sentiment")
    out = []

    if tech is not None and fond is not None:
        if tech >= strong and fond <= weak:
            out.append("Technique forte mais fondamental fragile (risque de piège)")
        elif fond >= strong and tech <= weak:
            out.append("Fondamental solide mais technique faible (pas encore le bon timing)")

    if tech is not None and senti is not None and tech >= strong and senti <= weak:
        out.append("Technique forte mais actualités négatives (vérifier le catalyseur)")

    if fond is not None and senti is not None and fond >= strong and senti <= weak:
        out.append("Bonne société mais flux d'actualités négatif")

    return out


# ─────────────────────────────────────────────────────────────
# DIMENSIONNEMENT DE LA POSITION
# ─────────────────────────────────────────────────────────────

def position_size(conviction, downside_pct=None, ai_max_pct=None,
                  has_divergence: bool = False) -> float:
    """
    Taille de position (% du portefeuille), gestion du risque incluse :
      - croît avec la conviction (du plancher au plafond) ;
      - réduite en cas de divergence ;
      - plafonnée par le risque max par trade (perte au stop) ;
      - plafonnée par la taille max suggérée par les IA (Claude) ;
      - la sécurité (risque) l'emporte toujours en dernier.
    `downside_pct` : distance au stop en % (ex. 8.0 pour -8%).
    """
    s = config.SIZING
    if conviction is None:
        conviction = s["conviction_floor"]

    # 1) Échelle de conviction (plancher -> plafond)
    span = (conviction - s["conviction_floor"]) / max(1e-9, (100 - s["conviction_floor"]))
    span = max(0.0, min(1.0, span))
    pct = s["min_pct"] + span * (s["max_pct"] - s["min_pct"])

    # 2) Pénalité de divergence
    if has_divergence:
        pct *= s["divergence_factor"]

    # 3) Cap des IA (prudence Claude)
    if ai_max_pct:
        pct = min(pct, float(ai_max_pct))

    # 4) Bornes globales
    pct = max(s["min_pct"], min(pct, s["max_pct"]))

    # 5) Cap par le risque max par trade (la sécurité gagne en dernier)
    if downside_pct and downside_pct > 0:
        risk_cap = s["max_risk_per_trade_pct"] / (downside_pct / 100.0)
        pct = min(pct, risk_cap)

    return round(max(pct, 0.5), 1)


# ─────────────────────────────────────────────────────────────
# SYNTHÈSE (pour signal + alerte)
# ─────────────────────────────────────────────────────────────

def evaluate(final_score=None, fundamental_score=None, sentiment_score=None,
             downside_pct=None, ai_max_pct=None) -> dict:
    """
    Synthèse complète prête pour l'enregistrement du signal et l'alerte.
    Retourne conviction, label, divergences, taille conseillée + textes.
    """
    conv = compute_conviction(final_score, fundamental_score, sentiment_score)
    divergences = detect_divergences(conv.get("axes", {}))
    has_div = bool(divergences)
    pct = position_size(conv.get("conviction"), downside_pct, ai_max_pct, has_div)

    conv_txt = (f"Conviction {conv['conviction']}/100 ({conv['label']})"
                if conv["conviction"] is not None else "Conviction : n/d")
    div_txt = (" ; ".join(divergences)) if divergences else ""

    return {
        "conviction": conv["conviction"],
        "conviction_label": conv["label"],
        "axes": conv.get("axes", {}),
        "divergences": divergences,
        "divergence": has_div,
        "suggested_position_pct": pct,
        "conviction_text": conv_txt,
        "divergence_text": div_txt,
    }
