"""
holdings.py — Suivi en TEMPS RÉEL du portefeuille de Rémy (CTO + PEA).

À partir du relevé de l'appli (valeur de chaque position + plus/moins-value
depuis l'achat), on déduit pour chaque ligne :
  - le prix de revient en € (ce que Rémy a réellement investi),
  - le cours de référence du jour du relevé (cours_natif au moment du relevé).

Ensuite, à chaque appel, on récupère le cours LIVE (Yahoo) et on recalcule :
  - la valeur actuelle de la position,
  - la variation du JOUR,
  - la plus/moins-value DEPUIS L'ACHAT.

On raisonne en RATIO de cours (cours_live / cours_référence). Pour les lignes en
$ la valeur € suit donc le cours de l'action ; la dérive du taux EUR/USD depuis
le relevé est négligée (ordre de grandeur d'un coup d'œil, pas d'une compta).

Les lignes sans buy_price (ex. ETF Gold) n'ont pas de cours de référence
calculable : on en fixe un au 1er passage (cours du moment, mémorisé dans
agent_state) pour pouvoir suivre la valeur ensuite.
"""

import logging

import config
import data_fetcher

logger = logging.getLogger("holdings")

REF_STATE_KEY = "holdings_ref"   # cours de référence mémorisés (ETF sans buy_price)


# ─────────────────────────────────────────────────────────────
# DÉRIVATION (pur, testable) : relevé appli -> prix de revient + cours de réf.
# ─────────────────────────────────────────────────────────────

def derive(line: dict) -> dict:
    """
    Complète une ligne de config.HOLDINGS avec :
      - cost_basis_eur : prix de revient en € (euros investis),
      - pl_pct_snap    : P/L depuis l'achat au moment du relevé,
      - ref_price      : cours natif au moment du relevé (None si incalculable).
    """
    value = float(line["value_eur"])
    if "pl_pct" in line and line["pl_pct"] is not None:
        pl_pct = float(line["pl_pct"])
        cost = value / (1 + pl_pct) if (1 + pl_pct) else value
    elif "pl_eur" in line and line["pl_eur"] is not None:
        pl_eur = float(line["pl_eur"])
        cost = value - pl_eur
        pl_pct = (pl_eur / cost) if cost else 0.0
    else:
        cost, pl_pct = value, 0.0

    buy = line.get("buy_price")
    ref_price = (float(buy) * (1 + pl_pct)) if buy else None

    return {**line, "cost_basis_eur": cost, "pl_pct_snap": pl_pct, "ref_price": ref_price}


# ─────────────────────────────────────────────────────────────
# COURS LIVE
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


def _ref_cache() -> dict:
    try:
        from memory import state
        return state.get_state(REF_STATE_KEY, default={}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _save_ref_cache(cache: dict) -> None:
    try:
        from memory import state
        state.set_state(REF_STATE_KEY, cache)
    except Exception as e:  # noqa: BLE001
        logger.warning("Sauvegarde cours de référence échouée : %s", e)


# ─────────────────────────────────────────────────────────────
# CALCUL D'UNE LIGNE LIVE
# ─────────────────────────────────────────────────────────────

def evaluate_line(line: dict, ref_cache: dict) -> dict:
    """Calcule la valeur live d'une ligne. Met à jour ref_cache si besoin."""
    d = derive(line)
    tk = d["ticker"]
    last, prev = _last_two_closes(tk)

    ref = d["ref_price"]
    if ref is None:
        # Pas de cours de référence calculable (ETF sans buy_price) :
        # on mémorise le 1er cours observé comme référence.
        ref = ref_cache.get(tk)
        if ref is None and last is not None:
            ref = last
            ref_cache[tk] = ref

    out = {**d, "ok": False, "price": last}
    if last is None or ref in (None, 0):
        out["reason"] = "cours indisponible"
        # On retombe sur la valeur du relevé pour ne pas fausser le total.
        out["value_now"] = d["value_eur"]
        out["pl_eur"] = d["value_eur"] - d["cost_basis_eur"]
        out["pl_pct"] = d["pl_pct_snap"]
        out["day_eur"] = None
        out["day_pct"] = None
        return out

    ratio = last / ref
    value_now = d["value_eur"] * ratio
    out["ok"] = True
    out["value_now"] = value_now
    out["pl_eur"] = value_now - d["cost_basis_eur"]
    out["pl_pct"] = (value_now / d["cost_basis_eur"] - 1) if d["cost_basis_eur"] else 0.0
    if prev:
        out["day_pct"] = last / prev - 1
        out["day_eur"] = d["value_eur"] * (last - prev) / ref
    else:
        out["day_pct"] = None
        out["day_eur"] = None
    return out


def evaluate_all(lines: list[dict] | None = None) -> list[dict]:
    """Évalue toutes les positions (config.HOLDINGS par défaut)."""
    lines = lines if lines is not None else config.HOLDINGS
    cache = _ref_cache()
    cache_before = dict(cache)
    results = [evaluate_line(l, cache) for l in lines]
    if cache != cache_before:
        _save_ref_cache(cache)
    return results


# ─────────────────────────────────────────────────────────────
# AGRÉGATS
# ─────────────────────────────────────────────────────────────

def summarize(results: list[dict]) -> dict:
    """Totaux par compte (valeur, P/L, variation jour) + espèces + total global."""
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
    if x is None:
        return ""
    return f"{x*100:+.1f}%"


def _line_txt(r: dict) -> str:
    val = _eur(r["value_now"])
    day = ""
    if r.get("day_pct") is not None:
        arrow = "🟢" if r["day_pct"] >= 0 else "🔴"
        day = f" {arrow} {_pct(r['day_pct'])} auj."
    pl = f"PV {_pct(r['pl_pct'])}"
    flag = "" if r.get("ok") else " ⚠️"
    return f"  • {r['name']} : {val} ({pl}){day}{flag}"


def format_portfolio(results: list[dict] | None = None) -> str:
    """Message Telegram : portefeuille temps réel CTO + PEA."""
    results = results if results is not None else evaluate_all()
    s = summarize(results)
    order = ["CTO", "PEA"]
    accounts = s["accounts"]

    lines = ["💼 PORTEFEUILLE — temps réel", ""]
    for acc in order + [a for a in accounts if a not in order]:
        a = accounts.get(acc)
        if not a:
            continue
        day = f" · jour {_pct_eur(a['day'])}" if a["day"] else ""
        lines.append(f"━ {acc} : {_eur(a['total'])}  (PV {_pct(a['pl_pct'])}{day})")
        for r in sorted(a["lines"], key=lambda x: -x["value_now"]):
            lines.append(_line_txt(r))
        if a["cash"]:
            lines.append(f"  • Liquidités : {_eur(a['cash'])}")
        lines.append("")

    g = s["grand"]
    day = f" · jour {_pct_eur(g['day'])}" if g["day"] else ""
    lines.append(f"💰 TOTAL : {_eur(g['total'])}  (PV {g['pl_eur']:+,.0f} €".replace(",", " ")
                 + f" / {_pct(g['pl_pct'])}{day})")
    errs = [r["name"] for r in results if not r.get("ok")]
    if errs:
        lines.append(f"\n⚠️ Cours indisponible (valeur du relevé) : {', '.join(errs)}")
    lines.append("\n(Lignes en $ : valeur € suivie via le cours, taux de change approché.)")
    return "\n".join(lines)


def _pct_eur(x: float) -> str:
    return (f"{x:+,.0f} €").replace(",", " ")


def run(send: bool = True) -> str:
    """Calcule et (optionnellement) envoie le portefeuille sur Telegram."""
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
