# Vercel frontend + Oracle VM backend for the judges' demo

This is an **optional split deployment** for SakhyaPath. Vercel hosts the compiled React/Vite frontend. Your existing Oracle VM runs FastAPI, SQLite, evidence, model inference and RTSP/HLS capture. Vercel proxies the browser's `/api/...` requests to the Oracle VM, so the app can keep its same-origin cookie and relative API paths. Vercel's [external rewrites](https://vercel.com/docs/routing/rewrites) support this topology, but the complete login, cookie, server-sent event and image-preview flow must be tested on the actual deployed URLs before submission.

**Simpler alternative:** the Oracle VM can serve **both** frontend and backend at one URL after `npm run build --prefix frontend`, using the [single-VM guide](README.md). That avoids a second deployment and is the safest fallback if Vercel's proxy affects live alerts or cookies.

## 1. Check the Oracle VM

SSH into the VM and run `uname -m` and `python3 --version`. `x86_64` is an x86 VM; `aarch64` is ARM/Ampere. Do not assume a GPU: run `nvidia-smi`; if it is absent, use the CPU requirements and measure whether one-feed inference is responsive enough for a demo. Install the app following the [single-VM guide](README.md) through its systemd service step. Use a persistent disk for the SQLite database, evidence, model cache and Search Proof signing key.

Also run `free -h` and `nproc`. An Oracle Always Free AMD micro VM has 1 GB RAM, less than a safe margin for this project's measured local inference process. Vercel hosting the UI does **not** remove the model, decoder or SQLite memory load from Oracle. Oracle may reclaim idle Always Free compute, so a strict 24/7 promise needs a paid always-on host and monitoring. [Oracle's current limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) explain this.

The VM must be able to reach its **owned** RTSP/HLS source. A feed on your Windows laptop's `127.0.0.1` cannot be opened from Oracle. Government streams should stay in the organiser-approved network; do not route them through a public demo just to get a submission link.

## 2. Give Oracle a public HTTPS API origin

Point an `api.example.com` DNS record at the Oracle VM. Install Caddy using its [official Ubuntu instructions](https://caddyserver.com/docs/install) and adapt [`Caddyfile.example`](Caddyfile.example): replace `demo.example.com` with `api.example.com`. Keep its `basic_auth` gate and proxy to `127.0.0.1:8000`. Generate a strong separate Basic password and its Caddy hash with interactive `caddy hash-password`; avoid typing the password in a command argument or repository file. Open inbound TCP 80/443 in both the VM OS firewall and Oracle's network security rules; keep TCP 8000 closed externally. Caddy obtains HTTPS when DNS and ports are correct. [Caddy's HTTPS guide](https://caddyserver.com/docs/quick-starts/https) covers these conditions.

Verify the origin from **outside** the VM: `https://api.example.com/api/v1/health` should require Basic authentication; after providing it, it should return `status: ok`. Never put the SakhyaPath operator key or Sentinel credentials in the Caddyfile.

## 3. Prepare the two Vercel environment variables

The frontend includes [`frontend/vercel.mjs`](../../frontend/vercel.mjs), a programmatic Vercel configuration. It reads:

- `SAKHYAPATH_BACKEND_ORIGIN`: `https://api.example.com` with no path or trailing credentials.
- `SAKHYAPATH_BACKEND_BASIC_B64`: Base64 encoding of the **Caddy Basic username and plaintext password**, e.g. `judge:<password>`. This is a secret. Set it in Vercel's project environment settings; do not prefix it with `VITE_`, commit it, print it in logs or share it with judges. Generate it locally from an interactive prompt, and paste only into the Vercel secret setting.

For example, on your own machine, an interactive Python prompt can produce that Base64 value without placing the plaintext password in shell history:

```bash
python3 -c 'import base64,getpass; print(base64.b64encode(("judge:"+getpass.getpass("Oracle Basic password: ")).encode()).decode())'
```

Treat the printed Base64 value as a password. The plaintext password entered here must be the same one whose **hash** you installed in Oracle Caddy's `basic_auth` block.

The configuration uses Vercel's `deploymentEnv` helper to insert this Basic credential into server-side proxy requests; it is not bundled into browser JavaScript. It rewrites `/api/(.*)` to the Oracle API before the SPA fallback. The Oracle Caddy Basic gate therefore remains in place even though judges visit the Vercel URL. Keep the SakhyaPath operator key separate; that is the app's own sign-in after the proxy.

## 4. Deploy the frontend project

Commit the current tested source to a **private repository you control**. Import that repository into Vercel as a new project. Select **Root Directory: `frontend`**, framework preset **Vite**, build command `npm run build`, and output directory `dist`. Add both environment variables above to the Production environment. Then deploy. Vercel documents both [Vite deployment](https://vercel.com/docs/frameworks/frontend/vite) and [root-directory/build settings](https://vercel.com/docs/builds/configure-a-build).

Protect preview deployments or give them a separate disposable backend; otherwise a preview UI could query the same prototype database. The `vercel.mjs` build fails early when the backend origin is missing or is not a clean HTTPS origin. Do not submit the Vercel URL until the next section passes.

## 5. End-to-end acceptance on the actual Vercel URL

In a private browser window, verify all of these through `https://<your-vercel-domain>`:

1. Open the page and sign in with the SakhyaPath operator key. Browser Developer Tools should show `/api/v1/auth/login` on the **Vercel hostname** and a `sakhyapath_session` cookie for that host. Reload and confirm `/api/v1/auth/me` stays authenticated.
2. Import an owned VM-reachable camera. Confirm map/list data persists after a browser and backend restart.
3. Open the preview. Check that `/api/v1/cameras/<id>/snapshot.jpg` shows a **fresh decoded frame** with PTS/generation headers and that no source credentials appear in browser requests.
4. Create a watchlist entry and trigger a real owned-feed read. Verify `GET /api/v1/alerts/stream` delivers live events through the Vercel rewrite. If the event stream fails, use the Oracle-only single-domain deployment for the submission instead of claiming live alerting works through Vercel.
5. Search a plate, inspect Journey/Active Pursuit, create a signed Search Proof, and download both JSON and PDF through the Vercel URL. Verify the files independently.
6. Stop and restart the Oracle backend. The Vercel UI should recover; database, evidence and signing key must still be present. Confirm the backend API remains Basic-protected when called directly.

Run the [submission link checklist](../../docs/DEMO_AND_LINK_CHECKLIST.md) before sending judges the URL. The Vercel URL is the shareable prototype entry point; the Oracle API domain and Basic credentials remain team infrastructure, and no Government footage should be exposed by this demo.

## Limits and fallback

This topology keeps the current **one-process** FastAPI/SQLite backend. It does not make inference serverless or turn the Oracle VM into a GPU. Vercel is hosting static files and proxying API calls; video decoding, inference, evidence and state still live on Oracle. Session cookies and server-sent events are expected to pass through the rewrite but are **unverified until the live acceptance test above**. If any critical path fails, serve the built React frontend directly from FastAPI on Oracle through Caddy and submit that single HTTPS URL.
