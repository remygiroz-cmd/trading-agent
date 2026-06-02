// trigger-agent — Minuteur FIABLE (Supabase) qui réveille l'agent sur GitHub.
//
// Problème : le minuteur gratuit de GitHub Actions saute parfois des créneaux.
// Solution : Supabase Cron appelle cette fonction à heures fixes ; elle demande à
// GitHub de lancer le job `cron` (qui décide ensuite quoi faire : buzz, scan,
// bilan…). Le cerveau Python reste sur GitHub, seul le déclenchement passe par
// Supabase (fiable).
//
// Secret nécessaire (à poser sur la fonction) :
//   GH_TOKEN — un token GitHub (fine-grained) avec le droit "Actions: Read and write"
//              sur le dépôt remygiroz-cmd/trading-agent
//
// Planification : voir docs/supabase-cron.md

const GH_TOKEN = Deno.env.get("GH_TOKEN")!;
const OWNER = "remygiroz-cmd";
const REPO = "trading-agent";
const WORKFLOW = "agent.yml";

Deno.serve(async () => {
  const r = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "trading-agent-cron",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { command: "cron" } }),
    },
  );
  const ok = r.status === 204; // GitHub renvoie 204 quand le déclenchement réussit
  if (!ok) console.error("dispatch KO", r.status, await r.text());
  return new Response(JSON.stringify({ triggered: ok, status: r.status }), {
    status: ok ? 200 : 500,
    headers: { "Content-Type": "application/json" },
  });
});
