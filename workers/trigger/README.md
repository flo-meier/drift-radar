# Drift Radar · trigger worker

Cloudflare Worker that lets anyone (Drift Radar jury, readers, the product page)
kick off a `drift-radar-weekly` GitHub Action run without needing write access
to `flo-meier/drift-radar`.

## How it works

- `POST /dispatch` from the Drift Radar frontend
- In-memory rate limit: 1 request per 60 s per IP (best-effort across isolates)
- Forwards to `POST /repos/flo-meier/drift-radar/actions/workflows/drift-radar-weekly.yml/dispatches`
- Auth via a fine-grained PAT stored as the `GH_TOKEN` secret

## Deploy

```sh
cd workers/trigger
npx wrangler login           # one-time CF auth (opens browser)
npx wrangler secret put GH_TOKEN   # paste the fine-grained PAT, Return
npx wrangler deploy
```

Wrangler prints the live URL, e.g. `https://drift-radar-trigger.<account>.workers.dev`.
Paste that URL into the frontend in `src/data/trigger.json` (or hard-code
in the trigger-button wiring).

## Token scope

The `GH_TOKEN` PAT must be fine-grained and limited to:

- Repository: `flo-meier/drift-radar` only
- Permissions → Repository permissions → Actions: Read and write
- Nothing else

Revoke at any time on <https://github.com/settings/tokens>.

## Local dev

```sh
npx wrangler dev
# → http://127.0.0.1:8787/dispatch
```
