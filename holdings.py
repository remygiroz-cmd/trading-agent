"""
holdings.py — Suivi en TEMPS RÉEL du portefeuille de Rémy (CTO + PEA).

Modèle : un REGISTRE de positions en PARTS (nb d'actions) + prix de revient en €.
  - Au départ, le registre est SEEDÉ depuis le relevé de l'appli (config.HOLDINGS) :
    valeur de chaque position + plus/moins-value depuis l'achat -> on en déduit le
    prix de revient, le cours de référence et le nombre de parts.
  - Ensuite, chaque ACHAT/VENTE (capture Trade Republic envoyée sur Telegram, cf.
    transactions.py) met à jour les parts et le prix de revient.

Valeur live = parts × cours_natif (Yahoo) × fx (€ par unité de cours).
  - Ligne en € (.PA …)  : fx = 1.
  - Ligne en $          : fx figé au seed (≈ EUR/USD du moment). La dérive du taux
    de change est négligée (ordre de grandeur d'un coup d'œil).

Le registre et le journal des transactions vivent dans agent_state (Supabase),
car le système de fichiers de GitHub Actions est éphémère.
"""

import logging

import config
import data_fetcher

logger = logging.getLogger("holdings")

LEDGER_KEY = "holdings_ledger"   # {account|ticker: position}
JOURNAL_KEY = "holdings_journal"  # liste des transactions enregistrées


# ─────────────────────────────────────────────────────────────
# DÉRIVATION (pur, testable) : relevé appli -> prix de revient + cours de réf.
# ─────────────────────────────────────────────────────────────

def derive(line: dict) -> dict:
    """
    Déduit d'une ligne de relevé :
      - cost_basis_eur : prix de revient en € (euros investis),
      - pl_pct_snap    : P/L depuis l'achat au moment du relevé,
      - ref_price      : cours natif au moment du relevé (None si incalculable).
    """
    value = float(line["value_eur"])
    if line.get("pl_pct") is not None:
        pl_pct = float(line["pl_pct"])
        cost = value / (1 + pl_pct) if (1 + pl_pct) else value
    elif line.get("pl_eur") is not None:
        pl_eur = float(line["pl_eur"])
        cost = value - pl_eur
        pl_pct = (pl_eur / cost) if cost else 0.0
    else:
        cost, pl_pct = value, 0.0

    buy = line.get("buy_price")
    ref_price = (float(buy) * (1 + pl_pct)) if buy else None
    return {**line, "cost_basis_eur": cost, "pl_pct_snap": pl_pct, "ref_price": ref_price}


def is_eur(cur: str | None, ticker: str = "") -> bool:
    """Une ligne est-elle libellée en € (sinon en $) ?"""
    if cur:
        return cur.strip() in ("€", "EUR", "eur")
    eu = (".PA", ".MI", ".DE", ".AS", ".BR", ".MC", ".LS", ".HE", ".ST")
    return any((ticker or "").upper().endswith(s) for s in eu)


# ─────────────────────────────────────────────────────────────
# COURS LIVE + CHANGE
# ─────────────────────────────────────────────────────────────

def _last_two_closes(ticker: str) -> tuple[float | None, float | None]:
    """Dernier cours et cours de la veille (pour la variation du jour)."""
    try:
        df = data_fetcher.fetch_ticker(ticker, period="5d", interval="1d")
        if df is None or df.empty:
            return None, None
        closes = df["close"].dropna()
        last = float(closes.iloc[-1]) if len(closes) >= 1 else None
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
        return last, prev
    except Exception as e:  # noqa: BLE001
        logger.warning("Cours %s indisponible : %s", ticker, e)
        return None, None


def eur_per_usd() -> float | None:
    """€ pour 1 $ (= 1 / cours EUR/USD). None si indisponible."""
    try:
        rate = data_fetcher.fetch_current_price("EURUSD=X")  # USD pour 1 €
        if rate and rate > 0:
            return 1.0 / float(rate)
    except Exception as e:  # noqa: BLE001
        logger.warning("Taux EUR/USD indisponible : %s", e)
    return None


# ─────────────────────────────────────────────────────────────
# REGISTRE (parts + prix de revient) — persistant
# ─────────────────────────────────────────────────────────────

def _key(account: str, ticker: str) -> str:
    return f"{account.upper()}|{ticker.upper()}"


def load_ledger() -> dict:
    try:
        from memory import state
        return state.get_state(LEDGER_KEY, default={}) or {}
    except Exception:  # noqa: BLE001
        return {}


def save_ledger(ledger: dict) -> None:
    try:
        from memory import state
        state.set_state(LEDGER_KEY, ledger)
    except Exception as e:  # noqa: BLE001
        logger.warning("Sauvegarde registre échouée : %s", e)


def seed_ledger(lines: list[dict] | None = None, fx: float | None = None) -> dict:
    """
    Construit le registre initial (parts + prix de revient) depuis le relevé.
    fx (€ par $) est utilisé pour les lignes en $ ; à défaut on le récupère.
    """
    lines = lines if lines is not None else config.HOLDINGS
    need_fx = any(not is_eur(l.get("cur"), l["ticker"]) for l in lines)
    if need_fx and fx is None:
        fx = eur_per_usd()

    ledger: dict = {}
    for l in lines:
        d = derive(l)
        eur = is_eur(l.get("cur"), l["ticker"])
        line_fx = 1.0 if eur else (fx or 1.0)

        ref = d["ref_price"]
        if ref is None:                      # ETF sans buy_price : référence = cours du moment
            ref, _ = _last_two_closes(l["ticker"])
        if not ref:
            logger.warning("Seed %s : pas de cours de référence, ligne ignorée", l["ticker"])
            continue

        shares = d["value_eur"] / (ref * line_fx)
        ledger[_key(l["account"], l["ticker"])] = {
            "account": l["account"], "name": l["name"], "ticker": l["ticker"],
            "cur": l.get("cur", "€" if eur else "$"),
            "shares": shares, "cost_eur": d["cost_basis_eur"], "fx": line_fx,
        }
    return ledger


def ensure_ledger() -> dict:
    """Charge le registre, le seed au 1er appel s'il est vide."""
    ledger = load_ledger()
    if not ledger:
        ledger = seed_ledger()
        if ledger:
            save_ledger(ledger)
    return ledger


# ─────────────────────────────────────────────────────────────
# APPLIQUER UNE TRANSACTION (achat / vente)
# ─────────────────────────────────────────────────────────────

def apply_transaction(ledger: dict, tx: dict) -> dict:
    """
    Met à jour le registre avec une transaction. tx attendu :
      {account, name, ticker, cur, action: 'buy'|'sell', shares, price_eur,
       total_eur, fees_eur}
    Retourne {ok, msg, position}.
    """
    account = (tx.get("account") or "").upper()
    ticker = (tx.get("ticker") or "").upper()
    action = (tx.get("action") or "buy").lower()
    shares = float(tx.get("shares") or 0)
    total = float(tx.get("total_eur") or 0)
    if not ticker or shares <= 0:
        return {"ok": False, "msg": "transaction incomplète (ticker / quantité)."}

    k = _key(account, ticker)
    pos = ledger.get(k)
    eur = is_eur(tx.get("cur"), ticker)

    if action in ("sell", "vente"):
        if not pos or pos["shares"] <= 0:
            return {"ok": False, "msg": f"vente {ticker} ignorée : aucune position connue."}
        sold = min(shares, pos["shares"])
        frac = sold / pos["shares"] if pos["shares"] else 0
        pos["cost_eur"] *= (1 - frac)
        pos["shares"] -= sold
        if pos["shares"] <= 1e-6:
            ledger.pop(k, None)
        else:
            ledger[k] = pos
        return {"ok": True, "msg": f"Vente enregistrée : {sold:g} {ticker}.", "position": pos}

    # ACHAT
    if pos:
        pos["shares"] += shares
        pos["cost_eur"] += (total or shares * float(tx.get("price_eur") or 0))
        ledger[k] = pos
    else:
        # nouvelle position : on fige le fx (€/cours) à partir du cours du moment
        line_fx = 1.0
        if not eur:
            nat, _ = _last_two_closes(ticker)
            price_eur = float(tx.get("price_eur") or 0)
            line_fx = (price_eur / nat) if (nat and price_eur) else (eur_per_usd() or 1.0)
        pos = {
            "account": account, "name": tx.get("name") or ticker, "ticker": ticker,
            "cur": tx.get("cur") or ("€" if eur else "$"),
            "shares": shares, "cost_eur": total or shares * float(tx.get("price_eur") or 0),
            "fx": line_fx,
        }
        ledger[k] = pos
    return {"ok": True, "msg": f"Achat enregistré : {shares:g} {ticker}.", "position": pos}


# ─────────────────────────────────────────────────────────────
# JOURNAL
# ─────────────────────────────────────────────────────────────

def load_journal() -> list:
    try:
        from memory import state
        return state.get_state(JOURNAL_KEY, default=[]) or []
    except Exception:  # noqa: BLE001
        return []


def save_journal(journal: list) -> None:
    try:
        from memory import state
        state.set_state(JOURNAL_KEY, journal)
    except Exception as e:  # noqa: BLE001
        logger.warning("Sauvegarde journal échouée : %s", e)


# ─────────────────────────────────────────────────────────────
# ÉVALUATION LIVE D'UNE POSITION DU REGISTRE
# ─────────────────────────────────────────────────────────────

def evaluate_position(pos: dict) -> dict:
    """Valeur live d'une position du registre (parts × cours × fx)."""
    last, prev = _last_two_closes(pos["ticker"])
    fx = float(pos.get("fx", 1.0))
    shares = float(pos["shares"])
    cost = float(pos["cost_eur"])
    out = {**pos, "ok": False, "price": last, "cost_basis_eur": cost}

    if last is None:
        out["value_now"] = cost           # repli neutre : valeur = prix de revient
        out["pl_eur"] = 0.0
        out["pl_pct"] = 0.0
        out["day_eur"] = out["day_pct"] = None
        out["reason"] = "cours indisponible"
        return out

    value = shares * last * fx
    out["ok"] = True
    out["value_now"] = value
    out["pl_eur"] = value - cost
    out["pl_pct"] = (value / cost - 1) if cost else 0.0
    if prev:
        out["day_pct"] = last / prev - 1
        out["day_eur"] = shares * (last - prev) * fx
    else:
        out["day_pct"] = out["day_eur"] = None
    return out


def evaluate_all(ledger: dict | None = None) -> list[dict]:
    ledger = ledger if ledger is not None else ensure_ledger()
    return [evaluate_position(p) for p in ledger.values()]


# ─────────────────────────────────────────────────────────────
# AGRÉGATS
# ─────────────────────────────────────────────────────────────

def summarize(results: list[dict]) -> dict:
    accounts: dict[str, dict] = {}
    for r in results:
        acc = accounts.setdefault(r["account"], {
            "value": 0.0, "cost": 0.0, "day": 0.0, "lines": []})
        acc["value"] += r["value_now"]
        acc["cost"] += r["cost_basis_eur"]
        acc["day"] += r.get("day_eur") or 0.0
        acc["lines"].append(r)

    cash = getattr(config, "CASH", {}) or {}
    grand = {"value": 0.0, "cost": 0.0, "day": 0.0, "cash": 0.0}
    for acc, a in accounts.items():
        a["cash"] = float(cash.get(acc, 0.0))
        a["total"] = a["value"] + a["cash"]
        a["pl_eur"] = a["value"] - a["cost"]
        a["pl_pct"] = (a["value"] / a["cost"] - 1) if a["cost"] else 0.0
        grand["value"] += a["value"]
        grand["cost"] += a["cost"]
        grand["day"] += a["day"]
        grand["cash"] += a["cash"]
    grand["total"] = grand["value"] + grand["cash"]
    grand["pl_eur"] = grand["value"] - grand["cost"]
    grand["pl_pct"] = (grand["value"] / grand["cost"] - 1) if grand["cost"] else 0.0
    return {"accounts": accounts, "grand": grand}


# ─────────────────────────────────────────────────────────────
# FORMAT TELEGRAM
# ─────────────────────────────────────────────────────────────

def _eur(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " €"


def _pct(x: float | None) -> str:
    return "" if x is None else f"{x*100:+.1f}%"


def _signed_eur(x: float) -> str:
    return (f"{x:+,.0f} €").replace(",", " ")


def _line_txt(r: dict) -> str:
    day = ""
    if r.get("day_pct") is not None:
        arrow = "🟢" if r["day_pct"] >= 0 else "🔴"
        day = f" {arrow} {_pct(r['day_pct'])} auj."
    flag = "" if r.get("ok") else " ⚠️"
    return f"  • {r['name']} : {_eur(r['value_now'])} (PV {_pct(r['pl_pct'])}){day}{flag}"


def format_portfolio(results: list[dict] | None = None) -> str:
    results = results if results is not None else evaluate_all()
    s = summarize(results)
    accounts = s["accounts"]
    order = ["CTO", "PEA"]

    lines = ["💼 PORTEFEUILLE — temps réel", ""]
    for acc in order + [a for a in accounts if a not in order]:
        a = accounts.get(acc)
        if not a:
            continue
        day = f" · jour {_signed_eur(a['day'])}" if a["day"] else ""
        lines.append(f"━ {acc} : {_eur(a['total'])}  (PV {_pct(a['pl_pct'])}{day})")
        for r in sorted(a["lines"], key=lambda x: -x["value_now"]):
            lines.append(_line_txt(r))
        if a["cash"]:
            lines.append(f"  • Liquidités : {_eur(a['cash'])}")
        lines.append("")

    g = s["grand"]
    day = f" · jour {_signed_eur(g['day'])}" if g["day"] else ""
    lines.append(f"💰 TOTAL : {_eur(g['total'])}  (PV {_signed_eur(g['pl_eur'])} / {_pct(g['pl_pct'])}{day})")
    errs = [r["name"] for r in results if not r.get("ok")]
    if errs:
        lines.append(f"\n⚠️ Cours indisponible : {', '.join(errs)}")
    lines.append("\n(Lignes en $ : valeur € via le cours, taux de change figé au seed.)")
    return "\n".join(lines)


def run(send: bool = True) -> str:
    msg = format_portfolio()
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi portefeuille échoué : %s", e)
    return msg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run(send=False))
