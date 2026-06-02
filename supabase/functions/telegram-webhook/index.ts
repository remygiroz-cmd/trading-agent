// telegram-webhook — Réponses INSTANTANÉES aux commandes Telegram.
//
// Telegram envoie chaque message/clic à cette fonction (webhook). Elle répond en
// 1-2 s, 24h/24, sans GitHub Actions. La logique reprend celle du Python
// (alerts/daily_report.py + dashboard.py) en lisant directement Supabase.
//
// Variables d'environnement (secrets de la fonction) :
//   TELEGRAM_BOT_TOKEN        — token du bot
//   TELEGRAM_WEBHOOK_SECRET   — secret partagé (anti-abus), vérifié à chaque appel
//   SUPABASE_URL              — fourni automatiquement par Supabase
//   SUPABASE_SERVICE_ROLE_KEY — fourni automatiquement par Supabase
//
// Déploiement et enregistrement : voir docs/telegram-webhook.md

const TG_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN")!;
const WEBHOOK_SECRET = Deno.env.get("TELEGRAM_WEBHOOK_SECRET") ?? "";
const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const sbHeaders = {
  apikey: SB_KEY,
  Authorization: `Bearer ${SB_KEY}`,
  "Content-Type": "application/json",
};

// ── Accès Supabase REST ──
async function sbSelect(table: string, query: string): Promise<any[]> {
  const r = await fetch(`${SB_URL}/rest/v1/${table}?${query}`, { headers: sbHeaders });
  if (!r.ok) return [];
  return await r.json();
}

async function sbUpsertState(key: string, value: unknown): Promise<void> {
  await fetch(`${SB_URL}/rest/v1/agent_state?on_conflict=key`, {
    method: "POST",
    headers: { ...sbHeaders, Prefer: "resolution=merge-duplicates" },
    body: JSON.stringify({ key, value }),
  });
}

async function sbUpdate(table: string, query: string, patch: unknown): Promise<void> {
  await fetch(`${SB_URL}/rest/v1/${table}?${query}`, {
    method: "PATCH",
    headers: { ...sbHeaders, Prefer: "return=minimal" },
    body: JSON.stringify(patch),
  });
}

// ── Telegram ──
async function tg(method: string, payload: unknown): Promise<void> {
  await fetch(`https://api.telegram.org/bot${TG_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function tgDocument(chatId: number, filename: string, content: string, caption: string): Promise<void> {
  const form = new FormData();
  form.append("chat_id", String(chatId));
  form.append("caption", caption);
  form.append("document", new Blob([content], { type: "text/html" }), filename);
  await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendDocument`, { method: "POST", body: form });
}

// ── Agrégats (miroir de dashboard.py) ──
const pct = (x: number) => `${(x * 100 >= 0 ? "+" : "")}${(x * 100).toFixed(1)}%`;

type Stat = { key: string; n: number; wr: number; avg: number };

function winData(rows: any[], key: string, minN = 2): Stat[] {
  const groups: Record<string, number[]> = {};
  for (const s of rows) {
    if (s.result_7d == null) continue;
    const k = s[key];
    if (!k || k === "n/d") continue;
    (groups[k] ??= []).push(Number(s.result_7d));
  }
  return Object.entries(groups)
    .filter(([, v]) => v.length >= minN)
    .map(([k, v]) => ({
      key: k, n: v.length,
      wr: v.filter((r) => r > 0).length / v.length,
      avg: v.reduce((a, b) => a + b, 0) / v.length,
    }))
    .sort((a, b) => b.n - a.n)
    .slice(0, 8);
}

function convData(rows: any[]): Stat[] {
  const tiers: [string, number, number][] = [
    ["80-100", 80, 101], ["65-79", 65, 80], ["50-64", 50, 65], ["0-49", 0, 50],
  ];
  const out: Stat[] = [];
  for (const [label, lo, hi] of tiers) {
    const v = rows.filter((s) =>
      s.result_7d != null && s.conviction != null && s.conviction >= lo && s.conviction < hi
    ).map((s) => Number(s.result_7d));
    if (!v.length) continue;
    out.push({ key: label, n: v.length, wr: v.filter((r) => r > 0).length / v.length,
               avg: v.reduce((a, b) => a + b, 0) / v.length });
  }
  return out;
}

function globalStats(rows: any[]) {
  const closed = rows.filter((s) => s.result_7d != null);
  const res = closed.map((s) => Number(s.result_7d));
  const gains = res.filter((r) => r > 0);
  const losses = res.filter((r) => r <= 0);
  const pnl = rows.reduce((a, s) => a + (s.realized_pnl_eur != null ? Number(s.realized_pnl_eur) : 0), 0);
  return {
    n: closed.length, open: rows.length - closed.length,
    winRate: closed.length ? gains.length / closed.length : 0,
    avgGain: gains.length ? gains.reduce((a, b) => a + b, 0) / gains.length : 0,
    avgLoss: losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 0,
    exp: closed.length ? res.reduce((a, b) => a + b, 0) / closed.length : 0,
    best: res.length ? Math.max(...res) : 0, worst: res.length ? Math.min(...res) : 0,
    pnl,
  };
}

async function statsMessage(): Promise<string> {
  const rows = await sbSelect("trading_signals",
    "select=result_7d,realized_pnl_eur,sector,cap_bucket,conviction&order=created_at.desc&limit=1000");
  const g = globalStats(rows);
  if (g.n === 0) {
    return `📈 Performances\nAucun signal clos pour l'instant (${g.open} en cours).\n` +
      `Le taux de réussite s'affichera dès les premiers résultats à J+7.`;
  }
  const lines = [
    "📈 Performances globales",
    `Signaux clos : ${g.n} (${g.open} en cours)`,
    `Taux de réussite : ${Math.round(g.winRate * 100)}%`,
    `Gain moyen gagnants : ${pct(g.avgGain)} | perte moyenne : ${pct(g.avgLoss)}`,
    `Espérance/trade : ${pct(g.exp)}`,
    `P&L paper (1000€/trade) : ${g.pnl >= 0 ? "+" : ""}${g.pnl.toFixed(0)}€`,
  ];
  const fmt = (d: Stat[]) => d.map((r) => `  ${r.key} : ${Math.round(r.wr * 100)}% (${r.n})`);
  const block = (title: string, d: Stat[]) => d.length ? ["\n" + title, ...fmt(d)] : [];
  lines.push(...block("🧭 Par secteur :", winData(rows, "sector")));
  lines.push(...block("📦 Par taille :", winData(rows, "cap_bucket")));
  lines.push(...block("🎯 Par conviction :", convData(rows)));
  return lines.join("\n");
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
}

function barRows(d: Stat[]): string {
  if (!d.length) return '<p class="muted">Pas encore de données.</p>';
  return d.map((r) => {
    const wr = r.wr * 100;
    const color = wr >= 55 ? "#16a34a" : wr >= 45 ? "#eab308" : "#dc2626";
    return `<div class="row"><span class="lbl">${esc(r.key)}</span>` +
      `<span class="bar"><span style="width:${wr.toFixed(0)}%;background:${color}"></span></span>` +
      `<span class="val">${wr.toFixed(0)}% (${r.n})</span></div>`;
  }).join("");
}

async function buildHtml(): Promise<string> {
  const rows = await sbSelect("trading_signals",
    "select=created_at,ticker,sector,cap_bucket,conviction,result_7d,realized_pnl_eur&order=created_at.desc&limit=1000");
  const g = globalStats(rows);
  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  const cards: [string, string][] = [
    ["Signaux clos", `${g.n}`], ["En cours", `${g.open}`],
    ["Taux de réussite", `${Math.round(g.winRate * 100)}%`], ["Espérance/trade", pct(g.exp)],
    ["Gain moyen", pct(g.avgGain)], ["Perte moyenne", pct(g.avgLoss)],
    ["P&L paper", `${g.pnl >= 0 ? "+" : ""}${g.pnl.toFixed(0)}€`],
    ["Meilleur / pire", `${pct(g.best)} / ${pct(g.worst)}`],
  ];
  const cardsHtml = cards.map(([k, v]) =>
    `<div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");
  const recent = rows.slice(0, 25).map((s) => {
    const r7 = s.result_7d;
    const res = r7 == null ? '<span class="muted">en cours</span>'
      : `<span style="color:${Number(r7) > 0 ? "#16a34a" : "#dc2626"}">${pct(Number(r7))}</span>`;
    return `<tr><td>${esc((s.created_at ?? "").slice(0, 10))}</td><td>${esc(s.ticker ?? "")}</td>` +
      `<td>${esc(s.sector ?? "—")}</td><td>${s.conviction ?? "—"}</td><td>${res}</td></tr>`;
  }).join("");

  return `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Tableau de bord</title>
<style>
  body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#0f172a;color:#e2e8f0;padding:16px}
  h1{font-size:20px;margin:0 0 4px}.muted{color:#94a3b8;font-size:13px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}
  .card{background:#1e293b;border-radius:12px;padding:12px}.card .k{font-size:12px;color:#94a3b8}
  .card .v{font-size:22px;font-weight:700;margin-top:4px}
  h2{font-size:15px;margin:20px 0 8px;color:#cbd5e1}
  .row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:13px}
  .row .lbl{width:34%}.row .bar{flex:1;background:#334155;border-radius:6px;height:14px;overflow:hidden}
  .row .bar span{display:block;height:100%}.row .val{width:78px;text-align:right;color:#cbd5e1}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:6px 4px;border-bottom:1px solid #1e293b}th{color:#94a3b8}
</style></head><body>
<h1>📊 Agent boursier — Tableau de bord</h1>
<div class="muted">Généré le ${now} · taux de réussite à J+7</div>
<div class="cards">${cardsHtml}</div>
<h2>🧭 Réussite par secteur</h2>${barRows(winData(rows, "sector"))}
<h2>📦 Réussite par taille de capi</h2>${barRows(winData(rows, "cap_bucket"))}
<h2>🎯 Réussite par conviction</h2>${barRows(convData(rows))}
<h2>🕒 Derniers signaux</h2>
<table><tr><th>Date</th><th>Ticker</th><th>Secteur</th><th>Conv.</th><th>J+7</th></tr>
${recent || '<tr><td colspan="5" class="muted">Aucun signal.</td></tr>'}</table>
</body></html>`;
}

async function paperMessage(): Promise<string> {
  const rows = await sbSelect("trading_signals",
    "select=ticker,realized_pct,realized_pnl_eur,closed,is_paper&is_paper=eq.true&limit=1000");
  const closed = rows.filter((s) => s.closed);
  const open = rows.length - closed.length;
  if (!closed.length) {
    return `📝 Paper trading\n${open} position(s) ouverte(s), aucune clôturée pour l'instant.`;
  }
  const wins = closed.filter((s) => Number(s.realized_pct) > 0).length;
  const pnl = closed.reduce((a, s) => a + (s.realized_pnl_eur != null ? Number(s.realized_pnl_eur) : 0), 0);
  return `📝 Paper trading\nClôturées : ${closed.length} · ouvertes : ${open}\n` +
    `Taux de réussite : ${Math.round((wins / closed.length) * 100)}%\n` +
    `P&L : ${pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}€ (1000€/trade)`;
}

async function diagMessage(): Promise<string> {
  const today = new Date().toISOString().slice(0, 10);
  const st = await sbSelect("agent_state", `select=value&key=eq.activity`);
  const log = st.length ? (st[0].value ?? {}) : {};
  const runs = (log as Record<string, any[]>)[today] ?? [];
  if (!runs.length) return "🩺 Santé : aucun scan enregistré aujourd'hui pour l'instant.";
  const sum = (k: string) => runs.reduce((a, r) => a + (r[k] ?? 0), 0);
  const best = Math.max(...runs.map((r) => r.best_score ?? 0));
  const alerts = sum("alerts");
  let msg = `🩺 Santé du jour : ${runs.length} scan(s), ${sum("candidates")} candidats, ` +
    `${sum("finalists")} étudiés par les IA.`;
  msg += alerts ? `\n🔔 ${alerts} alerte(s) aujourd'hui.` :
    `\n✅ Meilleur score : ${best}/100. En dessous du seuil → pas d'alerte. NORMAL.`;
  return msg;
}

const HELP = `👋 Agent boursier connecté.
Commandes :
/stats — performances (réussite par secteur, conviction…)
/dashboard — tableau de bord visuel (fichier à ouvrir)
/paper — portefeuille fictif (1000 €/trade)
/diag — santé du jour (scans, meilleur score)
/status — état du système
/pause /actif /digest — mode d'alerte`;

const MODE_REPLY: Record<string, string> = {
  "/pause": "⏸️ Alertes suspendues. Tape /actif pour reprendre.",
  "/digest": "📥 Mode résumé activé. Une seule alerte à 22h.",
  "/actif": "🔔 Alertes en temps réel activées.",
};

async function handleCommand(text: string): Promise<string> {
  const cmd = text.trim().split(/\s+/)[0].toLowerCase();
  if (cmd === "/pause" || cmd === "/digest" || cmd === "/actif") {
    const mode = cmd === "/pause" ? "pause" : cmd === "/digest" ? "digest" : "actif";
    await sbUpsertState("alert_mode", { mode });
    return MODE_REPLY[cmd];
  }
  if (cmd === "/stats") return await statsMessage();
  if (cmd === "/paper") return await paperMessage();
  if (cmd === "/diag") return await diagMessage();
  if (cmd === "/status") {
    const st = await sbSelect("agent_state", "select=value&key=eq.alert_mode");
    const mode = st.length ? (st[0].value?.mode ?? "actif") : "actif";
    return `📡 Système actif. Mode : ${mode}.`;
  }
  if (cmd === "/start" || cmd === "/help") return HELP;
  if (cmd === "/bilan") {
    const today = new Date().toISOString().slice(0, 10);
    const sigs = await sbSelect("trading_signals",
      `select=ticker&created_at=gte.${today}T00:00:00&created_at=lte.${today}T23:59:59`);
    return `🗓️ ${sigs.length} signal(aux) aujourd'hui.`;
  }
  return "Commande inconnue. Tape /help.";
}

async function handleCallback(data: string): Promise<string> {
  const map: Record<string, [string, string]> = {
    action_taken: ["pris", "✅ Noté : position prise. Je suivrai le résultat."],
    action_ignored: ["ignore", "❌ Noté : signal ignoré."],
    action_watching: ["surveille", "⏳ Noté : tu surveilles."],
  };
  const [key, signalId] = data.split(":", 2);
  if (!(key in map)) return "Action inconnue.";
  const [action, reply] = map[key];
  if (signalId) await sbUpdate("trading_signals", `id=eq.${signalId}`, { user_action: action });
  return reply;
}

Deno.serve(async (req) => {
  if (WEBHOOK_SECRET &&
      req.headers.get("x-telegram-bot-api-secret-token") !== WEBHOOK_SECRET) {
    return new Response("unauthorized", { status: 401 });
  }
  try {
    const update = await req.json();
    if (update.callback_query) {
      const cq = update.callback_query;
      const reply = await handleCallback(cq.data ?? "");
      await tg("answerCallbackQuery", { callback_query_id: cq.id, text: reply });
      await tg("sendMessage", { chat_id: cq.message.chat.id, text: reply });
    } else if (update.message?.text) {
      const text = update.message.text as string;
      const chatId = update.message.chat.id as number;
      if (/^\/dashboard\b/i.test(text.trim())) {
        const html = await buildHtml();
        await tgDocument(chatId, "dashboard.html", html, "📊 Tableau de bord — ouvre-le dans ton navigateur");
      } else {
        await tg("sendMessage", { chat_id: chatId, text: await handleCommand(text) });
      }
    }
  } catch (e) {
    console.error("webhook error", e);
  }
  return new Response("ok");
});
