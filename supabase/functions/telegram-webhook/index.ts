// telegram-webhook — Réponses INSTANTANÉES + commandes de suivi + screenshots.
//
// Réponses instantanées (Supabase) aux commandes Telegram. En plus :
//  - /suivre <ticker|nom> et /unfollow <…>  -> file de commandes + réveil de l'agent
//  - /tweet <texte>                          -> analyse du tweet par les 3 IA
//  - une PHOTO (capture de tweet)            -> lecture par vision IA + débat
// Ces actions sont déposées dans agent_state.monitor_queue ; l'agent (Python, sur
// GitHub) les traite en ~1 min et renvoie le résultat.
//
// Secrets de la fonction :
//   TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, GH_TOKEN
//   (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY fournis automatiquement)

const TG_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN")!;
const WEBHOOK_SECRET = Deno.env.get("TELEGRAM_WEBHOOK_SECRET") ?? "";
const GH_TOKEN = Deno.env.get("GH_TOKEN") ?? "";
const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const GH_OWNER = "remygiroz-cmd", GH_REPO = "trading-agent", GH_WORKFLOW = "agent.yml";

const sbHeaders = {
  apikey: SB_KEY,
  Authorization: `Bearer ${SB_KEY}`,
  "Content-Type": "application/json",
};

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
async function tgFileUrl(fileId: string): Promise<string | null> {
  const r = await fetch(`https://api.telegram.org/bot${TG_TOKEN}/getFile?file_id=${fileId}`);
  const d = await r.json();
  const path = d?.result?.file_path;
  return path ? `https://api.telegram.org/file/bot${TG_TOKEN}/${path}` : null;
}

// ── File de commandes + réveil de l'agent ──
async function queueCommand(action: string, arg: string): Promise<void> {
  const rows = await sbSelect("agent_state", "select=value&key=eq.monitor_queue");
  const cur = (rows.length && Array.isArray(rows[0].value)) ? rows[0].value : [];
  cur.push({ action, arg });
  await sbUpsertState("monitor_queue", cur);
}
async function wakeAgent(): Promise<void> {
  if (!GH_TOKEN) return;
  await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${GH_WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${GH_TOKEN}`, Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "trading-agent", "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { command: "cron" } }),
  });
}

// ── Agrégats (miroir de dashboard.py) ──
const pct = (x: number) => `${(x * 100 >= 0 ? "+" : "")}${(x * 100).toFixed(1)}%`;
function winrateBy(rows: any[], key: string, minN = 2): string[] {
  const g: Record<string, number[]> = {};
  for (const s of rows) {
    if (s.result_7d == null) continue;
    const k = s[key];
    if (!k || k === "n/d") continue;
    (g[k] ??= []).push(Number(s.result_7d));
  }
  return Object.entries(g).filter(([, v]) => v.length >= minN).sort((a, b) => b[1].length - a[1].length)
    .slice(0, 6).map(([k, v]) => `  ${k} : ${Math.round((v.filter((r) => r > 0).length / v.length) * 100)}% (${v.length})`);
}

async function paperMessage(): Promise<string> {
  const rows = await sbSelect("trading_signals",
    "select=ticker,realized_pct,realized_pnl_eur,closed,is_paper&is_paper=eq.true&limit=1000");
  const closed = rows.filter((s) => s.closed);
  const open = rows.length - closed.length;
  if (!closed.length) return `📝 Paper trading\n${open} position(s) ouverte(s), aucune clôturée.`;
  const wins = closed.filter((s) => Number(s.realized_pct) > 0).length;
  const pnl = closed.reduce((a, s) => a + (s.realized_pnl_eur != null ? Number(s.realized_pnl_eur) : 0), 0);
  return `📝 Paper trading\nClôturées : ${closed.length} · ouvertes : ${open}\n` +
    `Réussite : ${Math.round((wins / closed.length) * 100)}%\nP&L : ${pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}€`;
}

async function diagMessage(): Promise<string> {
  const today = new Date().toISOString().slice(0, 10);
  const st = await sbSelect("agent_state", `select=value&key=eq.activity`);
  const log = st.length ? (st[0].value ?? {}) : {};
  const runs = (log as Record<string, any[]>)[today] ?? [];
  if (!runs.length) return "🩺 Santé : aucun passage enregistré aujourd'hui pour l'instant.";
  return `🩺 ${runs.length} passage(s) aujourd'hui — système actif.`;
}

const HELP = `👋 Agent de suivi de portefeuille.
/portefeuille — valeur en temps réel de ton CTO + PEA (PV + variation du jour)
📷 Envoie une CAPTURE de transaction Trade Republic -> je l'ajoute au portefeuille
/transactions — journal de tes achats/ventes enregistrés
/annuler — retirer la dernière transaction enregistrée
/monitor — bulletin de suivi (achat/vente sur tes valeurs)
/liste — voir toutes les actions actuellement suivies
/suivre <ticker|nom> — suivre une nouvelle action (ex. /suivre $NVDA)
/unfollow <ticker|nom> — ne plus suivre
/tweet <texte> — analyser un tweet par les 3 IA
📷 Une capture de tweet -> les 3 IA l'analysent
/paper /diag /status /pause /actif`;

const MODE_REPLY: Record<string, string> = {
  "/pause": "⏸️ Alertes suspendues. Tape /actif pour reprendre.",
  "/actif": "🔔 Alertes réactivées.",
  "/digest": "📥 Mode résumé activé.",
};

function argOf(text: string): string {
  return text.trim().split(/\s+/).slice(1).join(" ").trim();
}

async function handleCommand(text: string): Promise<string> {
  const cmd = text.trim().split(/\s+/)[0].toLowerCase();

  if (cmd === "/suivre" || cmd === "/follow") {
    const arg = argOf(text);
    if (!arg) return "Usage : /suivre <ticker ou nom>  (ex. /suivre $NVDA ou /suivre Nvidia)";
    await queueCommand("follow", arg); await wakeAgent();
    return `📝 OK, je vais suivre « ${arg} ». Confirmation dans ~1 min.`;
  }
  if (cmd === "/unfollow" || cmd === "/unsuivre" || cmd === "/nepasuivre") {
    const arg = argOf(text);
    if (!arg) return "Usage : /unfollow <ticker ou nom>";
    await queueCommand("unfollow", arg); await wakeAgent();
    return `📝 OK, j'arrête de suivre « ${arg} ». Confirmation dans ~1 min.`;
  }
  if (cmd === "/liste" || cmd === "/suivis" || cmd === "/watchlist") {
    await queueCommand("list", ""); await wakeAgent();
    return "📋 Je te prépare la liste des actions suivies… (~1 min).";
  }
  if (cmd === "/portefeuille" || cmd === "/pf" || cmd === "/portfolio" || cmd === "/pea" || cmd === "/cto") {
    await queueCommand("portfolio", ""); await wakeAgent();
    return "💼 Je calcule ton portefeuille en temps réel (CTO + PEA)… réponse dans ~1 min.";
  }
  if (cmd === "/transactions" || cmd === "/journal" || cmd === "/tx") {
    await queueCommand("journal", ""); await wakeAgent();
    return "📒 Je te sors le journal des transactions… (~1 min).";
  }
  if (cmd === "/annuler" || cmd === "/undo") {
    await queueCommand("undo_tx", ""); await wakeAgent();
    return "↩️ J'annule la dernière transaction enregistrée… (~1 min).";
  }
  if (cmd === "/tweet") {
    const arg = argOf(text);
    if (!arg) return "Colle le texte du tweet après /tweet (ou envoie une capture d'écran).";
    await queueCommand("tweet", arg); await wakeAgent();
    return "📨 Tweet reçu — les 3 IA l'analysent (~1 min).";
  }
  if (cmd === "/pause" || cmd === "/actif" || cmd === "/digest") {
    const mode = cmd === "/pause" ? "pause" : cmd === "/digest" ? "digest" : "actif";
    await sbUpsertState("alert_mode", { mode });
    return MODE_REPLY[cmd];
  }
  if (cmd === "/paper") return await paperMessage();
  if (cmd === "/diag") return await diagMessage();
  if (cmd === "/status") return "📡 Système actif (mode suivi de portefeuille).";
  if (cmd === "/monitor") {
    await queueCommand("noop", ""); // force un réveil ; le bulletin part du créneau du matin
    await wakeAgent();
    return "📋 Je prépare ton bulletin de suivi… (il arrive au prochain passage)";
  }
  if (cmd === "/start" || cmd === "/help") return HELP;
  return "Commande inconnue. Tape /help.";
}

async function handleCallback(data: string): Promise<string> {
  const map: Record<string, [string, string]> = {
    action_taken: ["pris", "✅ Noté : position prise."],
    action_ignored: ["ignore", "❌ Noté : ignoré."],
    action_watching: ["surveille", "⏳ Noté : tu surveilles."],
  };
  const [key, signalId] = data.split(":", 2);
  if (!(key in map)) return "Action inconnue.";
  const [action, reply] = map[key];
  if (signalId) await sbUpdate("trading_signals", `id=eq.${signalId}`, { user_action: action });
  return reply;
}

Deno.serve(async (req) => {
  if (WEBHOOK_SECRET && req.headers.get("x-telegram-bot-api-secret-token") !== WEBHOOK_SECRET) {
    return new Response("unauthorized", { status: 401 });
  }
  try {
    const update = await req.json();
    if (update.callback_query) {
      const cq = update.callback_query;
      const reply = await handleCallback(cq.data ?? "");
      await tg("answerCallbackQuery", { callback_query_id: cq.id, text: reply });
      await tg("sendMessage", { chat_id: cq.message.chat.id, text: reply });
    } else if (update.message?.photo) {
      // Capture d'écran -> analyse par vision IA
      const chatId = update.message.chat.id as number;
      const photos = update.message.photo;
      const fileId = photos[photos.length - 1].file_id;   // plus grande taille
      const url = await tgFileUrl(fileId);
      if (url) {
        await queueCommand("screenshot", url);
        await wakeAgent();
        await tg("sendMessage", { chat_id: chatId, text: "📷 Capture reçue — je la lis (transaction ou tweet), réponse dans ~1 min." });
      } else {
        await tg("sendMessage", { chat_id: chatId, text: "Je n'ai pas pu récupérer l'image, réessaie." });
      }
    } else if (update.message?.text) {
      await tg("sendMessage", { chat_id: update.message.chat.id, text: await handleCommand(update.message.text) });
    }
  } catch (e) {
    console.error("webhook error", e);
  }
  return new Response("ok");
});
