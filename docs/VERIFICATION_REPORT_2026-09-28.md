# SakhyaPath integrated verification report

**Date:** 28 September 2026  
**Scope:** Existing Modules 1-4 plus five advanced features, on a local owned/synthetic test setup.  
**Verdict:** Locally integrated and passing the checks below. Government integration, Indian-road recognition quality, and production scale are still unverified.

## Checks performed

| Check | Result | Meaning and boundary |
| --- | --- | --- |
| Complete backend suite, `python -m pytest -q` | **28 passed** | Covers camera ingest, live owned RTSP/HLS decode, registry, ANPR/alerts, journey/review, pursuit/coverage, and advanced features. This is local evidence only. |
| Frontend, `npm run build` in `frontend` | **Passed** | Production bundle built after the federation wording correction. |
| Fresh server HTTP smoke, `scripts/verify_runtime.py` | **Passed** | Health/static, auth and CSRF, registry/trust, pursuit/journey, shadow, Search Proof JSON/PDF, unconfigured federation, regional view, and logout. Used an isolated disposable database and key. |
| Existing database migration, `scripts/verify_existing_db_migration.py` | **Passed** | Backed up the current local SQLite database, migrated the copy, checked integrity/new tables and preserved two cameras and two pursuits. Source database was untouched. |
| Browser on isolated fresh server | **Passed for inspected flows** | Imported an owned replay camera, inspected trust, made a journey, created a signed receipt, queried unconfigured federation, and toggled exploration. The corrected UI says no permitted agents are configured. This was not an end-to-end Government or accuracy test. |
| `git diff --check` | **Passed** | No whitespace errors; Git printed line-ending warnings on some Windows files. |

## Feature-by-feature result

| Feature | Verified locally | Remaining validation |
| --- | --- | --- |
| Module 1 registry, GIS, ingest | Persisted registry/map data, stubbed Sentinel read-only catalogue changes, owned RTSP/HLS, PTS, H.264/H.265, reconnect and preview. | Authorised `GET /api/ingest`, actual Government codecs/network, count of discovered/connected/viewed/analyzed feeds. |
| Module 2 ANPR and alerts | Actual decoded owned stream and model sample through sighting/evidence, representative watchlist alert, deduplication and access checks. | Permission-cleared Indian-road holdout or organiser private score: exact plate accuracy, misses, false reads, latency distribution. |
| Module 3 journey/report | Historical search, evidence links, review corrections, PDF and timing limitations. | Real multi-camera target route with a trustworthy shared UTC mapping before precise travel times. |
| Module 4 pursuit/ledger | Measured budget, deterministic revisions, applied-rate acknowledgement and four coverage states. | Fair repeated route comparison on annotated recordings; 50-feed authorised pilot and production failover. |
| Search Proof | JSON/PDF signatures, tamper failure, persisted signing key, restart and coverage-gap language. | KMS/HSM key handling, external public-key pinning, timestamp/archive policy, large-grid receipt design. |
| Regional query agents | Two isolated databases and department scopes, denied cross-department request, metadata-only fan-out, partial failure. Empty configuration now returns `complete=false`. | Separate networked regional deployments, mTLS/service identity, policy audit and load test. |
| Shadow scheduler | Equal-budget adaptive/uniform decisions, no second capture, one-slot exploration persisted and shown in UI. | Measured comparative *outcomes* on several reset annotated routes; current shadow records decisions only. |
| Camera/clock trust | Owned live RTSP PTS interval telemetry, decode and queue indicators, generation-aware UTC mapping gate; UI blocks precise timing when unverified. | Source-side clock attestation and drift monitoring on authorised cameras. |
| Regional outage mode | Durable SQLite outbox, automatic retry after simulated outage, deduplicated central replay, persistence across restart, strict metadata schema. | Two-process WAN partition drill, encrypted durable queue, capacity/backpressure and failover operations. |

## Important operational finding

The user's existing server at `http://127.0.0.1:8000` is still an older Python process: its health endpoint responds, but the newly added `/api/v1/proofs/public-key` endpoint returns 404. A newly started isolated server served the new endpoints and passed HTTP/browser checks. Restart the existing port-8000 backend **with its current operator key, database path, and any other environment settings preserved** before judging the current browser session or demo. The frontend build alone cannot refresh Python routes in an already-running process. No existing process or live data was reset during verification.

## Repeatable commands

```powershell
.\.venv\Scripts\python -m pytest -q
npm run build --prefix frontend
.\.venv\Scripts\python scripts/verify_existing_db_migration.py
```

For the HTTP smoke, start a **fresh isolated server** with a disposable test database and operator key, then run `scripts/verify_runtime.py --allow-test-data --base-url http://127.0.0.1:<test-port>`. The script refuses to run without its explicit test-data flag. See its `--help` before use. Do not point it at an operational database.

## Evidence and claim discipline

- The available tests establish local function and integration behavior, not a guaranteed hackathon result.
- Government footage is held by the organiser; no Government recording was supplied or required for these local checks.
- A zero-hit Search Proof means no match in the analyzed frames. It says nothing about unsampled or unavailable video.
- Source PTS is per-stream media timing. Precise cross-camera timing requires separately verified UTC mapping.
- The current laptop/SQLite/single-process prototype is not a completed statewide deployment. Use [the HLD](MODULE4_HLD.md) and [production gate](PRODUCTION_GATE.md) for the staged pilot path.
