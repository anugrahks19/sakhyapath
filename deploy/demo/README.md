# Host the SakhyaPath prototype for judges

This is a **private, single-VM demo** recipe for the current FastAPI/React/SQLite prototype. It is not the [Government production architecture](../../docs/PRODUCTION_GATE.md). The submission link points to the running application. The organiser's private CCTV should only be used inside the authorised network and under its recording/evidence rules; use owned or permission-cleared feeds for a public hackathon demo.

If you prefer the React frontend on **Vercel** while this VM runs the backend, follow the [Vercel + Oracle VM guide](VERCEL_ORACLE.md) after preparing the VM service. The Oracle-only URL remains the fallback if the Vercel proxy fails any live acceptance check.

## The hosting choice

Use an Ubuntu 24.04 VM with a persistent disk and a domain name. A CPU VM can show the grid and non-intensive flows, but measure actual inference before promising live ALPR. Choose a compatible NVIDIA GPU VM if the submission must process live plates continuously. **The feed source must be reachable from the VM.** `rtsp://127.0.0.1/...` on your laptop will not be reachable from the cloud. Publish an owned replay to an approved, VM-reachable source or put the VM on the same permitted network.

**Check an existing Oracle Free Tier VM before deploying.** Run `uname -m`, `free -h`, and `nproc`. Oracle's Always Free AMD micro shape has only **1 GB RAM**; the measured local two-feed SakhyaPath run recorded about **1 GB peak backend RAM alone**, so a 1 GB VM is not a credible full live-ANPR host. The Ampere A1 allowance can provide more memory but requires a separate ARM dependency check. Oracle also states that idle Always Free compute **may be reclaimed**. For a strict 24/7 submission link, use a paid persistent VM or paid always-on service with sufficient measured memory, and keep a backup and monitored health check. [Oracle Always Free details](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) and [local benchmark](../../output/benchmarks/module4_owned_pipeline.json) provide the basis for this gate.

The app's frontend is already served by FastAPI after `npm run build --prefix frontend`; do not deploy the frontend alone. Run **one Uvicorn worker**: prototype sessions, capture workers and scheduling are process-local. Bind it to `127.0.0.1:8000`; let Caddy handle public HTTPS and an extra judges-only password.

## 1. Transfer a clean source revision

The workspace may contain uncommitted changes and does not yet have a remote. Commit the tested source to a **private** repository that you control, or transfer a source bundle. Do not upload `.env`, `backend/data/`, camera URLs, footage, evidence, model caches or signing keys. The existing `.gitignore` excludes `backend/data/`, `frontend/dist/`, `.venv/` and `.env`; review `git status` and the exact commit before sharing. A fresh checkout will have no demo camera or sighting data until you add an owned source.

Use `/opt/sakhyapath` as the checkout path in the templates. Create a dedicated Linux account named `sakhyapath`, make the checkout readable by that account, and create `/var/lib/sakhyapath` owned by it with restricted access. Keep the OS and Python/Node runtimes updated according to the VM provider's standard process.

## 2. Install and build

Install Python 3.12, Node 24, FFmpeg, Git and Caddy on the VM. Install Caddy from its [official Ubuntu instructions](https://caddyserver.com/docs/install). From `/opt/sakhyapath`, as the `sakhyapath` user:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-cpu.txt
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m pytest -q
```

For a GPU VM with installed compatible NVIDIA drivers and CUDA runtime, use `backend/requirements-gpu.txt` **instead of** `backend/requirements-cpu.txt`, then verify that the app reports the actual GPU provider. Do not install both ONNX Runtime variants in the same environment. On the first inference, model files may be fetched into the configured models directory; warm and verify this cache before the judge demo.

## 3. Put secrets and data on the persistent disk

Copy `deploy/demo/demo.env.example` to `/etc/sakhyapath/demo.env`, replace the operator-key placeholder with a long random key and set file mode `0600`. Create `/var/lib/sakhyapath` and its evidence/models subdirectories owned by the service user. The database, evidence and Ed25519 proof key must persist together; back them up together. Keep this environment file out of Git and never paste the key into a screenshot or slide.

Set `SAKHYAPATH_COOKIE_SECURE=1` for HTTPS. Leave the Sentinel values absent until the organiser supplies the authorised origin, authentication and network rules. Never attach private Government footage to this public demo without explicit approval. The current camera import accepts server-reachable RTSP/HLS URLs from a signed-in operator, so the outer judges-only gate and a strong app key are important on an internet-facing prototype.

## 4. Install the single-process service

Copy `deploy/demo/sakhyapath.service` to `/etc/systemd/system/sakhyapath.service`. Its fixed paths assume the checkout and data locations above. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sakhyapath
systemctl status sakhyapath
curl http://127.0.0.1:8000/api/v1/health
```

The local health endpoint should return JSON with `"status":"ok"`. If startup fails, inspect `journalctl -u sakhyapath -n 100 --no-pager`. The backend intentionally does not bind to a public network interface. Uvicorn's proxy-header settings trust only the local reverse proxy.

## 5. Add domain, HTTPS and judges-only access

Create a DNS A/AAAA record for your domain pointing to the VM and allow inbound ports 80 and 443 to Caddy. Keep port 8000 closed externally. Run `caddy hash-password` **without a plaintext command-line argument** so it prompts privately, then replace `REPLACE_WITH_CADDY_HASH` and the hostname in `deploy/demo/Caddyfile.example`. Install it as `/etc/caddy/Caddyfile`, validate it, and reload Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy can provision HTTPS when the domain points to the server and ports 80/443 are reachable. The outer username/password protects the entire site; SakhyaPath's operator key is a second, separate sign-in. Share both with the intended judges through the submission's approved private channel. Test the public URL from a different device/network. [Caddy HTTPS](https://caddyserver.com/docs/quick-starts/https) and [basic authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth) document this setup.

## 6. Make the demo real and repeatable

1. Open the HTTPS URL and pass the outer gate, then sign into SakhyaPath.
2. Import one owned, VM-reachable RTSP/HLS source; show that the map marker turns online only after a decoded frame.
3. Warm the recognizer and create a real sighting/representative alert from an owned plate sample. The first model download and inference can otherwise delay the demo.
4. Create a historical search, inspect Evidence Journey, Active Pursuit, coverage, trust and a signed Search Proof.
5. Restart the service and confirm cameras, sightings, evidence, proof verification and the frontend still work.
6. Record the separate 2-3 minute own-feed operational video using the [shot list](../../docs/DEMO_AND_LINK_CHECKLIST.md). Open the final link from an incognito window and check its permissions.

If the VM cannot reach a live owned camera, host a permission-cleared replay source that the VM can reach. Do not substitute hard-coded sightings for the frame-to-alert demo. A live hosted app plus a recorded own-feed video gives judges a link to inspect and evidence that recognition actually ran.

## Submission and rollback

Submit the HTTPS URL, temporary judge access instructions via an approved private channel, the own-feed video link, the code link, pitch deck and HLD. State that the hosted link is an **owned-feed prototype**; Government live evaluation remains with the organiser. Keep the previous tested commit available. If a deployment fails, restore that commit and the matching data backup; do not replace the proof signing key or evidence files independently.

## When a single VM is insufficient

This recipe is for a hackathon demo. The current app has SQLite, local evidence, memory sessions/capture, one active pursuit and a default four-analysis-camera cap. Multiple Uvicorn workers or replicas would not share that state correctly. A Government pilot needs the regional architecture, approved identity, PostgreSQL/PostGIS, durable events, encrypted evidence and secrets, measured multi-feed capacity, and restore/failover tests in the [production gate](../../docs/PRODUCTION_GATE.md).
