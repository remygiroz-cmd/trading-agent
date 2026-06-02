// telegram-webhook — Réponses INSTANTANÉES aux commandes Telegram.
//
// Telegram envoie chaque message/clic à cette fonction (webhook). Elle répond en
// 1-2 s, 24h/24, sans GitHub Actions. La logique reprend celle du Python
// (alerts/daily_report.py) en lisant directement Supabase.
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

// ── Helpers d'agrégation (miroir de dashboard.py) ──
const pct = (x: number) => `${(x * 100 >= 0 ? "+" : "")}${(x * 100).toFixed(1)}%`;

function winrateBy(rows: any[], key: string, minN = 2): string[] {
  const groups: Record<string, number[]> = {};
  for (const s of rows) {
    if (s.result_7d == null) continue;
    const k = s[key];
    if (!k || k === "n/d") continue;
    (groups[k] ??= []).push(Number(s.result_7d));
  }
  return Object.entries(groups)
    .filter(([, v]) => v.length >= minN)
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 6)
    .map(([k, v]) => {
      const wins = v.filter((r) => r > 0).length;
      return `  ${k} : ${Math.round((wins / v.length) * 100)}% (${v.length})`;
    });
}

function convTiers(rows: any[]): string[] {
  const tiers: [string, number, number][] = [
    ["80-100", 80, 101], ["65-79", 65, 80], ["50-64", 50, 65], ["0-49", 0, 50],
  ];
  const out: string[] = [];
  for (const [label, lo, hi] of tiers) {
    const v = rows.filter((s) =>
      s.result_7d != null && s.conviction != null &&
      s.conviction >= lo && s.conviction < hi
    ).map((s) => Number(s.result_7d));
    if (!v.length) continue;
    const wins = v.filter((r) => r > 0).length;
    out.push(`  ${label} : ${Math.round((wins / v.length) * 100)}% (${v.length})`);
  }
  return out;
}

async function statsMessage(): Promise<string> {
  const rows = await sbSelect("trading_signals",
    "select=result_7d,realized_pnl_eur,sector,cap_bucket,conviction&order=created_at.desc&limit=1000");
  const closed = rows.filter((s) => s.result_7d != null);
  if (!closed.length) {
    return `📈 Performances\nAucun signal clos pour l'instant (${rows.length} en cours).\n` +
      `Le taux de réussite s'affichera dès les premiers résultats à J+7.`;
  }
  const res = closed.map((s) => Number(s.result_7d));
  const gains = res.filter((r) => r > 0);
  const losses = res.filter((r) => r <= 0);
  const pnl = rows.reduce((a, s) => a + (s.realized_pnl_eur != null ? Number(s.realized_pnl_eur) : 0), 0);
  const lines = [
    "📈 Performances globales",
    `Signaux clos : ${closed.length} (${rows.length - closed.length} en cours)`,
    `Taux de réussite : ${Math.round((gains.length / closed.length) * 100)}%`,
    `Gain moyen gagnants : ${pct(gains.length ? gains.reduce((a, b) => a + b, 0) / gains.length : 0)} | ` +
    `perte moyenne : ${pct(losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 0)}`,
    `Espérance/trade : ${pct(res.reduce((a, b) => a + b, 0) / res.length)}`,
    `P&L paper (1000€/trade) : ${pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}€`,
  ];
  const block = (title: string, arr: string[]) => arr.length ? ["\n" + title, ...arr] : [];
  lines.push(...block("🧭 Par secteur :", winrateBy(rows, "sector")));
  lines.push(...block("📦 Par taille :", winrateBy(rows, "cap_bucket")));
  lines.push(...block("🎯 Par conviction :", convTiers(rows)));
  return lines.join("\n");
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
  if (cmd === "/dashboard" || cmd === "/bilan") {
    return "Cette commande est générée par le bilan automatique (elle arrivera au prochain passage).";
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
  if (signalId) {
    await sbUpdate("trading_signals", `id=eq.${signalId}`, { user_action: action });
  }
  return reply;
}

Deno.serve(async (req) => {
  // Anti-abus : Telegram renvoie le secret dans cet en-tête
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
      const reply = await handleCommand(update.message.text);
      await tg("sendMessage", { chat_id: update.message.chat.id, text: reply });
    }
  } catch (e) {
    console.error("webhook error", e);
  }
  // On répond toujours 200 pour que Telegram ne ré-essaie pas en boucle
  return new Response("ok");
});
