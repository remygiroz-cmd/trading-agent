"""
dashboard.py — Tableau de bord des performances.

Deux sorties à partir des signaux stockés dans Supabase :
  1. un RÉSUMÉ TEXTE pour Telegram (commande /stats) — consultable depuis le tél ;
  2. un DASHBOARD HTML autonome (mobile-friendly, sans dépendance externe) que
     l'on peut t'envoyer en pièce jointe Telegram ou publier sur GitHub Pages.

Les agrégats sont des fonctions PURES (testables sans réseau) ; la récupération
des données et le rendu sont séparés. Le taux de réussite se base sur le résultat
à J+7 (result_7d), cohérent avec le reste du système.
"""

import html
import logging
import datetime as dt

logger = logging.getLogger("dashboard")


# ─────────────────────────────────────────────────────────────
# RÉCUPÉRATION
# ─────────────────────────────────────────────────────────────

def fetch_signals(limit: int = 1000) -> list[dict]:
    """Tous les signaux (récents d'abord)."""
    try:
        from memory import database
        return (database.table("trading_signals").select("*")
                .order("created_at", desc=True).limit(limit).execute()).data or []
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_signals KO : %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# AGRÉGATS (purs)
# ─────────────────────────────────────────────────────────────

def _closed(signals: list[dict]) -> list[dict]:
    return [s for s in signals if s.get("result_7d") is not None]


def global_stats(signals: list[dict]) -> dict:
    """Stats globales sur les signaux clos (result_7d connu)."""
    closed = _closed(signals)
    n = len(closed)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "avg_gain": 0.0, "avg_loss": 0.0,
                "expectancy": 0.0, "best": 0.0, "worst": 0.0, "pnl_eur": 0.0, "open": len(signals)}
    res = [float(s["result_7d"]) for s in closed]
    gains = [r for r in res if r > 0]
    losses = [r for r in res if r <= 0]
    pnl = sum(float(s["realized_pnl_eur"]) for s in signals
              if s.get("realized_pnl_eur") is not None)
    return {
        "n": n,
        "win_rate": len(gains) / n,
        "avg_gain": (sum(gains) / len(gains)) if gains else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "expectancy": sum(res) / n,
        "best": max(res),
        "worst": min(res),
        "pnl_eur": pnl,
        "open": len(signals) - n,
    }


def winrate_by(signals: list[dict], key: str, min_n: int = 1) -> list[dict]:
    """
    Taux de réussite groupé par champ (`sector`, `cap_bucket`, `pattern_name`…).
    Retourne une liste triée par effectif décroissant.
    """
    groups: dict[str, list[float]] = {}
    for s in _closed(signals):
        k = s.get(key)
        if k in (None, "", "n/d"):
            continue
        groups.setdefault(str(k), []).append(float(s["result_7d"]))
    out = []
    for k, res in groups.items():
        if len(res) < min_n:
            continue
        wins = sum(1 for r in res if r > 0)
        out.append({"key": k, "n": len(res), "win_rate": wins / len(res),
                    "avg": sum(res) / len(res)})
    return sorted(out, key=lambda d: -d["n"])


CONV_TIERS = [("80-100", 80, 101), ("65-79", 65, 80), ("50-64", 50, 65), ("0-49", 0, 50)]


def winrate_by_conviction(signals: list[dict]) -> list[dict]:
    """Taux de réussite par tranche de conviction."""
    out = []
    closed = [s for s in _closed(signals) if s.get("conviction") is not None]
    for label, lo, hi in CONV_TIERS:
        res = [float(s["result_7d"]) for s in closed if lo <= int(s["conviction"]) < hi]
        if not res:
            continue
        wins = sum(1 for r in res if r > 0)
        out.append({"key": label, "n": len(res), "win_rate": wins / len(res),
                    "avg": sum(res) / len(res)})
    return out


def divergence_stats(signals: list[dict]) -> dict:
    """Compare la réussite avec vs sans divergence."""
    closed = _closed(signals)
    def wr(rows):
        res = [float(s["result_7d"]) for s in rows]
        return {"n": len(res), "win_rate": (sum(1 for r in res if r > 0) / len(res)) if res else 0.0}
    return {
        "avec": wr([s for s in closed if s.get("divergence")]),
        "sans": wr([s for s in closed if not s.get("divergence")]),
    }


def agent_stats() -> list[dict]:
    """Performance par IA (réutilise weights.get_agent_performance)."""
    out = []
    try:
        from memory import weights
        for agent in weights.AGENTS:
            p = weights.get_agent_performance(agent)
            out.append({"key": agent, "n": p.get("total", 0),
                        "win_rate": p.get("win_rate", 0.0),
                        "weight": p.get("current_weight", 0.33)})
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_stats KO : %s", e)
    return out


# ─────────────────────────────────────────────────────────────
# RÉSUMÉ TEXTE (Telegram /stats)
# ─────────────────────────────────────────────────────────────

def _pct(x: float) -> str:
    return f"{x*100:+.1f}%"


def build_text_summary(signals: list[dict] | None = None) -> str:
    if signals is None:
        signals = fetch_signals()
    g = global_stats(signals)
    if g["n"] == 0:
        return ("📈 Performances\n"
                f"Aucun signal clos pour l'instant ({g['open']} en cours).\n"
                "Le taux de réussite s'affichera dès les premiers résultats à J+7.")

    lines = [
        "📈 *Performances globales*",
        f"Signaux clos : {g['n']} ({g['open']} en cours)",
        f"Taux de réussite : {g['win_rate']*100:.0f}%",
        f"Gain moyen gagnants : {_pct(g['avg_gain'])} | perte moyenne : {_pct(g['avg_loss'])}",
        f"Espérance/trade : {_pct(g['expectancy'])}",
        f"P&L paper (1000€/trade) : {g['pnl_eur']:+,.0f}€",
    ]

    def block(title, rows, fmt_extra=None):
        if not rows:
            return []
        out = [f"\n{title}"]
        for r in rows[:6]:
            extra = fmt_extra(r) if fmt_extra else ""
            out.append(f"  {r['key']} : {r['win_rate']*100:.0f}% ({r['n']}){extra}")
        return out

    lines += block("🤖 Par IA :", agent_stats(),
                   lambda r: f" · poids {r['weight']*100:.0f}%")
    lines += block("🧭 Par secteur :", winrate_by(signals, "sector", min_n=2))
    lines += block("📦 Par taille :", winrate_by(signals, "cap_bucket", min_n=2))
    lines += block("🎯 Par conviction :", winrate_by_conviction(signals))

    d = divergence_stats(signals)
    if d["avec"]["n"] or d["sans"]["n"]:
        lines.append(f"\n⚠️ Divergences : {d['avec']['win_rate']*100:.0f}% ({d['avec']['n']}) "
                     f"vs sans {d['sans']['win_rate']*100:.0f}% ({d['sans']['n']})")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# DASHBOARD HTML (autonome)
# ─────────────────────────────────────────────────────────────

def _bar_rows(rows: list[dict]) -> str:
    out = []
    for r in rows:
        wr = r["win_rate"] * 100
        color = "#16a34a" if wr >= 55 else "#eab308" if wr >= 45 else "#dc2626"
        out.append(
            f'<div class="row"><span class="lbl">{html.escape(str(r["key"]))}</span>'
            f'<span class="bar"><span style="width:{wr:.0f}%;background:{color}"></span></span>'
            f'<span class="val">{wr:.0f}% ({r["n"]})</span></div>')
    return "\n".join(out) or '<p class="muted">Pas encore de données.</p>'


def build_html(signals: list[dict] | None = None) -> str:
    if signals is None:
        signals = fetch_signals()
    g = global_stats(signals)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = [
        ("Signaux clos", f"{g['n']}"),
        ("En cours", f"{g['open']}"),
        ("Taux de réussite", f"{g['win_rate']*100:.0f}%"),
        ("Espérance/trade", _pct(g['expectancy'])),
        ("Gain moyen", _pct(g['avg_gain'])),
        ("Perte moyenne", _pct(g['avg_loss'])),
        ("P&L paper", f"{g['pnl_eur']:+,.0f}€"),
        ("Meilleur / pire", f"{_pct(g['best'])} / {_pct(g['worst'])}"),
    ]
    cards_html = "\n".join(
        f'<div class="card"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}</div></div>' for k, v in cards)

    recent = signals[:25]
    rows_html = []
    for s in recent:
        r7 = s.get("result_7d")
        if r7 is None:
            res = '<span class="muted">en cours</span>'
        else:
            r7 = float(r7)
            c = "#16a34a" if r7 > 0 else "#dc2626"
            res = f'<span style="color:{c}">{r7*100:+.1f}%</span>'
        rows_html.append(
            f"<tr><td>{html.escape((s.get('created_at') or '')[:10])}</td>"
            f"<td>{html.escape(str(s.get('ticker') or ''))}</td>"
            f"<td>{html.escape(str(s.get('sector') or '—'))}</td>"
            f"<td>{s.get('conviction') if s.get('conviction') is not None else '—'}</td>"
            f"<td>{res}</td></tr>")

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent boursier — Tableau de bord</title>
<style>
  :root {{ font-family: system-ui, -apple-system, sans-serif; }}
  body {{ margin:0; background:#0f172a; color:#e2e8f0; padding:16px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .muted {{ color:#94a3b8; font-size:13px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin:16px 0; }}
  .card {{ background:#1e293b; border-radius:12px; padding:12px; }}
  .card .k {{ font-size:12px; color:#94a3b8; }}
  .card .v {{ font-size:22px; font-weight:700; margin-top:4px; }}
  h2 {{ font-size:15px; margin:20px 0 8px; color:#cbd5e1; }}
  .row {{ display:flex; align-items:center; gap:8px; margin:5px 0; font-size:13px; }}
  .row .lbl {{ width:34%; }}
  .row .bar {{ flex:1; background:#334155; border-radius:6px; height:14px; overflow:hidden; }}
  .row .bar span {{ display:block; height:100%; }}
  .row .val {{ width:78px; text-align:right; color:#cbd5e1; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:6px 4px; border-bottom:1px solid #1e293b; }}
  th {{ color:#94a3b8; font-weight:600; }}
</style></head><body>
<h1>📊 Agent boursier — Tableau de bord</h1>
<div class="muted">Généré le {now} · taux de réussite à J+7</div>
<div class="cards">{cards_html}</div>
<h2>🤖 Réussite par IA</h2>{_bar_rows(agent_stats())}
<h2>🧭 Réussite par secteur</h2>{_bar_rows(winrate_by(signals, "sector", min_n=2))}
<h2>📦 Réussite par taille de capi</h2>{_bar_rows(winrate_by(signals, "cap_bucket", min_n=2))}
<h2>🎯 Réussite par conviction</h2>{_bar_rows(winrate_by_conviction(signals))}
<h2>🕒 Derniers signaux</h2>
<table><tr><th>Date</th><th>Ticker</th><th>Secteur</th><th>Conv.</th><th>J+7</th></tr>
{''.join(rows_html) or '<tr><td colspan=5 class="muted">Aucun signal.</td></tr>'}
</table>
</body></html>"""


def write_html(path: str = "dashboard.html", signals: list[dict] | None = None) -> str:
    content = build_html(signals)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Dashboard écrit : %s", path)
    return path


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    out = sys.argv[1] if len(sys.argv) > 1 else "dashboard.html"
    sigs = fetch_signals()
    print(build_text_summary(sigs))
    write_html(out, sigs)
    print(f"\nDashboard HTML écrit : {out}")
