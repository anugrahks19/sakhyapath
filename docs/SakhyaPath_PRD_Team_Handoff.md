# SakhyaPath - Product Requirements Document and team handoff

**Version:** 1.0 | **Date:** 28 September 2026 | **Audience:** teammate, developer, tester, designer and hackathon presenter  
**Product stage:** integrated local prototype; organiser-owned Government footage and live evaluation pending  
**Decision owner:** project lead. The teammate should confirm scope and assignments with the lead before changing interfaces.

## 1. One-minute overview

SakhyaPath is an evidence-backed vehicle search system for a heterogeneous CCTV grid in Gujarat. An authorised operator registers or discovers cameras, sees them on a GIS map, runs number-plate recognition on selected live feeds, searches for a designated registration, reviews evidence-linked sightings, and launches a measured Active Pursuit that reallocates a bounded analysis budget. Its central promise is **honest search evidence**: every observation is tied to a decoded frame and source timestamp, while skipped cameras, outages, uncertain clocks and unsampled video remain visible. A signed Search Proof receipt lets a reviewer detect later changes to the search snapshot.

The implementation combines the hackathon's mandatory Model 1 registry/GIS foundation with a hybrid regional architecture. A region keeps raw video near the camera and can return only authorised metadata to the central interface. The current application is a local FastAPI/React/SQLite prototype. It must be demonstrated on team-owned or permission-cleared feeds until the organiser grants live Sentinel access. The organiser may privately test it with Government footage; teammates must not request or copy restricted footage to complete local tasks.

## 2. The problem and intended outcome

Large CCTV estates contain different departments, codecs, connectivity states and clock quality. A camera listed in a catalogue may be offline; a reported FPS is not a reliable frame clock; a plate read can be wrong; and a search that skips most cameras can falsely look conclusive. The operator needs one place to find a camera, inspect a real feed, find plate evidence, understand possible movement, and see precisely what the system did and did not observe.

**Primary outcome:** an evaluator can enter a target plate and see an evidence-linked, access-controlled search result with camera locations, source timing, review state, coverage gaps and an exportable report.  
**Distinctive outcome:** a pursuit can change sampling after a confirmed sighting while preserving a fair budget and an auditable coverage ledger.  
**Trust outcome:** a Search Proof records the search scope, counts, gaps, model version and evidence hashes in signed JSON/PDF.

## 3. Users and permissions

| Persona | Need | Key permission |
| --- | --- | --- |
| State/operator user | Search the authorised grid, investigate target, run pursuit, export proof | Operator role; still subject to deployment policy |
| Department analyst | Inspect own cameras and sightings | Department-scoped camera, evidence and regional search |
| Evidence reviewer | Confirm/reject ambiguous reads and preserve audit history | Review action within authorised scope |
| Regional service agent | Run bounded local search and deliver permitted metadata | Service identity restricted to configured department/region |
| Evaluator | Observe a transparent own-feed or approved live demo | No inherent access to unrestricted URLs or credentials |

Authentication uses an operator or department key for this prototype, sessions and CSRF for browser writes. Production requires approved identity federation, service identity, TLS and mTLS as appropriate. Every camera, sighting, evidence, report, proof and regional query must enforce scope server-side; hiding a button is insufficient.

## 4. Scope and product principles

### In scope now

1. Camera registry and Leaflet GIS; read-only Sentinel catalogue adapter; RTSP-over-TCP and HLS capture; controlled preview and health.
2. Plate detection/OCR, evidence crops and hashes, representative watchlist alerts, historical sighting search and review.
3. Evidence Journey with observed points versus inferred links, timing uncertainty and PDF report.
4. Active Pursuit scheduler with measured capacity, applied worker rates and Coverage Integrity Ledger.
5. Signed Search Proof; regional metadata query agents; shadow scheduler with exploration; camera/clock trust; regional metadata outbox across outages.

### Outside verified scope

There is no claim of police database integration, identity matching of people, automatic enforcement decisions, verified statewide scale, verified Government feed connection, or an Indian-road accuracy score. A uniform-versus-adaptive shadow decision is a counterfactual schedule record; it is not a second detector run or a measured hit improvement. A negative sample never proves a vehicle absent from a road or unsampled video.

### Rules that should never be weakened

- Catalogue metadata is not proof of decoded live frames.
- Preserve camera ID, source PTS, timebase, stream generation, source mode and receive time through capture and inference. Arrival time and reported FPS are not substitutes for source timing.
- Use a separately attested PTS-to-UTC mapping before precise cross-camera travel-time claims. Otherwise label times approximate.
- Keep credentials, private keys and raw stream URLs off the public frontend and out of logs and receipts.
- Only a confirmed evidence-backed sighting may move Active Pursuit automatically.
- Mark partial regional responses, outages, unsampled frames and unavailable feeds explicitly.

## 5. User journeys

### Journey A - camera onboarding and inspection

An operator signs in, imports authorised camera metadata or syncs the read-only `GET /api/ingest` catalogue, then opens the map. Each marker shows department, location, source type, catalogue state, decoded-feed health and analysis state. The operator opens a controlled preview; the backend establishes capture only when needed, records source PTS and closes idle capture. If a feed fails or restarts, the UI shows its current health, recent history and clock limitations. No camera is labelled online solely because the catalogue says live.

### Journey B - target plate and evidence

An analyst enters a normalized registration. The system searches persisted historical sightings, including those captured before the query. Each candidate has raw/normalized OCR, model scores, camera/location, source PTS/generation, available UTC mapping, evidence hash and review status. A reviewer may confirm or reject a candidate while retaining the source record and review history. The journey map displays observed sightings as evidence-backed points and possible connections as inferred. The PDF reflects the same persisted query.

### Journey C - Active Pursuit

An operator runs a measured capacity test on owned feeds, starts a pursuit, and sees a baseline plus selected priority cameras within the 70% sustainable-throughput ceiling. A confirmed sighting or camera failure triggers a documented schedule revision. Workers acknowledge applied rates; requested rates alone do not count as delivered coverage. A coverage window records planned, received and analyzed frames and one result code: `observed`, `not observed in sampled frames`, `feed unavailable`, or `insufficient coverage`. The UI and export show excluded cameras and gaps.

### Journey D - advanced trust and federation

The operator can create a signed Search Proof, inspect the camera/clock trust scorecard, compare adaptive and rotating uniform *decisions* from one capture, and enable one exploration slot without raising the total budget. When regional agents are configured, an authorised search fans out and returns metadata-only hits. A failed region or empty configuration returns `complete=false`. A regional link outage leaves a local durable metadata queue; after reconnection the central inbox deduplicates replay and reports the gap. The centre cannot claim visibility of events still undelivered across a partition.

## 6. Functional requirements and acceptance criteria

Priority legend: **P0** required for honest core demo; **P1** advanced differentiator; **P2** production phase.

| ID | Priority | Requirement | Acceptance evidence |
| --- | --- | --- | --- |
| CAM-01 | P0 | Persist camera ID, department, coordinates, source type and status; render the same records on API/map after restart. | Import, restart, API/map reconciliation. |
| CAM-02 | P0 | Sync only the authorised read-only Sentinel catalogue; update changed/removed cameras; never invent URLs or use control API. | Stub changes/removal test; live test when access exists. |
| CAM-03 | P0 | Decode owned RTSP and HLS with PTS, H.264/H.265, warm-up, bounded reconnect, generation changes and idle close. | Two-source live test, interruption/recovery and health history. |
| VIS-01 | P0 | Preserve actual decoded-frame metadata in a bounded latest-frame inference path. | Measured received/selected/analyzed/dropped counts, no hidden backlog. |
| VIS-02 | P0 | Save a real plate read with confidence, model version, evidence ref/hash and timestamp provenance. | Owned feed creates persisted searchable sighting. |
| ALT-01 | P0 | Exact high-confidence representative watchlist alert, deduplication, acknowledgement and history. | Positive, negative and ambiguous samples; reload persistence. |
| JRN-01 | P0 | Historical target search, reviewed observations, inferred links, access control and PDF from same data. | Three-camera owned fixture plus negative/review case; UI/report match. |
| TIM-01 | P0 | Reject precise cross-camera time claims without current attested clock mapping. | Restart invalidates old mapping; UI/report remain approximate. |
| PUR-01 | P0 | Schedule from measured end-to-end capacity with 30% reserve, applied-rate acknowledgment and deterministic revisions. | Budget test, repeated input, saturation and failure tests. |
| COV-01 | P0 | Derive four ledger states from real health and per-window counters. | Working, target-observed, failed and undersampled examples. |
| PRF-01 | P1 | Produce immutable signed JSON/PDF Search Proof with scope, counters, gaps, model and evidence hashes. | Independent verify succeeds; altered byte fails; no URLs; zero-hit wording correct. |
| FED-01 | P1 | Search configured regional agents under department scope and return metadata only. | Two isolated agents, one denied request, partial/empty response incomplete. |
| SHD-01 | P1 | Record equal-budget adaptive and uniform scheduling decisions; optional one-slot exploration. | Same revision/budget, one capture, persisted toggle, no claimed counterfactual hits. |
| TRU-01 | P1 | Report observed capture health, PTS intervals, queue age, generation and UTC mapping status. | H.264/H.265/restart test; precise time blocked without mapping. |
| OUT-01 | P1 | Queue strict regional metadata while central unavailable and idempotently replay later. | Simulated outage, auto retry, restart, duplicate acknowledgement, schema rejects video URL. |
| OPS-01 | P2 | Production regional deployment with durable data, approved identity, key management, observability and recovery. | Multi-feed pilot, security review, restore/failover drill and measured SLOs. |

## 7. Architecture and data flow

```text
Authorised camera/VMS catalogue -> regional registry + GIS metadata -> central API/map
Authorised RTSP/HLS -> on-demand regional capture -> decoded frame + source PTS/generation
decoded frame -> bounded sampler -> ALPR -> persisted sighting + hashed evidence
sighting -> watchlist alert, historical journey and reviewer action
confirmed sighting + health + measured capacity -> Active Pursuit -> worker applied rates
worker counters + health -> coverage ledger -> dashboard/report/Search Proof
regional metadata query/outbox -> scoped central API -> map and investigation
```

**Current stack:** FastAPI/Python, React/Leaflet, SQLite, FastALPR, OpenCV/PyAV capture path, local evidence files, Ed25519 signing and optional local/regional agent processes. Refer to `backend/requirements.txt` and `frontend/package.json` for pinned exact packages. The prototype uses process-local capture and sessions, a single active pursuit and a default four-camera analysis cap.

**Pilot target topology:** regional read-only ingest and GPU workers near source VMS; one upstream connection per active camera; bounded latest-frame queues; region-scoped metadata and evidence; central PostgreSQL/PostGIS; durable event bus and encrypted object storage; approved identity/TLS/KMS/retention; worker leases, backups, restore and failover drills. This is a deployment design, not a completed implementation.

## 8. Data and interface contract

| Record | Minimum fields and interpretation |
| --- | --- |
| Camera | `camera_id`, source system/type, department, coordinates, codec/resolution, catalogue seen time, health; URL reference server-only. |
| Frame | `camera_id`, `source_pts`, `pts_timebase`, `stream_generation`, `source_mode`, receive UTC for diagnostics, verified event UTC only if mapping exists. |
| Sighting | Stable ID, camera/frame provenance, raw and normalized plate, detector/OCR score, model version, evidence ref and SHA-256, review state. |
| Alert | Stable ID, watchlist entry, sighting, match basis, status, acknowledgement actor/time. |
| Coverage | Pursuit/camera/window, planned/received/analyzed frames, health/errors, applied rate, result code and reason. |
| Regional event | Stable event ID, region, department, permitted metadata and event time/provenance; no video, crop bytes or source URL. |
| Search Proof | Query and eligible scope, counts, unavailable/skipped coverage, sightings/reviews/alerts, model and evidence hashes, signature and verification key ID. |

**Key existing endpoints:** `/api/v1/health`, `/api/v1/cameras`, `/api/v1/cameras/sync-sentinel`, `/api/v1/cameras/{id}/trust`, `/api/v1/sightings`, `/api/v1/alerts`, `/api/v1/pursuits/{id}/journey`, `/api/v1/pursuits/{id}/schedule`, `/api/v1/pursuits/{id}/coverage`, `/api/v1/pursuits/{id}/shadow`, `/api/v1/pursuits/{id}/proofs`, `/api/v1/federation/search`, and `/api/v1/regions/events`. Source-of-truth request/response details are in `backend/app/main.py` and `backend/app/schemas.py`; do not implement from this summary alone.

## 9. Non-functional requirements

- **Truth and provenance:** every visible hit links to stored evidence and timing provenance; every gap has a reason. No “vehicle absent” conclusion from negative samples.
- **Performance:** measure frame-to-alert median/p95, decode rate, applied analysis fps, queue age and reconnects on the actual host/feed mix. Do not extrapolate the existing laptop benchmark to statewide capacity.
- **Scalability:** register many cameras without connecting to all of them; analyze on demand. Partition by region and independently size worker replicas from measured fps. Keep uniform/adaptive experiments under identical budgets.
- **Security/privacy:** server-side department scope, HTTPS/service identity, secret manager/KMS, minimal regional metadata, evidence encryption and retention defined with authority. No private stream URL or key in browser, logs or exports.
- **Reliability:** bounded queues and reconnect backoff, durable event IDs/outbox, incomplete-result flags, replay after outage and tested backup restore before operational use.
- **Accessibility/UX:** light-mode interface; clear live/replay/unavailable labels; visible source and clock confidence; operator actions and errors stated in plain language. Animations must not block data or add heavy polling.
- **Observability:** separate discovered, connected, viewed and analyzed counts; requested versus applied fps; health/gap/error rates; receipt verification and key status.

## 10. Demonstration and validation plan without Government footage

1. Start a fresh server with a test operator key and disposable SQLite database. Confirm authentication, health and map.
2. Add two team-owned feeds with distinct source types or codecs. Show actual decoded frames, PTS, health, reconnect and controlled preview. Label all inputs owned/replay.
3. Use an annotated, permission-cleared plate sample to produce a real persisted sighting, evidence crop/hash and representative watchlist alert. Show a nonmatch and an ambiguous read.
4. Search a target plate, show observed versus inferred journey points, a review correction and a PDF. Demonstrate that unaligned clocks remain approximate.
5. Run the measured pursuit and show a confirmed sighting changing the schedule, the applied frame budget, four coverage states and shadow/exploration records.
6. Create and download a Search Proof. Verify signature with the pinned public key; alter a byte in a copy and show verification fails. Point to unavailable/unsampled coverage in receipt.
7. Start two isolated regional agents. Show scoped metadata search, denial across departments and `complete=false` on an offline region. Drop central connectivity; show pending metadata and idempotent automatic reconciliation.
8. Show test outputs, the exact host/feed/codec conditions, open gates and the production HLD. Record a 2-3 minute own-feed operational video separately for submission.

**Repeatable local gate:** `python -m pytest -q` in the project environment (28 passed on 28 September 2026), `npm run build --prefix frontend`, `scripts/verify_existing_db_migration.py`, and the isolated HTTP smoke `scripts/verify_runtime.py --allow-test-data` against a disposable server. Read [the verification report](VERIFICATION_REPORT_2026-09-28.md) for precise evidence. Government live validation must occur in the organiser-approved environment and may not create a local recording without permission.

## 11. Teammate handoff: concrete work packages

**Package A - reproduce and document (first):** Clone/open the same revision; install from the runbooks; run the full suite and frontend build; record versions, host, command outputs and any failure. Confirm port 8000 was restarted with existing environment before testing new endpoints. Do not replace the existing database with smoke-test data.

**Package B - own-feed demo:** Prepare an owned RTSP/HLS source and annotated target plate; record the actual UI/backend path from decoded frame to sighting, journey, alert and receipt. Measure sample size, p50/p95 latency, misses and false reads. Label model sample imagery separately from Indian-road footage.

**Package C - advanced feature rehearsal:** Run the two-agent scoped search and outage replay, the receipt tamper check, trust/reconnect test and shadow/exploration schedule. Capture one screenshot or clip plus corresponding API/log evidence for each feature; record which process and database produced it.

**Package D - submission support:** Turn the evidence into slides: problem, architecture, real own-feed flow, Search Proof, adaptive/coverage honesty, regional scaling, measured local results and open gates. Check all demo and deck links from a private browser session. Use only claims backed by recorded evidence.

**Package E - production planning (after demo):** Draft regional pilot sizing for about 50 authorised feeds from measured codec/resolution/bitrate and selected analysis fps; propose PostgreSQL/PostGIS migration, durable events, identity, KMS, encrypted evidence, retention, disaster recovery and monitoring. Keep this explicitly marked proposed until tested.

Each package is done when the teammate supplies the command/configuration, test input provenance, expected versus actual result, output artifact, date and known limitation. Do not mark Government integration, Indian-road model quality or production readiness done from local tests.

## 12. Release gates and unresolved dependencies

| Gate | Current state | Who/what unlocks it |
| --- | --- | --- |
| Local integrated behavior | Passed: 28 backend tests, frontend build, isolated HTTP/browser checks | Team reruns on one shared revision and records results. |
| Current localhost 8000 | Older backend process lacks new endpoints | Restart it with current key/DB/env preserved. |
| Sentinel live catalogue/feed | Pending | Organiser approves account, supplies authorised origin/auth/network rules; then read-only sync and live test. |
| Indian-road recognition score | Pending | Independent permission-cleared annotated holdout or organiser-derived private evaluation metrics. |
| Cross-camera exact route | Pending | Verified shared UTC mapping and uncertainty per stream generation. |
| Fair adaptive benefit | Pending | Multiple reset, annotated routes with equal analyzed-frame budget; report losses too. |
| Submission media and shareable links | Own-feed recording/link check pending | Team records operational video and publishes only to approved destination. |
| Production deployment | Proposed only | Regional pilot, security/retention approval, migration and restore/failover/load tests. |

## 13. Open questions for the project lead and organiser

1. What is the official Sentinel catalogue origin and permitted authentication/network route? The current source guide does not supply access credentials.
2. Which departments and cameras may the team query during private evaluation, and what derived reports/screenshots may be retained?
3. Is a common UTC clock or trusted PTS-to-UTC anchor available for each feed/generation?
4. What private scoring will the organiser return for exact plates, false reads, misses and latency?
5. What specific submission destination and file/link access rules apply to the deck, code and own-feed video?
6. Which teammate owns the own-feed demo, slide assembly, regional drill and live evaluation checklist? Assign one accountable owner and due date to each.

## 14. Source documents in this workspace

- `hackathon_source_index/README.md` - indexed hackathon brief and source locations.
- `sentinel_source_index/README.md` - indexed integration reference and constraints.
- `SakhyaPath_4_module_implementation_plan.md` - original module gates and exact test ideas.
- `docs/FEATURE_IMPLEMENTATION_LOG.md` - five differentiators, API flow, demo and claim wording.
- `docs/MODULE4_HLD.md` and `docs/PRODUCTION_GATE.md` - regional target architecture and production acceptance.
- `docs/VERIFICATION_REPORT_2026-09-28.md` - current integrated verification evidence.

**Suggested message when sharing:** “Here is the SakhyaPath PRD and handoff. Please start with Section 11, rerun the local gate in Section 10, and record evidence against the requirements in Section 6. The organiser keeps Government footage private, so use only owned or permission-cleared feeds for our demo. Flag every pending gate rather than presenting it as complete.”

## 15. One-page execution checklist for the teammate

Use this checklist as the daily handoff record. Put a name, date and evidence link beside each item in the team's tracker.

- Confirm the shared code revision and the environment variables needed for the local instance. Do not copy secrets into the tracker or a screenshot.
- Run the 28-test backend suite and the frontend production build. Record the exact commands and results. If the count changes after new work, record the new count and explain why.
- Restart the existing backend on port 8000 only after preserving its operator key and database path; then confirm the new proof public-key endpoint responds. Avoid running the destructive disposable smoke against that operational database.
- Verify one owned camera through catalogue/import, decoded preview, PTS, health state and map marker. Confirm the browser network trace does not expose raw stream credentials.
- Prepare a second owned source type or codec. Demonstrate a disconnect/reconnect and record the new stream generation and coverage gap.
- Run a target plate through the real decoder and recognizer. Save the raw/normalized result, confidence, model version, evidence hash and any false read. Do not substitute a manually entered sighting for this demo gate.
- Add a representative watchlist item, confirm an actual matching alert and show a nonmatch/ambiguous case. Confirm the alert and review history survive reload.
- Create a journey and report; check observed versus inferred markers, timing labels and reviewer correction. Compare the underlying sighting IDs in UI and PDF.
- Run a measured pursuit; capture requested and applied rates, remaining budget, schedule revision, shadow comparison and four coverage states. Mark cameras excluded by capacity.
- Export Search Proof JSON/PDF, verify both with the pinned public key, and tamper with a copy to show a failure. Make sure the receipt names unavailable and unsampled coverage.
- Run department A and B regional agents with isolated databases; test operator search, forbidden cross-department access, a failed region, link outage and automatic idempotent metadata replay.
- Rehearse the 2-3 minute own-feed demo from a fresh start. Record a concise narration that distinguishes implemented local behavior, proposed regional scale and organiser-pending private footage tests.
- Update the slide evidence table and shareable links. Open every link in a private browser session and check that no secret, raw Government URL or restricted media is exposed.

For each failed item, log **input, expected result, actual result, logs/screenshot, suspected cause, owner, next action**. Fix regressions in the current build before adding extra features. A partial feature should be shown as partial in both the PRD tracker and presentation.

## 16. The idea, explained for a teammate and evaluator

**The simple pitch:** “SakhyaPath helps an authorised investigator search a distributed CCTV grid for a vehicle while proving which cameras and frames were actually examined. It follows evidence, shifts limited compute to promising cameras, and produces a signed receipt that shows both findings and blind spots.”

Imagine an operator searching for a designated registration after a reported incident. A conventional map can show nearby camera icons, but it cannot tell whether each camera decoded a frame, whether its plate detector ran, whether its clock agrees with the next camera, or whether a no-hit result has any meaning. SakhyaPath treats these facts as first-class product data. Camera health and timestamp trust sit beside every observation; coverage counters accompany every search; review decisions stay tied to original evidence. The investigator gets a defensible *investigation trail*, not a visually appealing guess.

The second idea is that analysis capacity is scarce. If there are many registered cameras but only a measured budget of analyzed frames per second, the system should not imply it watched everything. Active Pursuit starts from the last **confirmed** sighting, ranks eligible nearby cameras using transparent factors, changes the applied sampling rates, and records each decision. One optional exploration slot keeps a camera outside the top-ranked route in view. A shadow policy records what a rotating uniform schedule would have chosen under the same budget, allowing a fair later replay comparison. These controls make the distinctive feature inspectable and falsifiable.

The third idea is deployment reality. Different departments may retain their own VMS and camera permissions. SakhyaPath's regional agent pattern searches approved metadata near each source; the centre receives permitted hits and explicit partial-result status rather than pulling every raw video stream statewide. If a regional link fails, the local agent queues limited metadata and replays it with stable event IDs. The user sees the missing interval. This gives the prototype a credible migration path while keeping the current implementation's limits visible.

**Why the combination is memorable:** one journey connects an authorised camera grid, actual plate evidence, adaptive compute, coverage truth, regional access boundaries and a signed Search Proof. The feature is not a claim that AI knows a vehicle's true route. It is a system for making useful search decisions while exposing uncertainty. That claim can be demonstrated without Government footage on owned streams and then privately checked by the organiser on authorised feeds.

**The evaluator's decisive moment:** start with two owned cameras on the map. One displays a real decoded preview and the other is deliberately disconnected. Run a designated-plate search. The first camera yields an evidence-backed plate sighting and the second becomes an explicit unavailable gap. The pursuit reacts only to the confirmed sighting and shows the new applied sampling rates. The trust card explains why the map cannot claim an exact travel time. The signed receipt records the frames analyzed and the failed camera; changing one byte makes independent verification fail. This five-minute sequence proves the project's main idea more strongly than a slide with a large but untested camera count.

**Why an implementation team can build on it:** the prototype already has a versioned API, persistent camera/sighting/pursuit records, a tested live owned-feed path, and explicit boundaries between capture, recognition, journey, scheduling and proof. The next team can improve model quality, regional deployment or UI without rewriting what a camera ID, frame timestamp or coverage window means. The teammate's role is to preserve those contracts, turn local checks into reproducible evidence, and make the presentation trace every claim to a result. A persuasive pitch comes from one verified end-to-end story and a credible staged rollout, not from promising an unmeasured statewide deployment.

## 17. Technology stack: what exists and what is proposed

| Layer | Current implementation | Why it is used | Production direction, not yet deployed |
| --- | --- | --- | --- |
| Frontend | React 19, Vite 8, Leaflet 1.9, CSS light-mode dashboard | Fast browser UI for map, cameras, pursuit, trust and receipts | Same UI concept behind approved ingress, accessibility and operational hardening |
| API and services | Python, FastAPI, Uvicorn, Pydantic, HTTPX | Versioned REST endpoints, validation, auth and regional calls | Separately scaled regional and central services with policy enforcement |
| Video capture | PyAV/FFmpeg and OpenCV, RTSP-over-TCP with HLS fallback | Decode varied sources; retain per-stream PTS and stream generation | Regional capture relays, leases and one upstream connection per active feed, validated under load |
| Plate recognition | FastALPR with its detector/OCR packages; OpenCV/NumPy image handling | Real decoded-frame plate detection and OCR on owned inputs | Tune and score on permission-cleared Indian-road holdout; size GPU workers from measured throughput |
| Registry and events | SQLite, local file evidence and process-local workers | Simple reproducible local prototype and persisted audit records | PostgreSQL/PostGIS, durable event bus, encrypted object storage and distributed workers |
| Reports and integrity | ReportLab, pypdf, SHA-256 evidence hashes, Ed25519 signatures via `cryptography` | Evidence report and tamper-detectable Search Proof JSON/PDF | Approved KMS/HSM, external key pinning, retention and independent verification |
| Regional connection | Configured HTTPX agent calls, department-scoped token, SQLite metadata outbox | Demonstrate federation and retry without moving video | mTLS or approved service identity, protected configuration, durable regional queue |
| Tests and packaging | pytest, owned RTSP/HLS fixtures, HTTP/browser smoke, Vite build, Git | Reproduce behavior and regressions on one revision | CI/CD, security scans, regional load/restore/failover tests and audited release process |

Exact package versions are pinned in `backend/requirements.txt` and `frontend/package.json`. CUDA is an optional acceleration path for the locally measured model environment; the product must expose CPU fallback and remeasure capacity when hardware changes. MediaMTX may be used only as an owned-feed relay where needed; it is not a required Government gateway component or a substitute for source timestamp validation. PostgreSQL/PostGIS, broker, KMS and object storage are **target architecture choices**, not claims about the current installation.

## 18. Architecture from camera to defensible result

### 18.1 Local integrated architecture today

```text
Read-only camera catalogue / authorised owned RTSP or HLS
              |
              v
FastAPI registry + on-demand PyAV capture + health/PTS tracking
              |                         |
              |                         +--> React/Leaflet preview and trust card
              v
Bounded latest-frame sampler --> FastALPR --> sighting + evidence hash
                                      |                  |
                                      |                  +--> watchlist alert/review
                                      v
                             journey + confirmed anchor
                                      |
                                      v
                     measured Active Pursuit + shadow decision
                                      |
                                      v
                        applied worker rate + coverage ledger
                                      |
                                      v
                       report + signed Search Proof JSON/PDF
```

The registry and map can contain more camera records than active capture workers. A viewer or analyzer causes the backend to connect to a feed; closing idle work releases capture. Each decoded packet carries the camera ID, PTS, timebase, stream generation and source mode. The sampler keeps the latest frames instead of accumulating an unbounded queue. Plate readings become persisted sightings with confidence and evidence. Review status determines which sightings can anchor a pursuit. The scheduler's desired rate is compared to worker acknowledgement and actual frame counters before the coverage ledger can state what was analyzed.

SQLite holds camera, sighting, pursuit, schedule, coverage and proof records in the current build. Local evidence files are protected by API access checks and hash references. Search Proof signs a frozen snapshot; it does not continuously update if a review changes later. The correct action after a material change is to generate a new receipt while retaining the old one for audit.

### 18.2 Regional deployment path

```text
Department/VMS A --> regional read-only ingest A --> local GPU workers A --+
                                                                      |
Department/VMS B --> regional read-only ingest B --> local GPU workers B --+--> permitted metadata/events
                                                                      |          to central API
Regional evidence and bounded outbox stay near the source ------------+                |
                                                                                       v
                                                               PostgreSQL/PostGIS + audit
                                                                                       |
                                                                                       v
                                                                  scoped web map/search/proof
```

The centre configures which regions can be queried and which departments an operator may see. A regional search returns bounded hit metadata, not source URLs or frame bytes. Each region can continue local bounded analysis when the wide-area connection is down; the central view marks incomplete results until permitted events arrive. Production work must add identity, encrypted transport/storage, a durable event system, policy review, monitoring and tested recovery before any operational rollout.

**Scaling rule:** do not interpret 80,000 registered camera records as 80,000 simultaneous video streams. Let `N` be concurrently analyzed feeds, `r` the target fps per feed, and `B_worker` the measured safe analyzed fps per worker for that feed mix. Required worker count is at least `ceil(N × r / B_worker)` plus failover reserve. Recalculate for each codec, resolution, model and hardware class. The existing two-feed laptop measurement is a calibration for that laptop, not a statewide capacity benchmark.

## 19. End-to-end workflow: what happens when a plate is searched

The example plate below is **fictional test input**. Actual results must come from decoded owned or authorised feeds, and every screenshot should show the correct source label.

1. **Prepare the grid.** The operator imports authorised camera records or calls the read-only catalogue sync. The UI shows geographic markers, department scope and separate discovered/connected/viewed/analyzed counts. A marker with no decoded frame remains unverified or unavailable, even if catalogue metadata says live.
2. **Connect only needed feeds.** The operator opens a preview or starts bounded analysis. The backend connects through the allowed RTSP/HLS adapter, records actual frame PTS, stream generation, codec, resolution, decode health and reconnects, and never places raw credentials in the browser.
3. **Create target search.** The operator enters test plate `GJ01AB1234`. The backend normalizes the search value and checks persisted historical sightings first. A department user sees only permitted cameras and records. A regional query, if configured, returns scoped hit metadata plus a `complete` flag; a missing or failed region is visible.
4. **Recognize and preserve evidence.** On each selected decoded frame, the recognizer attempts plate detection and OCR. A qualified read stores raw and normalized text, scores, model version, camera/source PTS/generation and a hashed evidence crop. A low-confidence or ambiguous reading goes to review instead of silently becoming a confirmed alert.
5. **Show the journey honestly.** Confirmed sightings appear as observed map points linked to evidence. Possible movement between cameras is shown as an inferred connection. If clocks are not aligned, the view uses approximate receive-time order and refuses precise travel-time conclusions.
6. **Direct limited compute.** After a confirmed sighting, Active Pursuit ranks candidate cameras using current health, straight-line proximity, measured queue age and cost/readability proxies. It asks workers for new sample rates within the measured budget. The UI distinguishes the requested schedule from rates actually acknowledged by inference workers.
7. **Account for gaps.** Every pursuit-camera window stores planned, received and analyzed frames plus failures. The resulting state is observed, not observed in sampled frames, feed unavailable or insufficient coverage. An unselected camera is a visible gap, not an implied negative result.
8. **Compare decisions.** The shadow record shows what a rotating uniform policy would have scheduled under the same budget. One exploration slot may sample a lower-ranked camera. The comparison becomes a performance claim only after replaying multiple annotated routes from reset state and measuring hits, misses, latency and frame use.
9. **Export a defensible record.** The operator downloads the journey report and creates a signed Search Proof. The receipt lists eligible cameras, analyzed counts, gaps, models, reviews, alerts and evidence hashes. Independent verification detects edits to the exported JSON/PDF. A zero-hit result is explicitly limited to the frames analyzed.
10. **Recover from outage.** If a regional link fails, the agent retains only allowed event metadata in a bounded local outbox. When connectivity returns, it retries with stable IDs; the central inbox deduplicates delivery and updates the gap view. Until then, the central search remains incomplete.

**What the teammate should be convinced of:** this is a coherent product loop, not a collection of unrelated AI widgets. The camera grid supplies identity and location; real frames supply evidence; review supplies trust; the scheduler allocates measured compute; the ledger explains coverage; regional agents make the pattern deployable; and the signed receipt makes each investigation inspectable. The strongest presentation is a live, labelled demonstration of that loop followed by precise measurements and openly stated pending gates.
