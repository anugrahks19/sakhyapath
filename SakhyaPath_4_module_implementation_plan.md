# SakhyaPath: four-module implementation and acceptance plan

**Status (28 September 2026):** Modules 1–4 are implemented as an integrated **local prototype** and the owned-feed tests pass. The real Sentinel catalogue/feed gate, Indian-plate holdout, clock-aligned multi-camera route evaluation, submission recordings, and production acceptance remain pending. A green hackathon module requires the stated evidence, not merely code that compiles or a convincing UI. See the [submission readiness checklist](docs/SUBMISSION_READINESS.md) and module runbooks for current proof and open gates.

**Source of truth:** [hackathon brief index](hackathon_source_index/README.md), [Sentinel sandbox index](sentinel_source_index/README.md), and [technical blueprint](SakhyaPath_technical_blueprint.md). The user's pasted copy of the blueprint was checked against the current workspace document. The Sentinel rules in the index govern Sentinel access, including read-only catalogue discovery, live consumption, PTS timing, and no calls to its control API.

## Build path and ownership

```text
Module 1: Camera grid + GIS + live-feed adapter
       ↓ verified frames and camera metadata
Module 2: ANPR + evidence + representative watchlist alerts
       ↓ verified sightings
Module 3: Cross-camera journey + search + evidence report
       ↓ verified pursuit context
Module 4: Active Pursuit + Coverage Integrity Ledger + deployment proof
```

With two builders, work inside each module can run in parallel, but its integration gate is shared. Builder A owns ingest/vision/scheduling; Builder B owns registry/API/UI/reporting. Neither should independently redefine camera IDs, timestamps, plate normalization, or event schemas. An owned, consented multi-camera scenario is the deterministic development fixture; the Sentinel feed remains a live integration test, not a downloadable file or a mock. Where authorised live access is absent, record the Government-feed gate as **pending**.

### Common event contract (freeze before implementation)

```text
Camera: camera_id, source_system, source_type, department, location,
        codec/resolution when known, live_status, health_status, last_frame_utc,
        stream URL reference (server-only), catalogue_seen_utc
Frame: camera_id, source_pts, pts_timebase, captured_utc_if_verified,
       receive_utc_for_diagnostics, stream_generation, decode_status
Sighting: sighting_id, camera_id, source_mode, source_pts, event_utc_if_verified,
          timestamp_provenance, timestamp_uncertainty, plate_raw,
          plate_normalized, detector_score, ocr_score, model_version,
          evidence_ref, evidence_sha256, review_status
Alert: alert_id, sighting_id, watchlist_entry_id, match_basis, status,
       created_utc, acknowledgement_actor_and_time
Coverage: pursuit_id, camera_id, window_start/end_and_timebase,
          planned_frames, received_frames, analyzed_frames, health,
          decode_errors, result_code, reason
```

Use stable internal IDs, UTC for verified absolute timestamps, and explicit timestamp provenance. Source PTS is a media timebase, not automatically a common UTC clock. A new stream generation begins after reconnect/loop cut. Keep source URLs and credentials server-side. Give every API response a versioned shape; persist schema migrations rather than relying on an untracked local database.

### Shared definition of done for **every** module

- [ ] It starts from a documented clean checkout with pinned dependencies and no hidden manual step.
- [ ] Its API and UI show the **same persisted data** after process restart; no hard-coded demo result masquerades as detection.
- [ ] A normal path and at least one relevant failure path are demonstrated on real services or controlled owned footage.
- [ ] Logs contain camera/event IDs and errors but no credentials or unrestricted stream links.
- [ ] An operator can tell what is live, replayed, inferred, unavailable, or unverified.
- [ ] A short evidence packet is saved: command/configuration, source type, input/expected result, actual output or screen recording, logs, observed latency/throughput when relevant, and known limitations.
- [ ] Builder A and Builder B reproduce the integration gate on the same commit. A demo seen once on one developer's machine is not a completion gate.

## Module 1 — Camera grid, registry, GIS, and live-feed adapter

**Purpose:** fulfill mandatory Model 1 and establish a truthful, heterogeneous live feed that later modules can use.

**Build:**

1. Create FastAPI backend, versioned API, SQLite schema/migration, React shell, configuration and health endpoint. Keep an adapter interface for source discovery, connect/disconnect, frame/PTS delivery, and health.
2. Implement camera import/list/detail and a Leaflet map with department, location, source type, connectivity, and analytics status. Imported metadata is **not** labelled online until a decoded frame passes the health check.
3. Implement Sentinel read-only `GET /api/ingest` catalogue adapter. Refresh IDs, location, codec, resolution, bitrate, live status, and URLs returned by the catalogue; handle removed/changed cameras. Never infer URLs from a numeric ID template. Do not use Sentinel's control API or publish to the gateway.
4. Implement RTSP-over-TCP capture and HLS fallback. Retain source PTS; do not calculate timing from reported FPS or arrival time. Handle variable frame intervals, H.264/H.265, decoder warm-up, reconnect with bounded exponential backoff (~2–30 s), and loop discontinuities. Open only feeds being viewed/analyzed; close idle captures. If using our own MediaMTX relay, confirm it does not multiply upstream connections or erase timestamp provenance.
5. Provide an authorised browser preview via a server-controlled path or permitted relay. Keep source credentials and raw Government stream URLs out of the public frontend. Show live/replay label and health history.

**Module interfaces:** `GET /api/v1/health`, `GET /api/v1/cameras`, `POST /api/v1/cameras/import`, `POST /api/v1/cameras/sync-sentinel`, `GET /api/v1/cameras/{id}`, `GET /api/v1/cameras/{id}/health`, and a controlled preview endpoint. Module 2 receives `(camera_id, decoded_frame, source_pts, timebase, stream_generation, source_mode)` plus health events.

**Required tests:**

- Import a controlled camera list, restart backend, and find the same positions/statuses on both API and map.
- Connect to one owned RTSP feed and one HLS feed (or two distinct authorised source types). Show decoded frames, measured arrival/frame rates, and source PTS. A local test stream is labelled owned/replay, never Government live.
- Stub the catalogue with changed ID, codec, live status, and removed camera; verify the registry updates without making up URLs or leaving stale cameras “online.” When Sentinel access exists, repeat against the real read-only catalogue and record the count discovered.
- Interrupt and restore one feed. Status moves online → unavailable/degraded → online; backoff prevents a tight reconnect loop. Join-time decoder warnings do not kill the feed before a reasonable warm-up. Mixed H.264/H.265 and resolution changes are either decoded or surfaced as explicit errors.
- Inspect a browser network trace: no embedded credentials or unrestricted source URL. Show that closing the viewer/sampler closes unused captures.

**Module 1 is finished when:** a real frame from each required source type reaches the backend and browser with correct camera identity and PTS; the registry/map survives restart; the failure tests above pass; and the Sentinel catalogue is used as designed if credentials/network access have been provided. Record discovered, connected, viewed, and concurrently analyzed counts separately. **No access to Sentinel means local module completion only, not Government integration completion.**

**Likely files:** `backend/app/ingest/`, `backend/app/api/cameras.py`, `backend/app/storage/`, `frontend/src/cameras/`, `frontend/src/map/`, `tests/ingest/`.

## Module 2 — ANPR, evidence, watchlist, and live alerts

**Purpose:** turn actual frames into traceable plate sightings and automatic alerts from a representative watchlist.

**Build:**

1. Measure GPU and decoding throughput on the RTX 4060 laptop, pin a tested FastALPR detector/OCR pair, and expose whether inference runs on GPU or falls back to CPU. Validate the models against Indian plate sizes, angles, and lighting present in test footage.
2. Add a bounded, latest-frame queue and a configured baseline sampling rate. Preserve the source PTS and stream generation with every selected frame. Record frames received, selected, analyzed, dropped, and model latency. Avoid hidden backlog.
3. Detect and OCR plates. Normalize text conservatively, fuse repeated readings across a short time window, retain raw readings/confidences, and save the best evidence crop/short permissible clip with SHA-256. Avoid duplicate sightings from the same stationary vehicle.
4. Create representative watchlist CRUD with expiry/disable, exact high-confidence match, alert creation, acknowledgement, and operator-visible live delivery. Ambiguous OCR (such as O/0) is a review candidate, not a confirmed law-enforcement alert. Persist all records before sending live notifications.
5. Expose sightings search and the evidence/alert view through role-checked APIs. Source-system URLs and local storage paths never appear in an unauthorised response. Do not claim integration with police databases.

**Module interfaces:** `GET /api/v1/sightings?plate=...`, `GET /api/v1/sightings/{id}`, watchlist create/list/disable, `GET /api/v1/alerts/stream` (WebSocket or server-sent events), `POST /api/v1/alerts/{id}/acknowledge`. Emit `SightingCreated`, `AlertCreated`, and frame/analysis counters from the common contract. Module 3 consumes persisted sightings, not transient UI messages.

**Required tests:**

- Run an owned clip/feed with an annotated visible plate. The raw frame produces a persisted sighting whose camera, PTS, plate text, scores, model version, and evidence hash are inspectable; after restart it remains searchable.
- Put that plate on a representative watchlist. One qualifying encounter creates one alert, which appears live and remains after browser reload. A nonmatching plate creates no confirmed alert. Repeated frames from the same encounter do not flood alerts.
- Run difficult/ambiguous frames and verify they are review candidates or rejected, with no false certainty. Verify alert expiry/disable and acknowledgement history.
- Disconnect/reconnect the feed and run a short GPU stress test. The queue remains bounded; dropped frames and actual analysis rate are visible. CPU fallback is shown and capacity claims are recalculated.
- Use a small, labelled holdout set. Report counts, false positives, misses, and median/p95 frame-to-alert latency with sample size and footage conditions. This smoke gate is not a statewide accuracy guarantee.

**Module 2 is finished when:** a **real decoded frame** can trigger a persisted evidence-backed sighting and a deduplicated exact-match watchlist alert end-to-end; ambiguous cases do not silently become confirmed hits; and throughput/latency are measured, not guessed. Model accuracy remains a separately reported empirical result.

**Likely files:** `backend/app/vision/`, `backend/app/services/watchlist.py`, `backend/app/api/sightings.py`, `backend/app/api/alerts.py`, `frontend/src/sightings/`, `frontend/src/alerts/`, `tests/vision/`.

## Module 3 — Evidence Journey, designated-vehicle search, and report

**Purpose:** satisfy the evaluator's designated-registration search and produce an auditable cross-camera movement history.

**Build:**

1. Search historical sightings by normalized plate, time range, camera, and review status, including detections made **before** the search starts. Show raw and normalized OCR, camera, location, source type, PTS, timestamp provenance/uncertainty, and evidence.
2. Establish a time contract: use verified source UTC or a documented PTS-to-UTC mapping when available. The Sentinel reference guarantees monotonic PTS per stream but does **not** establish cross-camera UTC synchronization. If that mapping is unavailable, label the receive-time order as approximate and do not fabricate precise travel times or an exact chronology. Investigate the actual stream metadata before promising an exact route.
3. Assemble an Evidence Journey Graph: observed sightings are solid points tied to evidence; possible connections are dashed/inferred. Use distance and broad configurable time bounds to flag implausible jumps; never claim the direct line between cameras is the road route. Allow a reviewer to confirm/reject a candidate without deleting the source record.
4. Export one report generated from the same persisted query as the UI: target plate, camera IDs/locations, source and verified/uncertain times, observed points, inferred links, watchlist alerts, evidence hashes, model version, operator corrections, and gaps. Include Government/owned/replay labels.

**Module interfaces:** `POST /api/v1/pursuits`, `GET /api/v1/pursuits/{id}`, `GET /api/v1/pursuits/{id}/journey`, review action endpoints, and `GET /api/v1/pursuits/{id}/report`. Module 4 receives the latest **confirmed** sighting plus candidate camera metadata; it cannot silently promote an ambiguous OCR result.

**Required tests:**

- Use an owned, annotated three-camera scenario with a common verified clock. Search the target plate and get the expected three observed points in time order, with evidence and map markers; the report and UI show identical records. If a live source contains fewer than three actual observations, show the actual number.
- Add an OCR false positive and an impossible time/distance jump. Review/reject it; source evidence stays intact while the journey and report reflect the decision.
- With a test source offering only per-stream PTS, verify that the UI/report displays unaligned/approximate timing instead of a fake UTC route. Test a reconnect and loop cut so the PTS timeline does not merge incompatible stream generations.
- Remove or deny an evidence file: report visibly flags it rather than presenting an unsupported observation. Recompute a saved evidence hash and detect a mismatch.
- Search data created before the query and restart the server; the same history returns. Verify a user without the relevant department permission cannot fetch its evidence/report.

**Module 3 is finished when:** an evaluator-supplied registration number returns real historical sightings, an evidence-linked GIS journey, and a consistent downloadable report; observed and inferred elements are visually distinct; timestamps are defensible. **Exact cross-camera timing remains a blocked claim until a common clock is verified.**

**Likely files:** `backend/app/services/journey.py`, `backend/app/services/report.py`, `backend/app/api/pursuits.py`, `frontend/src/journey/`, `frontend/src/reports/`, `tests/journey/`.

## Module 4 — Active Pursuit, Coverage Integrity, and deployment proof

**Purpose:** deliver the distinctive adaptive search loop and a credible route to real deployment, after the mandated journey works.

**Build:**

1. Benchmark sustainable end-to-end decoded/analysed frames per second per worker on representative camera sizes/codecs. Reserve headroom (initial design target at least 30%) for decode, API, UI, and spikes. The scheduler's budget comes from this measurement, not the GPU model name.
2. From the last confirmed sighting, rank plausible next cameras using distance/travel window, feed health, plate readability, current queue delay, and analysis cost. Keep multiple directions when direction is unknown. Explain ranking factors; do not call an uncalibrated score a probability.
3. Maintain a measured baseline across the active set, allocate spare frames to ranked cameras, and require workers to acknowledge their **applied** rate. React to a new sighting, unavailable feed, and GPU saturation. Make schedules deterministic and auditable for the same inputs.
4. Record a Coverage Integrity Ledger per pursuit-camera-window with planned/received/analyzed frames, health, decoding errors, and one of: `observed`, `not observed in sampled frames`, `feed unavailable`, `insufficient coverage`. Do not equate a negative sample with proof that a vehicle was absent.
5. Produce the HLD/deployment evidence: regional ingest and GPU workers, central metadata/event store, PostgreSQL/PostGIS migration path, role/department access, secrets, TLS, retention, backup/restore, audit, failover, monitoring, capacity/cost formula, and a staged ~50-feed → regional → ~80,000-camera rollout. Document actual prototype limits separately from proposed production design.

**Module interfaces:** `GET /api/v1/pursuits/{id}/rankings`, `GET /api/v1/pursuits/{id}/schedule`, `GET /api/v1/pursuits/{id}/coverage`, worker schedule acknowledgement, and `GET /api/v1/metrics` restricted to operators. Module 3's report includes the ledger and applied schedule.

**Required tests:**

- On the same owned scenario and **same total measured frame budget**, run uniform sampling and Active Pursuit from reset state. Compare valid time-to-next-sighting, frames analyzed, misses, false alerts, and gaps. Record the result even if adaptive scheduling does not improve it; do not claim a benefit without a measured improvement.
- Replay identical input events to the scheduler twice; rankings and allocations match. New confirmed sighting changes the ranked set for a documented reason. Unconfirmed OCR does not drive pursuit automatically.
- Simulate an offline feed, unreadable camera, insufficient sampling, and a camera where the target was observed. Each produces the corresponding ledger status, visible in the dashboard and report. The worker's acknowledged rate, not the scheduler's requested rate, determines coverage.
- Saturate the GPU queue. The scheduler reduces load or marks insufficient coverage rather than silently accumulating delay. Show baseline status for cameras not prioritized.
- Load-test the actual accessible live feed set within portal terms. Report discovered, connected, analyzed, and concurrently analyzed camera counts, CPU/GPU/RAM/network use, reconnects, p95 latency, and failures. The ~80,000-camera plan is accepted as an architecture/capacity model only, not a claim that it was run.
- Rehearse the required own-feed operational demo, Sentinel/Government-feed demo if access exists, timestamped output report, HLD, presentation, and accessible submission links. A polished UI without the backend data path fails this gate.

**Module 4 is finished for the hackathon when:** a confirmed sighting causes a visible, logged change to camera sampling; the measured budget is never exceeded silently; the ledger's four states are derived from real counters/health; the fair baseline comparison is recorded; and the deployment/HLD package states measured prototype capacity and proposed rollout separately. **Production readiness requires additional regional, security, retention, disaster-recovery, and operational acceptance testing.**

**Likely files:** `backend/app/services/scheduler.py`, `backend/app/services/coverage.py`, `backend/app/api/coverage.py`, `frontend/src/pursuit/`, `frontend/src/coverage/`, `scripts/benchmark.py`, `docs/HLD.md`, `docs/demo_script.md`, `tests/pursuit/`.

## Practical order for a two-person, 48-hour build

| Timebox | Builder A: feed/AI | Builder B: API/UI/GIS | Exit evidence |
|---|---|---|---|
| 0–12 h | Feed adapters, PTS, reconnection, real frame | Schema, registry, catalogue import, map/viewer | Module 1 local gate |
| 12–24 h | ANPR, evidence, dedup, benchmark | Watchlist, alerts, live UI | Module 2 gate |
| 24–34 h | Time mapping, evidence integrity, route validation | Search, journey UI, export | Module 3 gate |
| 34–44 h | Scheduler, applied-rate counters, ledger | Pursuit/coverage UI, HLD, demo integration | Module 4 gate |
| 44–48 h | Government-feed test if available, failure fixes | Report, recording, final links/checklist | End-to-end rehearsal |

This is a prioritization target, not evidence that 48 hours will suffice. If time slips, protect the mandatory path: working feed → actual ANPR → watchlist alert → designated-vehicle history/map/report → distinctive pursuit/ledger. Keep a startup command, last passing commit, fixture/source label, measured results, and known defects at every handoff.

## Final end-to-end acceptance run

1. Start from a clean checkout and configured secrets; start backend, database, inference worker, and frontend. Verify health, auth, and source access.
2. Import/refresh the camera catalogue and show the GIS registry. Show one real live feed and a second supported source type. Confirm PTS capture and health transitions.
3. Run ANPR on real decoded frames. Create a representative watchlist entry and prove an automatic, persisted alert with evidence.
4. Enter a target plate that is present in the test footage. Show observed points on the map, evidence, time provenance, uncertain links, and an exported report generated from the same data.
5. Begin Active Pursuit. Show a confirmed sighting changing camera priority and applied sampling, then show what the ledger says after a working camera, failed feed, and under-sampled window.
6. Disclose measured camera counts, GPU/frame budget, detection/alert latency, false positives/misses, recovery behaviour, and timestamp limitations. Record the working own-feed demo and the Government-feed demo only after actual authorised access/testing.

**Overall done:** all four module gates pass on the same integrated build, the mandatory Government-feed deliverables are completed if access is supplied, and every claim in the submission can be traced to a log, record, benchmark, source rule, or labelled architecture proposal. If a required live feed or shared timebase is missing, state that gap explicitly instead of marking the project complete.
