"""
bilan.py — Bilan complet et consolidé du paper trading depuis le début.

Réunit en UN seul rapport :
  1) le paper trading RÉEL (alertes envoyées au seuil 75) ;
  2) la simulation réaliste par seuil (budget 1500 €, valeurs Trade Republic) ;
  3) la couverture (période, nb d'actions étudiées, trades clos vs en cours).

But : répondre à "combien depuis le début ?" en une vue d'ensemble honnête.
"""

import logging

logger = logging.getLogger("bilan")


def _first_date(log: dict) -> str | None:
    return min(log.keys()) if log else None


def global_report(send: bool = True) -> str:
    from memory import state
    log = state.get_state("activity", default={}) or {}
    days = len(log)
    first = _first_date(log)

    # 1) Paper trading réel (alertes >= 75 effectivement envoyées)
    real_line = ""
    try:
        import paper_trading
        pt = paper_trading.compute_portfolio(live=True)
        if pt.get("n_total", 0) == 0:
            real_line = ("Aucune alerte réelle envoyée — le bot n'a jugé aucune action "
                         "≥ 75/100. C'est NORMAL : il est volontairement très sélectif.")
        else:
            real_line = (f"{pt['n_total']} position(s) · {pt['n_closed']} clôturée(s) · "
                         f"réussite {pt['win_rate']*100:.0f}% · P&L {pt['pnl_eur']:+,.0f} €")
    except Exception as e:  # noqa: BLE001
        real_line = f"(indisponible : {e})"

    # 2) Couverture (combien arrivés à terme)
    closed = total = 0
    try:
        import thresholds
        ts = thresholds.simulate(levels=(75, 70, 65, 60))
        total, closed = ts.get("total", 0), ts.get("closed", 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("couverture KO : %s", e)

    # 3) Simulation réaliste budget 1500 € par seuil
    sim_lines = []
    try:
        import budget_sim
        sim = budget_sim.simulate(levels=[75, 70, 65, 60])
        budget = sim["budget"]
        for w in sim["wallets"]:
            if w["trades"] == 0:
                sim_lines.append(f"  • seuil {w['level']} : aucun trade clôturé")
            else:
                wr = w["wins"] / w["trades"] * 100
                sim_lines.append(f"  • seuil {w['level']} : {w['trades']} trades · {wr:.0f}% gagnants · "
                                 f"{w['realized']:+,.0f} € → {w['final']:,.0f} €")
    except Exception as e:  # noqa: BLE001
        budget = 1500
        sim_lines = [f"  (indisponible : {e})"]

    period = f"{days} jour(s)" + (f" (depuis le {first})" if first else "")
    lines = [
        "📊 BILAN COMPLET — PAPER TRADING",
        f"Période : {period}",
        f"Actions étudiées par les IA : {total} · arrivées à terme : {closed} · "
        f"encore en cours : {max(total - closed, 0)}",
        "",
        "1️⃣ ALERTES RÉELLES (seuil 75) :",
        f"   {real_line}",
        "",
        f"2️⃣ SIMULATION RÉALISTE — budget {budget:.0f} € (valeurs Trade Republic only) :",
        "   « Si tu avais investi ce budget en suivant le bot »",
        *sim_lines,
        "",
        "📌 À retenir :",
        f"   • Échantillon encore petit ({closed} trades clos) — chiffres indicatifs, "
        "pas une preuve.",
        "   • Le vrai bilan se construit semaine après semaine, à mesure que les "
        "positions aboutissent.",
        "",
        "(Sorties objectif/stop/horizon. Indicatif, hors frais.)",
    ]
    msg = "\n".join(lines)
    print(msg)
    if send:
        try:
            from alerts import telegram_bot
            telegram_bot.send_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.warning("Envoi bilan échoué : %s", e)
    return msg


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    global_report(send=False)
