"""
autotune.py — Auto-réglage des sorties (objectif / stop / horizon).

Boucle fermée : l'agent ré-optimise périodiquement ses niveaux de sortie sur
son propre historique de prix, en walk-forward (anti-surajustement), et applique
le meilleur réglage TOUT SEUL — sans intervention de Rémy ni modification du code.

Garde-fous (on ne change un réglage qui marche que si la preuve est solide) :
  - on ne retient qu'un candidat validé en TEST (jamais sur l'apprentissage) ;
  - le candidat doit BATTRE le réglage actif en espérance TEST d'une marge
    minimale (min_improvement_pp) ;
  - taux de réussite TEST minimal exigé (min_test_winrate) ;
  - espérance TEST strictement positive.

Le réglage retenu est stocké dans l'état (clé 'risk_override') ; market_context
.compute_levels le lit automatiquement. Tout changement est historisé et notifié
sur Telegram.

Lancer manuellement : python autotune.py [annees] [--apply]
(sans --apply : simulation, n'écrit rien.)
"""

import sys
import logging
import datetime as dt

import config
import optimize
import market_context

logger = logging.getLogger("autotune")

STATE_OVERRIDE = "risk_override"
STATE_HISTORY = "risk_override_history"
STATE_LAST_RUN = "last_autotune"


# ─────────────────────────────────────────────────────────────
# CORRESPONDANCE réglage <-> override
# ─────────────────────────────────────────────────────────────

def active_spec() -> tuple[tuple, tuple, int]:
    """Réglage actif sous forme (target_spec, stop_spec, horizon)."""
    r = market_context.get_active_risk()
    if "target_kind" in r and "stop_kind" in r:
        ts = (r["target_kind"], float(r["target_value"]))
        ss = (r["stop_kind"], float(r["stop_value"]))
    elif r.get("mode") == "atr":
        ts = ("atr", float(r["atr_target_mult"]))
        ss = ("atr", float(r["atr_stop_mult"]))
    else:
        ts = ("pct", float(r["fixed_target_pct"]))
        ss = ("pct", float(r["fixed_stop_pct"]))
    return ts, ss, int(r["default_horizon"])


def spec_to_params(target_spec, stop_spec, horizon) -> dict:
    """Convertit un réglage gagnant en override partiel pour config.RISK."""
    return {
        "target_kind": target_spec[0], "target_value": float(target_spec[1]),
        "stop_kind": stop_spec[0], "stop_value": float(stop_spec[1]),
        "default_horizon": int(horizon),
        "mode": "atr" if (target_spec[0] == "atr" or stop_spec[0] == "atr") else "fixed",
    }


# ─────────────────────────────────────────────────────────────
# DÉCISION (pure, testable sans réseau)
# ─────────────────────────────────────────────────────────────

def choose_candidate(rows: list[dict],
                     min_winrate: float = 55.0,
                     min_avg_win: float = 10.0) -> dict | None:
    """
    Sélectionne le meilleur réglage selon le critère de Rémy (réussite élevée
    ET gains des gagnants >= 10%), trié par espérance TEST. Si aucun ne passe le
    critère strict, on retombe sur la meilleure espérance TEST globale.
    """
    if not rows:
        return None
    crit = [r for r in rows if r["te"]["win"] >= min_winrate and r["te"]["avg_win"] >= min_avg_win]
    pool = crit or rows
    pool = sorted(pool, key=lambda r: r["te"]["exp"], reverse=True)
    return pool[0]


def should_apply(candidate: dict, current: dict | None,
                 min_improvement_pp: float = 0.5,
                 min_test_winrate: float = 50.0) -> tuple[bool, str]:
    """
    Décide si on applique le candidat. Retourne (appliquer?, raison lisible).
    Garde-fous : espérance TEST positive, réussite mini, et marge d'amélioration
    par rapport au réglage actif.
    """
    if not candidate:
        return False, "aucun candidat évaluable"
    cte = candidate["te"]
    if cte["exp"] <= 0:
        return False, f"espérance TEST non positive ({cte['exp']:+.2f}%)"
    if cte["win"] < min_test_winrate:
        return False, f"réussite TEST trop faible ({cte['win']:.0f}% < {min_test_winrate:.0f}%)"
    if current is None:
        return True, f"pas de référence actuelle évaluable — adoption ({cte['exp']:+.2f}%)"
    gain = cte["exp"] - current["te"]["exp"]
    if gain < min_improvement_pp:
        return False, (f"gain insuffisant ({cte['exp']:+.2f}% vs actuel "
                       f"{current['te']['exp']:+.2f}%, +{gain:.2f}pp < {min_improvement_pp}pp)")
    return True, (f"espérance TEST {cte['exp']:+.2f}% vs actuel "
                  f"{current['te']['exp']:+.2f}% (+{gain:.2f}pp)")


def _same_spec(a: tuple, b: tuple) -> bool:
    return a[0] == b[0] and abs(float(a[1]) - float(b[1])) < 1e-9


# ─────────────────────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────────────────────

def run_autotune(years: int | None = None, apply: bool = True, notify: bool = True) -> dict:
    """Ré-optimise, décide, et (si apply) persiste l'override + notifie."""
    cfg = config.AUTOTUNE
    years = years or cfg["years"]

    train, test, cutoff = optimize.build_signals(years)
    n = len(train) + len(test)
    if n < cfg["min_signals"] or not test:
        msg = f"Auto-tuning ignoré : trop peu de signaux ({n}, min {cfg['min_signals']})."
        logger.info(msg)
        return {"ran": False, "reason": msg, "signals": n}

    rows = optimize.grid(train, test)
    candidate = choose_candidate(rows, cfg["min_winrate"], cfg["min_avg_win"])

    # Réglage actif évalué sur LE MÊME jeu test (comparaison équitable)
    cur_ts, cur_ss, cur_h = active_spec()
    current = optimize.eval_config(train, test, cur_ts, cur_ss, cur_h)

    apply_it, reason = should_apply(candidate, current,
                                    cfg["min_improvement_pp"], cfg["min_test_winrate"])

    # Pas de changement si le candidat = réglage actif
    if apply_it and candidate and _same_spec(candidate["target"], cur_ts) \
            and _same_spec(candidate["stop"], cur_ss) and int(candidate["horizon"]) == cur_h:
        apply_it, reason = False, "le réglage actif est déjà optimal"

    result = {
        "ran": True, "signals": n, "cutoff": str(cutoff.date()) if cutoff else None,
        "candidate": candidate["cfg"] if candidate else None,
        "candidate_te": candidate["te"] if candidate else None,
        "current_cfg": f"obj {cur_ts[0]}{cur_ts[1]} / stop {cur_ss[0]}{cur_ss[1]} / {cur_h}j",
        "current_te": current["te"] if current else None,
        "applied": False, "reason": reason,
    }

    if apply_it and apply:
        params = spec_to_params(candidate["target"], candidate["stop"], candidate["horizon"])
        _persist(params, candidate, current, reason)
        result["applied"] = True
        result["params"] = params
        logger.info("Auto-tuning APPLIQUÉ : %s (%s)", candidate["cfg"], reason)
        if notify:
            _notify(candidate, current, reason)
    else:
        logger.info("Auto-tuning : pas de changement (%s)", reason)

    _mark_run()
    return result


def _persist(params: dict, candidate: dict, current: dict | None, reason: str) -> None:
    from memory import state
    record = {
        "params": params,
        "cfg": candidate["cfg"],
        "test_metrics": candidate["te"],
        "previous_cfg": (current and current["cfg"]) or None,
        "previous_test_metrics": (current and current["te"]) or None,
        "reason": reason,
        "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    state.set_state(STATE_OVERRIDE, record)
    history = state.get_state(STATE_HISTORY, default=[]) or []
    history.append({"applied_at": record["applied_at"], "cfg": candidate["cfg"], "reason": reason})
    state.set_state(STATE_HISTORY, history[-50:])  # on borne l'historique
    market_context.get_active_risk(force_reload=True)  # rafraîchit le cache process


def _mark_run() -> None:
    try:
        from memory import state
        state.set_state(STATE_LAST_RUN, dt.date.today().isoformat())
    except Exception as e:  # noqa: BLE001
        logger.warning("Marquage last_autotune échoué : %s", e)


def due(today: dt.date | None = None) -> bool:
    """True si l'auto-tuning n'a pas tourné depuis min_interval_days."""
    today = today or dt.date.today()
    try:
        from memory import state
        last = state.get_state(STATE_LAST_RUN, default=None)
    except Exception:  # noqa: BLE001
        last = None
    if not last:
        return True
    try:
        last_d = dt.date.fromisoformat(last)
    except Exception:  # noqa: BLE001
        return True
    return (today - last_d).days >= config.AUTOTUNE["min_interval_days"]


def _notify(candidate: dict, current: dict | None, reason: str) -> None:
    try:
        from alerts import telegram_bot
        te = candidate["te"]
        prev = f"\nAvant : {current['cfg']} (espérance {current['te']['exp']:+.2f}%)" if current else ""
        msg = (
            "🔧 *Auto-réglage des sorties*\n"
            f"Nouveau réglage : `{candidate['cfg']}`\n"
            f"Réussite TEST {te['win']:.0f}% · gagnants {te['avg_win']:.1f}% · "
            f"espérance {te['exp']:+.2f}%{prev}\n"
            f"_{reason}_"
        )
        telegram_bot.send_message(msg)
    except Exception as e:  # noqa: BLE001
        logger.warning("Notification auto-tuning échouée : %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    yrs = None
    apply = "--apply" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            yrs = int(a)
    out = run_autotune(years=yrs, apply=apply, notify=apply)
    print("\n=== AUTO-TUNING ===")
    for k, v in out.items():
        print(f"{k}: {v}")
    if not apply:
        print("\n(simulation — relance avec --apply pour écrire le réglage)")
