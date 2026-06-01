"""
buzz.py — Radar de buzz (essai 7 jours).

2 récaps/jour via Grok (recherche en direct sur X + actus) : les 3-4 actions
les plus optimistes pour la séance à venir (EU avant 9h, US avant 15h30).
Chaque pick est enregistré. Au bout de 7 jours : récap + arrêt + coût estimé +
simulation intraday (achat ~10 min après ouverture, vente ~10 min avant clôture).

⚠️ Info sentiment, PAS une reco d'achat. Module séparé du système de trading.
"""

import logging
import datetime as dt

import config
from agents import base as agent_base
from alerts import telegram_bot
from memory import state

logger = logging.getLogger("buzz")

STATE_KEY = "buzz_state"
LOG_KEY = "buzz_log"

SYSTEM = "Tu es un analyste sentiment de marché. Réponds uniquement en JSON valide."

PROMPT = """En cherchant sur X (Twitter), dans les actualités financières et chez les analystes
au cours des dernières 24h, donne les 3 à 4 actions {scope} qui suscitent le PLUS
d'optimisme pour la séance de bourse d'aujourd'hui.

Critères : buzz positif en hausse, catalyseur récent (résultats, contrat, annonce),
avis d'analystes/suiveurs favorables. Uniquement des actions LIQUIDES et tradables.

IMPORTANT : donne le ticker au format Yahoo Finance (ex : "AIR.PA" pour Airbus,
"NVDA" pour Nvidia, "STMPA.PA" pour STMicro).

Réponds UNIQUEMENT avec ce JSON :
{{
  "picks": [
    {{"ticker": "...", "nom": "...", "raison": "[1 phrase courte]", "sentiment": [0-10]}}
  ]
}}"""

SCOPE = {
    "EU": "EUROPÉENNES (cotées à Paris / Euronext)",
    "US": "AMÉRICAINES (cotées au Nasdaq / NYSE)",
}


# ─────────────────────────────────────────────────────────────
# ÉTAT DE L'ESSAI
# ─────────────────────────────────────────────────────────────

def _get_state() -> dict:
    return state.get_state(STATE_KEY, default={}) or {}


def _set_state(s: dict):
    state.set_state(STATE_KEY, s)


def _start_if_needed(today: dt.date):
    s = _get_state()
    if not s.get("start_date"):
        s = {"active": True, "start_date": today.isoformat(), "recap_sent": False}
        _set_state(s)
        logger.info("Radar buzz démarré le %s", s["start_date"])
    return _get_state()


def is_expired(today: dt.date) -> bool:
    s = _get_state()
    if not s.get("start_date"):
        return False
    start = dt.date.fromisoformat(s["start_date"])
    return (today - start).days >= config.BUZZ["trial_days"]


# ─────────────────────────────────────────────────────────────
# RÉCAP QUOTIDIEN (un appel Grok)
# ─────────────────────────────────────────────────────────────

def run_digest(session: str, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    _start_if_needed(today)

    user = PROMPT.format(scope=SCOPE.get(session, "cotées"))
    extra = {"search_parameters": {
        "mode": "auto",
        "sources": [{"type": "x"}, {"type": "news"}, {"type": "web"}],
        "max_search_results": config.BUZZ["max_search_results"],
    }}
    try:
        text = agent_base.call_openai_compatible("grok", SYSTEM, user, extra)
    except Exception as e:  # noqa: BLE001
        logger.warning("Grok buzz KO (%s) — appel simple", str(e)[:80])
        text = agent_base.call_openai_compatible("grok", SYSTEM, user)
    parsed = agent_base.parse_json_response(text)
    picks = parsed.get("picks", [])[: config.BUZZ["max_picks"]]

    # Journalisation
    log = state.get_state(LOG_KEY, default=[]) or []
    for p in picks:
        log.append({"date": today.isoformat(), "session": session,
                    "ticker": p.get("ticker", ""), "nom": p.get("nom", ""),
                    "raison": p.get("raison", ""), "sentiment": p.get("sentiment")})
    state.set_state(LOG_KEY, log)

    _send_digest_message(session, picks, today)
    return {"session": session, "picks": picks}


def _send_digest_message(session: str, picks: list, today: dt.date):
    titre = "🇪🇺 OUVERTURE EUROPE" if session == "EU" else "🇺🇸 OUVERTURE US"
    msg = f"📡 RADAR BUZZ — {titre} ({today.isoformat()})\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    if not picks:
        msg += "Aucune valeur ne se détache aujourd'hui."
    else:
        for p in picks:
            s = p.get("sentiment")
            s_txt = f" ({s}/10)" if s is not None else ""
            msg += f"\n🔥 {p.get('ticker','?')} — {p.get('nom','')}{s_txt}\n   {p.get('raison','')}\n"
    msg += "\nℹ️ Info sentiment (X/analystes) — PAS une reco d'achat. Essai 7 jours."
    telegram_bot.send_message(msg)


# ─────────────────────────────────────────────────────────────
# SIMULATION INTRADAY (achat ~+10min ouverture / vente ~-10min clôture)
# ─────────────────────────────────────────────────────────────

def _intraday_return(ticker: str, day_iso: str) -> float | None:
    """Rendement entre ~10 min après l'ouverture et ~10 min avant la clôture."""
    try:
        import yfinance as yf
        import pandas as pd
        df = yf.download(ticker, period="1mo", interval="5m",
                         progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        day = dt.date.fromisoformat(day_iso)
        bars = df[df.index.date == day]
        if len(bars) < 4:
            return None
        buy_time = bars.index[0] + pd.Timedelta(minutes=10)
        sell_time = bars.index[-1] - pd.Timedelta(minutes=10)
        buy_rows = bars[bars.index >= buy_time]
        sell_rows = bars[bars.index <= sell_time]
        if buy_rows.empty or sell_rows.empty:
            return None
        buy = float(buy_rows["Close"].iloc[0])
        sell = float(sell_rows["Close"].iloc[-1])
        if buy <= 0:
            return None
        return (sell - buy) / buy
    except Exception as e:  # noqa: BLE001
        logger.warning("intraday %s %s KO : %s", ticker, day_iso, e)
        return None


def send_recap(today: dt.date | None = None):
    today = today or dt.date.today()
    log = state.get_state(LOG_KEY, default=[]) or []
    n_digests = len({(e["date"], e["session"]) for e in log})
    est_cost = n_digests * config.BUZZ["est_cost_per_digest_usd"]
    stake = 1000

    results = []
    for e in log:
        r = _intraday_return(e["ticker"], e["date"])
        if r is not None:
            results.append((e, r))

    msg = "📊 BILAN — RADAR BUZZ (essai 7 jours terminé)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"Picks envoyés : {len(log)} sur {n_digests} récaps\n"
    msg += f"Coût API estimé : ~{est_cost:.2f} $ (à vérifier sur ta facture xAI)\n\n"

    if results:
        import statistics
        rets = [r for _, r in results]
        pnl_total = sum(r * stake for r in rets)
        wins = sum(1 for r in rets if r > 0)
        msg += "💡 SIMULATION (1000€/action, achat ~10min après ouverture, "
        msg += "vente ~10min avant clôture, même journée) :\n"
        msg += f"  Trades simulés : {len(rets)}\n"
        msg += f"  Réussite : {wins/len(rets)*100:.0f}%\n"
        msg += f"  Gain moyen : {statistics.mean(rets)*100:+.2f}%/trade\n"
        msg += f"  RÉSULTAT TOTAL : {pnl_total:+,.0f} €\n\n"
        # détail top/flop
        results.sort(key=lambda x: x[1], reverse=True)
        msg += "  Meilleurs :\n"
        for e, r in results[:3]:
            msg += f"    {e['ticker']} ({e['date']}) {r*100:+.1f}%\n"
        msg += "  Pires :\n"
        for e, r in results[-3:]:
            msg += f"    {e['ticker']} ({e['date']}) {r*100:+.1f}%\n"
        net = pnl_total  # pas de frais ici (intraday, à titre indicatif)
        verdict = "intéressant 👍" if net > est_cost * 0.9 else "pas concluant"
        msg += f"\nVerdict : gain simulé {net:+,.0f} € vs coût ~{est_cost:.0f} $ → {verdict}."
    else:
        msg += "⚠️ Données intraday indisponibles pour la simulation."

    msg += "\n\n🛑 Radar stoppé. Tape /buzz_on pour le relancer, ou décide-toi avec ces chiffres."
    telegram_bot.send_message(msg)

    s = _get_state()
    s["active"] = False
    s["recap_sent"] = True
    _set_state(s)
    logger.info("Récap buzz envoyé, radar stoppé.")


# ─────────────────────────────────────────────────────────────
# COMMANDES MANUELLES
# ─────────────────────────────────────────────────────────────

def restart():
    state.set_state(STATE_KEY, {"active": True, "start_date": dt.date.today().isoformat(),
                                "recap_sent": False})
    state.set_state(LOG_KEY, [])
    logger.info("Radar buzz relancé.")
