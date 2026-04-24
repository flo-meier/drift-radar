// Cloudflare Worker · Drift Radar · jury-accessible workflow trigger
//
// Accepts POST /dispatch from the Drift Radar frontend, rate-limits per IP
// (in-memory, 60 s window), then calls the GitHub workflow_dispatch API on
// flo-meier/drift-radar.
//
// The GH_TOKEN secret must be a fine-grained PAT with
//   Repository: flo-meier/drift-radar
//   Permissions · Actions: Read and write
// and nothing else.
//
// Deployed via `wrangler deploy`. No KV, no DB – stateless on purpose.

const REPO = "flo-meier/drift-radar";
const WORKFLOW = "drift-radar-weekly.yml";

const ALLOWED_ORIGINS = new Set([
  "https://drift-radar.pages.dev",
  "http://localhost:4321",
  "http://localhost:3000",
]);

// Per-instance rate limiter. Multiple isolates = best-effort only, good enough
// for a jury-demo. For stricter guarantees the token rotation is the real fence.
const lastTrigger = new Map();
const RATE_LIMIT_SECONDS = 60;

function cors(origin) {
  const allow = ALLOWED_ORIGINS.has(origin) ? origin : "https://drift-radar.pages.dev";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Max-Age": "86400",
  };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("origin") || "";
    const h = cors(origin);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: h });
    }

    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") {
      return json({ ok: true, service: "drift-radar-trigger" }, 200, h);
    }
    if (url.pathname !== "/dispatch") {
      return json({ error: "not found" }, 404, h);
    }
    if (request.method !== "POST") {
      return json({ error: "method not allowed" }, 405, h);
    }
    if (!env.GH_TOKEN) {
      return json({ error: "worker not configured (missing GH_TOKEN secret)" }, 500, h);
    }

    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    const now = Math.floor(Date.now() / 1000);
    const last = lastTrigger.get(ip) || 0;
    if (now - last < RATE_LIMIT_SECONDS) {
      const wait = RATE_LIMIT_SECONDS - (now - last);
      return json(
        { ok: false, error: `rate limited, wait ${wait}s`, retry_after_seconds: wait },
        429,
        h,
      );
    }
    lastTrigger.set(ip, now);

    // Tiny housekeeping so the map stays small on long-lived isolates.
    if (lastTrigger.size > 1000) {
      for (const [k, v] of lastTrigger) {
        if (now - v > 600) lastTrigger.delete(k);
      }
    }

    try {
      const ghResp = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${env.GH_TOKEN}`,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "drift-radar-trigger-worker",
            "content-type": "application/json",
          },
          body: JSON.stringify({
            ref: "main",
            inputs: { date_range_days: "7" },
          }),
        },
      );

      if (ghResp.status === 204) {
        return json(
          {
            ok: true,
            message: "Workflow dispatched. Run will appear at the GitHub Actions page in 5–10 seconds.",
            runs_url: `https://github.com/${REPO}/actions/workflows/${WORKFLOW}`,
          },
          200,
          h,
        );
      }

      const detail = (await ghResp.text()).slice(0, 400);
      return json(
        {
          ok: false,
          error: `github api returned ${ghResp.status}`,
          detail,
        },
        502,
        h,
      );
    } catch (e) {
      return json(
        {
          ok: false,
          error: "network error reaching github",
          detail: String(e).slice(0, 240),
        },
        502,
        h,
      );
    }
  },
};
