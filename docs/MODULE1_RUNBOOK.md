# Module 1 runbook and verification record

## Status

This is a working local Camera Grid implementation. It covers the registry, authenticated API/UI, Sentinel catalogue adapter, RTSP-over-TCP/HLS capture, source PTS, health history, and server-managed browser preview. **No Sentinel host, credentials, or Government footage were supplied to this workspace**, so the Government-feed integration gate remains unverified. Do not describe a catalogue stub or owned test stream as a Government feed.

## Install and start on Windows

Use Python 3.12+, Node 24+ (or a supported current Node version), FFmpeg, and a browser. In two PowerShell terminals from the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements-cpu.txt
$env:SAKHYAPATH_OPERATOR_KEY = 'replace-with-a-long-random-local-key'
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`, sign in with the operator key, then import an owned RTSP/HLS URL or sync an authorised Sentinel catalogue. The UI is proxied through Vite in development. For a single local server, run `npm run build --prefix frontend` before starting the backend and open `http://127.0.0.1:8000`; FastAPI serves the built frontend. The backend stores data in `backend/data/sakhyapath.sqlite3` by default. That directory is ignored by Git. Use one backend worker; live capture subscriptions and prototype sessions are held in that process.

For authorised Sentinel access, set the actual **origin** in `SAKHYAPATH_SENTINEL_BASE_URL` and, if required, the full `Authorization` header in `SAKHYAPATH_SENTINEL_AUTHORIZATION`. The adapter makes only `GET <origin>/api/ingest`, consumes URLs returned by that response, and never calls Sentinel's control API or publishes to it. The supplied reference does not provide a real origin or authentication scheme, so these settings must come from the organisers.

### Obtaining Sentinel sandbox access

The [official Gujarat Informatics Limited website](https://gil.gujarat.gov.in/index) links to the [Sentinel Gujarat hackathon portal](https://sentinel.gujarat.gov.in/). The supplied hackathon brief (indexed at `hackathon_source_index/GUJtxt_lines.tsv`, line 373) says that after registration, participants can access the challenge details, resources, and approximately 50 geographically distributed live camera feeds on the portal's **Resources** page. Sign in with the account used for the application, complete any account verification the portal requests, and check that page and any team/application dashboard. If you already completed the Google submission form but the Resources page is absent or restricted, use the portal's own help/contact channel to request sandbox enablement. Provide your registered email, team/application ID, and a screenshot of the access message; ask for the authorised catalogue origin, authentication method, feed-use rules, and whether your network needs allowlisting. Do not send a password, token, or stream URL in a public issue or chat.

The portal was not reachable from this development environment on 28 September 2026, so its live UI, current enrolment status, and support contact details have not been independently verified. Do not assume that the submitted Google form itself grants feed access. Once access is granted, put the supplied settings in **local environment variables** and run the Sentinel sync from the signed-in dashboard. Record the returned catalogue count, then view one authorised H.264 and one H.265 feed if both are present; capture the health, PTS, and browser preview evidence. Keep the Government integration checklist item below open until that test is actually performed.

### Owned RTSP test fixture

For a repeatable local feed, install the verified MediaMTX binary with `powershell -ExecutionPolicy Bypass -File scripts/get-mediamtx.ps1`. This downloads and checks the official [MediaMTX release](https://github.com/bluenviron/mediamtx/releases/tag/v1.21.1). The binary is stored in ignored `backend/data/tools/`. The integration test creates a loopback-only MediaMTX configuration and uses FFmpeg to publish an owned test pattern; it does not connect to Sentinel. Run:

```powershell
python -m pytest -q
npm run build --prefix frontend
```

The RTSP integration test is skipped if the local MediaMTX binary is absent. The test checks H.264 and H.265, PTS delivery, one upstream capture shared by multiple consumers, disconnect detection, and reconnect. The HLS test creates actual media segments, serves them from localhost, and verifies a decoded authenticated JPEG with PTS. The catalogue tests exercise changed/removed IDs and verify server responses do not reveal stream URLs.

## API and data meaning

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Backend liveness. |
| `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` | Local operator session. Cookie is HttpOnly/SameSite Strict; write requests require CSRF header. |
| `POST /api/v1/cameras/import` | Add owned live/replay RTSP/HLS sources only; Government cameras come from the catalogue. |
| `POST /api/v1/cameras/sync-sentinel` | Read-only catalogue fetch and registry reconciliation. |
| `GET /api/v1/cameras`, `GET /api/v1/cameras/{id}` | Public metadata within the authenticated app; source URLs excluded. |
| `GET /api/v1/cameras/{id}/health` | Verified decode status, last-frame diagnostic UTC, source PTS/time base, measured PTS rate, reconnect generation, and health history. |
| `GET /api/v1/cameras/{id}/snapshot.jpg` | One authenticated JPEG; response headers carry camera ID, source PTS, time base, and stream generation. Stale frames are rejected. |
| Browser preview | Polls the authenticated `snapshot.jpg` endpoint while open. Requests share one server-side capture per camera; closing the viewer stops requests and closes idle capture. |
| `GET /api/v1/metrics` | Registered, Sentinel listed, decoded online, connected, viewed, and concurrently analyzed counts. Analysis begins only when its Module 2 sampler is started. |

`catalogue_live` is a claim in the returned catalogue. `health_status=online` means this backend has decoded a recent frame. `last_frame_utc` is for operational health, **not** a media event timestamp. Tracking and subsequent analytics must use `source_pts`/`pts_timebase`, resetting at a new stream generation or a suspected hard scene cut. Sentinel's per-stream PTS alone does not establish a common UTC clock across cameras.

## Local acceptance checklist

- [x] Registry survives backend restart; stale catalogue cameras are marked absent/offline; changed camera properties/URLs trigger capture restart.
- [x] Owned HLS segments decode to an authenticated JPEG with source PTS.
- [x] Owned RTSP/H.264 and RTSP/H.265 streams decode over TCP with PTS.
- [x] Feed interruption produces degraded/offline and recovery returns to online with a new stream generation.
- [x] Two consumers share one upstream worker; browser does not receive source URLs in camera metadata.
- [x] React UI builds with a GIS map, feed list, health history, and authorised preview.
- [x] Browser import, map marker, decoded preview, source PTS, and viewer count returning to zero were visually checked using an owned HLS fixture.
- [ ] Connect to the actual Sentinel `GET /api/ingest` and record discovered, connected, viewed, and analyzed counts when access is supplied.

Latest local verification: `python -m pytest -q` passed **8 tests** (catalogue/registry/auth, real HLS including RTSP fallback, real RTSP H.264/H.265 and reconnect); `npm run build --prefix frontend` succeeded. The test fixtures are owned synthetic video. These results do not establish Government-feed compatibility.

## Scope and production limits

The prototype uses one local operator key, an in-memory session store, SQLite, and a process-local capture manager. For a Government deployment, replace this with department-scoped identity, TLS, encrypted secret storage, Postgres/PostGIS, controlled regional workers, capacity limits, monitoring/alerts, and approved retention policies. Stream URLs in the SQLite database are **server-side but not encrypted at rest**; protect that file and do not populate it with sensitive sources in an uncontrolled environment. The default browser map requests OpenStreetMap tiles; set `VITE_MAP_TILE_URL` to an approved/self-hosted tile service for an isolated deployment.
