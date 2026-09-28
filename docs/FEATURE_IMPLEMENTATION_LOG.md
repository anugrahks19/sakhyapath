# SakhyaPath advanced feature implementation log

**Status:** Implemented as an optional local/owned-feed prototype on 28 September 2026. Government footage and Sentinel credentials were not supplied; Government integration, plate quality on Indian road footage, and production scale remain unverified. This file is the source for PPT claims and demo narration.

## 1. Search Proof receipt

**Why it matters.** A search result can be persuasive even when cameras were unavailable or frames were never analyzed. Search Proof freezes exactly what the system knew at the time of the search.

**Implemented flow.** An authenticated user creates a pursuit search, optionally runs sampling, then clicks **Create signed Search Proof**. `POST /api/v1/pursuits/{id}/proofs` snapshots the search filters, eligible cameras, health/PTS/generation, lifetime camera counters, schedule coverage-window deltas, matching records, model versions, evidence SHA-256 hashes, reviews, alerts and explicit gaps. The snapshot is canonical JSON signed with a persistent Ed25519 key. The PDF is rendered once, stored, SHA-256 hashed and independently signed. The private key stays server-side; `GET /api/v1/proofs/public-key` exposes only the public key. `GET /api/v1/proofs/{id}/verify` checks the stored JSON and PDF signatures. `scripts/verify_search_proof.py` independently checks exported files against a separately pinned public key. The receipt never includes stream URLs or image bytes.

**Truth rule.** Zero hits means no matching read in analyzed frames. It cannot establish absence from unsampled video, unavailable feeds, or a road. Lifetime counter snapshots are marked as such; only schedule-window deltas describe sampling in a window. The receipt is immutable, so a later review or changed evidence file requires a new receipt; the original signature verifies the original snapshot, not the current evidence state.

**Owned-feed demo.** Import one owned feed, start a pursuit, disconnect the feed, create a receipt, download JSON/PDF, run `python scripts/verify_search_proof.py receipt.json --public-key <trusted-key> --pdf receipt.pdf`. Alter one byte in either file and rerun to show failure. Show unavailable/insufficient windows in the PDF/JSON. An empty search is also a valid honesty demo.

**Verified.** The integration test checks JSON/PDF signatures, tampering, restart persistence, no source URL disclosure, and the unsampled-video warning.

**Production step.** Put signing keys in an approved KMS/HSM, pin public keys in the receiving system, timestamp and archive receipts under approved retention, and audit key rotation. For a very large grid, build signed regional manifest chunks and an aggregate root rather than rendering tens of thousands of camera rows into one PDF. Local PEM key storage and a single PDF are for the prototype.

**PPT claim.** “Every search can produce a signed receipt that proves what was analyzed and exposes coverage gaps.” Do not say it proves a vehicle was absent.

## 2. Regional query agents

**Why it matters.** A state-scale deployment should not centralize every raw stream. Each department or region can retain video and return only authorized hit metadata.

**Implemented flow.** A standalone `app.regional_main:app` process has its own database and token. `POST /v1/search` requires the regional token and a department contained in that agent's configured scope. It returns plate, camera, receive time, source PTS, stream generation, review status and evidence hash; no crop, source URL, or video. Central `POST /api/v1/federation/search` fans one plate query to configured agents with at most eight in flight and strips any unapproved fields from agent replies. Department sessions query only their own department; operator sessions may query all configured departments. Partial failures are listed, and `complete=false` prevents an incomplete grid search from looking conclusive. Agent URLs come only from admin configuration, not a user request. HTTPS is required outside loopback/local test.

**Owned-feed demo.** Run two agents with separate databases and departments. Add one owned test sighting to each. Operator search returns two metadata hits; department A search returns only A. Directly request department B from agent A and show HTTP 403. Stop one agent and show the central response marks that region incomplete.

**Verified.** A two-database integration test exercises the scoped fan-out, denial, and video-path exclusion.

**Production step.** Deploy regional workers near approved VMS infrastructure, provision mTLS/service identity and department policy centrally, and use PostgreSQL/PostGIS plus durable event infrastructure at pilot scale. The prototype uses configured bearer tokens and SQLite.

**PPT claim.** “SakhyaPath can search across separately operated regions while keeping video at its source.” Actual Government region integration has not been tested.

## 3. Shadow pursuit scheduler and exploration

**Why it matters.** An adaptive scheduler can focus on likely cameras yet miss unexpected turns. A side-by-side decision record makes that tradeoff visible.

**Implemented flow.** Every active schedule revision writes a `shadow_decisions` record. The applied adaptive policy and rotating uniform policy use the same measured FPS budget and camera slot count. The uniform result is a **counterfactual decision**, computed from the same ranking/capture state; it never starts another capture or claims a detection outcome. `GET /api/v1/pursuits/{id}/shadow` exposes decisions. An operator can enable one-slot exploration with `PUT /api/v1/pursuits/{id}/exploration?enabled=true`; on the next schedule revision, one lower-ranked eligible camera replaces the last selected camera while the original total FPS and worker cap remain enforced. The preference persists in SQLite. The existing equal-budget recorded replay script, `scripts/compare_recorded_sampling.py`, is the route to measured outcomes once annotated owned recordings are supplied.

**Owned-feed demo.** Start the measured pursuit on a small owned grid, open the shadow panel, show adaptive and uniform camera sets for the same revision. Enable exploration, trigger a new revision by a confirmed read or health change, and show one exploratory camera sampled without increasing total requested FPS or opening a second capture. Run the recorded replay comparison on multiple reset annotated routes to show both wins and losses; avoid an improvement claim without that replay.

**Verified.** Unit test checks rotation and equal budget. Existing Active Pursuit integration test covers scheduling, worker acknowledgement, revisions and coverage; the new shadow record is attached to each revision.

**Production step.** Validate camera transitions on permission-cleared footage; cap exploration by measured worker capacity and operational policy. Replace resolution/distance proxies only after measured plate readability and route evidence exist.

**PPT claim.** “One live capture supports auditable adaptive-versus-uniform decisions, and an optional exploration slot guards against unexpected routes.” Do not claim counterfactual hit improvement from decision logs alone.

## 4. Camera and clock trust scorecard

**Why it matters.** A connected catalogue entry is not necessarily decoded live, and PTS on different cameras is not automatically a shared UTC clock.

**Implemented flow.** `GET /api/v1/cameras/{id}/trust` combines current catalogue presence, decoded-frame freshness, codec/resolution, measured FPS, median/p95 PTS intervals from the active capture, PTS discontinuities, source PTS/timebase, stream generation, capture errors, recent health events, analysis queue age, worker state and a mapping for the **current** stream generation. The UI inspector displays readiness and clock limitations. The route only marks cross-camera travel-time calculation eligible for review when there is a fresh decoded frame, source PTS, and a current attested mapping with at most one second uncertainty. A restart/generation change invalidates the older mapping. This is an observed-telemetry scorecard, not a calibrated probability.

**Owned-feed demo.** Import H.264/H.265 owned streams, open each preview, show codec/PTS/FPS. Interrupt and restart a feed; show health events, capture errors and a new generation. Without an attested mapping, cross-camera time stays approximate. On an owned recording with a documented clock anchor, add the mapping and show eligibility change.

**Verified.** Integration test checks that a camera without shared UTC mapping blocks precise travel-time claims. Existing RTSP/HLS tests cover decode, PTS and reconnect.

**Production step.** Attest clock sources and uncertainty per gateway, monitor NTP/PTP drift, and reject travel-time conclusions if uncertainty is too high for the claim. The prototype's mapping is operator-attested for owned recordings only.

**PPT claim.** “The system knows when camera timing is not trustworthy and downgrades route claims.”

## 5. Low-connectivity regional mode

**Why it matters.** A regional WAN outage should not force video to a central server or silently discard permissible events.

**Implemented flow.** Each regional process scans its local sightings and feed-health events into an SQLite outbox in the same transaction as its cursor advance. Only strict `MetadataEvent` fields are allowed; attempts to send video URLs or extra fields get HTTP 422. Events include a stable ID for idempotent central ingestion. A five-second agent loop attempts `POST /api/v1/regions/{region_id}/events`, stops on failure, retains metadata, and retries after reconnection. Central inbox has a composite region/event primary key, so a repeated delivery acknowledges without duplicate storage. `GET /v1/outbox` shows pending/delivered counts and oldest pending time; central `GET /api/v1/regions/events` shows delivered gap/restored events and open reported gaps. A 10,000 pending-event cap fails closed and leaves scan cursors behind for later catch-up. Central cannot see undelivered events during a partition, so its UI says that remote outbox state is unknown.

**Owned-feed demo.** Run a regional agent and local owned feed, cut its connection to central, trigger a sighting and feed outage. Show outbox pending and central missing those events. Restore connection or invoke `POST /v1/flush`; show delivered count, central inbox count, a replayed duplicate acknowledged once, and the original gap event. Keep camera-local analysis bounded by the existing measured worker cap.

**Verified.** Integration test simulates failed send, durable queue, recovery, idempotent duplicate and rejection of a video URL field.

**Production step.** Replace the SQLite outbox with a monitored regional durable queue, enforce retention/encryption and backpressure policy, and run WAN partition/failover tests. A clear metadata queue never proves continuous video coverage.

**PPT claim.** “Regional agents continue bounded local analysis and reconcile permitted metadata after an outage, with explicit gap status.”

## Configuration and commands

Central: `SAKHYAPATH_REGIONS` is a JSON list of `{id,url,token,departments}`. Keep it in protected environment configuration. `SAKHYAPATH_PROOF_KEY_PATH` optionally sets the local Ed25519 PEM path; keep it outside web/static paths and back it up securely. Existing `SAKHYAPATH_OPERATOR_KEY` and department keys still apply.

Regional process: set `SAKHYAPATH_REGION_DB`, `SAKHYAPATH_REGION_ID`, `SAKHYAPATH_REGION_DEPARTMENTS` (comma-separated), `SAKHYAPATH_REGION_TOKEN`, and optionally `SAKHYAPATH_CENTRAL_URL` and `SAKHYAPATH_CENTRAL_TOKEN`; run `uvicorn app.regional_main:app --host 127.0.0.1 --port 8101` from `backend` in a trusted local setup. The central region token must match the regional token for this prototype. Do not expose this service directly to an untrusted network.

Verification: `python -m pytest -q tests/test_advanced_features.py`, `python -m pytest -q`, and `npm run build` in `frontend`. No supplied Government footage or Sentinel access was used in these tests.

If the browser at `127.0.0.1:8000` was opened before these changes, restart that existing backend process after saving its configuration. The frontend has been rebuilt, but a running Python process keeps its old route table. The startup command is in [Module 1 runbook](MODULE1_RUNBOOK.md); preserve the existing operator key and database path when restarting. Configure and start regional agents separately only when demonstrating federation or outage replay.

**Verified on 28 September 2026:** full backend suite **28 passed**, frontend production build passed, isolated HTTP and browser checks passed, and `git diff --check` reported no whitespace errors. The suite includes owned live RTSP/HLS tests and the new receipt/federation/outage/exploration boundary tests. The [integrated verification report](VERIFICATION_REPORT_2026-09-28.md) records the exact checks and the older server still running on port 8000. It does not include a Government-feed test or an Indian-road holdout score.

## Slide order

1. Problem: a large heterogeneous grid, uncertain timing, uncertain coverage.
2. Architecture: central map and policy + independent regional agents + local video.
3. Search Proof: signed JSON/PDF and tamper demonstration.
4. Shadow scheduler: equal-budget decisions and exploration, including known losses.
5. Trust scorecard: PTS versus shared UTC and blocked overclaims.
6. Outage mode: queue, reconnection, idempotent replay and visible gaps.
7. Validation: exact test counts and owned-feed labels; Government live test pending organiser access.
8. Pilot path: regional identity, PostgreSQL/PostGIS, encrypted evidence, durable events, KMS, multi-feed latency and holdout accuracy.
