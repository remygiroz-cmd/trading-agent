"""
transactions.py — Enregistrer un achat/vente depuis une capture Trade Republic.

Rémy envoie sur Telegram une capture d'écran d'une transaction (« Vous avez
investi 101,02 € … IonQ … 2,19756 × 45,515 € … Frais 1,00 € »). Le bot :
  1. lit l'image (vision Claude) et en extrait les champs au format JSON ;
  2. enregistre la transaction dans le journal (holdings.JOURNAL_KEY) ;
  3. met à jour le registre de parts (holdings) — sauf si la transaction est
     antérieure au relevé de référence (déjà comptée) ;
  4. renvoie une confirmation lisible que Rémy peut vérifier.

La même fonction sert de PORTE D'ENTRÉE pour toutes les captures : si l'image
n'est pas une transaction (ex. capture de tweet), on bascule sur l'analyse de
tweet existante (tweet.analyze_image).
"""

import json
import logging
import datetime as dt

import requests

import config
import holdings

logger = logging.getLogger("transactions")


# ─────────────────────────────────────────────────────────────
# LECTURE DE L'IMAGE (vision)
# ─────────────────────────────────────────────────────────────

_SYSTEM = (
    "Tu lis des captures d'écran d'opérations de bourse (appli Trade Republic, "
    "en français). Tu réponds UNIQUEMENT par un objet JSON, sans texte autour."
)

_USER = (
    "Analyse cette capture. Réponds en JSON strict :\n"
    "{\n"
    '  "kind": "transaction" | "tweet" | "autre",\n'
    '  "action": "buy" | "sell",          // achat (\"investi\"/\"Acheter\") ou vente\n'
    '  "account": "CTO" | "PEA",          // \"Compte-Titres\"->CTO, \"Plan/PEA\"->PEA\n'
    '  "asset": "nom de l\'actif",         // ex. IonQ, Tesla, Hermès\n'
    '  "shares": nombre,                   // quantité (ex. 2.19756)\n'
    '  "price_eur": nombre,                // cours unitaire en € (ex. 45.515)\n'
    '  "fees_eur": nombre,                 // frais en € (0 si absent)\n'
    '  "total_eur": nombre,                // total en € (montant investi/reçu)\n'
    '  "date": "AAAA-MM-JJ"                // date de l\'opération si visible, sinon null\n'
    "}\n"
    "Si ce n'est PAS une opération de bourse, renvoie {\"kind\":\"tweet\"} pour une "
    "capture de tweet, sinon {\"kind\":\"autre\"}. Utilise le POINT comme séparateur "
    "décimal. N'invente aucune valeur absente."
)


def _download(image_url: str) -> tuple[str, str] | None:
    import base64
    try:
        r = requests.get(image_url, timeout=30, headers={"User-Agent": "trading-agent"})
        r.raise_for_status()
        b64 = base64.b64encode(r.content).decode()
        media = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if media not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            media = "image/jpeg"
        return b64, media
    except Exception as e:  # noqa: BLE001
        logger.warning("Téléchargement image échoué : %s", e)
        return None


def extract(image_url: str) -> dict | None:
    """Lit l'image et renvoie les champs (dict) ou None si lecture impossible."""
    dl = _download(image_url)
    if not dl:
        return None
    b64, media = dl
    from agents import base as agent_base
    try:
        raw = agent_base.call_claude_vision(_SYSTEM, _USER, b64, media)
    except Exception as e:  # noqa: BLE001
        logger.warning("Vision transaction échouée : %s", e)
        return None
    try:
        return agent_base.parse_json_response(raw)
    except Exception:  # noqa: BLE001
        logger.warning("JSON transaction illisible : %s", str(raw)[:160])
        return None


# ─────────────────────────────────────────────────────────────
# NORMALISATION (nom -> ticker, compte, devise)
# ─────────────────────────────────────────────────────────────

def _resolve_ticker(asset: str) -> tuple[str | None, str | None, str | None]:
    """(ticker, name, cur) à partir du nom. Cherche d'abord dans config.HOLDINGS."""
    a = (asset or "").strip().lower()
    if not a:
        return None, None, None
    for l in config.HOLDINGS:
        if a in l["name"].lower() or l["name"].lower() in a or a == l["ticker"].lower():
            return l["ticker"], l["name"], l.get("cur")
    # Sinon, résolution Yahoo via le monitor
    try:
        import monitor
        tk = monitor.resolve_ticker(asset)
    except Exception:  # noqa: BLE001
        tk = None
    if not tk:
        return None, asset, None
    cur = "€" if holdings.is_eur(None, tk) else "$"
    return tk, asset, cur


def _norm_account(raw: str) -> str:
    r = (raw or "").upper()
    if "PEA" in r or "ÉPARGNE" in r or "EPARGNE" in r or "PLAN" in r:
        return "PEA"
    return "CTO"  # Compte-Titres par défaut


def normalize(fields: dict) -> dict | None:
    """Transforme la sortie vision en transaction prête à enregistrer."""
    if not fields or fields.get("kind") != "transaction":
        return None
    ticker, name, cur = _resolve_ticker(fields.get("asset", ""))
    if not ticker:
        return {"_error": f"actif non reconnu : « {fields.get('asset')} »"}
    action = "sell" if str(fields.get("action", "")).lower() in ("sell", "vente") else "buy"

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0

    shares = num(fields.get("shares"))
    price = num(fields.get("price_eur"))
    fees = num(fields.get("fees_eur"))
    total = num(fields.get("total_eur")) or (shares * price + (fees if action == "buy" else -fees))
    return {
        "action": action, "account": _norm_account(fields.get("account")),
        "ticker": ticker, "name": name, "cur": cur,
        "shares": shares, "price_eur": price, "fees_eur": fees, "total_eur": total,
        "date": fields.get("date"),
    }


# ─────────────────────────────────────────────────────────────
# ENREGISTREMENT
# ─────────────────────────────────────────────────────────────

def _predates_snapshot(date_str: str | None) -> bool:
    snap = getattr(config, "HOLDINGS_SNAPSHOT_DATE", None)
    if not snap or not date_str:
        return False
    try:
        return dt.date.fromisoformat(date_str) <= dt.date.fromisoformat(snap)
    except ValueError:
        return False


def record(tx: dict) -> str:
    """Enregistre la transaction (journal + registre) et renvoie la confirmation."""
    ledger = holdings.ensure_ledger()
    already = _predates_snapshot(tx.get("date"))

    if already:
        applied = {"ok": True, "msg": "déjà incluse dans le relevé (journalisée seulement)."}
    else:
        applied = holdings.apply_transaction(ledger, tx)
        if applied["ok"]:
            holdings.save_ledger(ledger)

    journal = holdings.load_journal()
    journal.append({**tx, "applied": applied["ok"] and not already})
    holdings.save_journal(journal)

    return _confirm(tx, applied, already, ledger)


def _confirm(tx: dict, applied: dict, already: bool, ledger: dict) -> str:
    verbe = "ACHAT" if tx["action"] == "buy" else "VENTE"
    emoji = "🟢" if tx["action"] == "buy" else "🔴"
    lines = [
        f"{emoji} {verbe} enregistré — {tx['name']} ({tx['ticker']}) · {tx['account']}",
        f"   {tx['shares']:g} × {tx['price_eur']:.4g} € = {tx['total_eur']:.2f} €"
        + (f" (frais {tx['fees_eur']:.2f} €)" if tx.get("fees_eur") else ""),
    ]
    if not applied["ok"]:
        lines.append(f"   ⚠️ {applied['msg']}")
        return "\n".join(lines)
    if already:
        lines.append("   ℹ️ Datée avant ton relevé : déjà comptée, je l'ai juste notée.")
    else:
        pos = ledger.get(holdings._key(tx["account"], tx["ticker"]))
        if pos:
            lines.append(f"   → position : {pos['shares']:g} parts, "
                         f"investi {pos['cost_eur']:.2f} €")
    lines.append("   (Vérifie : si c'est faux, /annuler pour retirer la dernière.)")
    return "\n".join(lines)


def undo_last() -> str:
    """Annule la dernière transaction enregistrée (rejoue le journal restant)."""
    journal = holdings.load_journal()
    if not journal:
        return "Aucune transaction à annuler."
    removed = journal.pop()
    holdings.save_journal(journal)
    # On reconstruit le registre depuis le seed + le journal restant.
    ledger = holdings.seed_ledger()
    for tx in journal:
        if tx.get("applied"):
            holdings.apply_transaction(ledger, tx)
    holdings.save_ledger(ledger)
    return f"↩️ Annulé : {removed.get('action', '?')} {removed.get('shares', '?')} {removed.get('ticker', '?')}."


def format_journal(limit: int = 15) -> str:
    journal = holdings.load_journal()
    if not journal:
        return "📒 Journal vide — aucune transaction enregistrée."
    lines = [f"📒 Dernières transactions ({min(limit, len(journal))}/{len(journal)}) :"]
    for tx in journal[-limit:][::-1]:
        emoji = "🟢" if tx.get("action") == "buy" else "🔴"
        d = f" · {tx['date']}" if tx.get("date") else ""
        lines.append(f"{emoji} {tx.get('name', tx.get('ticker'))} : "
                     f"{tx.get('shares', '?'):g} × {tx.get('price_eur', 0):.4g} € "
                     f"= {tx.get('total_eur', 0):.2f} €{d}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# PORTE D'ENTRÉE DES CAPTURES (transaction OU tweet)
# ─────────────────────────────────────────────────────────────

def handle_screenshot(image_url: str, send: bool = True) -> str:
    """Lit une capture : transaction -> enregistrement ; sinon -> analyse de tweet."""
    fields = extract(image_url)
    if fields is None:
        msg = "📷 Lecture de l'image impossible, réessaie avec une capture plus nette."
        if send:
            _send(msg)
        return msg

    if fields.get("kind") == "transaction":
        tx = normalize(fields)
        if tx is None:
            msg = "📷 Capture lue mais ce n'est pas une transaction exploitable."
        elif tx.get("_error"):
            msg = f"📷 {tx['_error']}. Dis-moi le ticker et je l'ajoute."
        else:
            msg = record(tx)
        if send:
            _send(msg)
        return msg

    # Pas une transaction -> ancien comportement (capture de tweet)
    import tweet
    return tweet.analyze_image(image_url, send=send)


def _send(msg: str) -> None:
    try:
        from alerts import telegram_bot
        telegram_bot.send_message(msg)
    except Exception as e:  # noqa: BLE001
        logger.warning("Envoi confirmation transaction échoué : %s", e)
