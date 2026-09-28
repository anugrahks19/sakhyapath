# SakhyaPath: implemented features and what makes the approach distinctive

**Prepared for:** teammate handoff and hackathon presentation  
**Evidence date:** 28 September 2026  
**Implementation status:** integrated local prototype tested with owned/synthetic feeds. The organiser's private Government feeds, Indian-road accuracy, and a production regional deployment have **not** been validated.

## The idea in plain language

SakhyaPath lets an authorised operator search a CCTV grid for a vehicle registration and see a defensible account of what the system actually observed. It joins a GIS camera registry, decoded live feeds, plate recognition, evidence review, a cross-camera journey, and a measured Active Pursuit. It also records blind spots: cameras that were disconnected, frames that were never analyzed, uncertain clocks, and regional searches that did not return.

The strongest distinctive element is the **closed evidence loop**:

```text
Camera identity and location
  -> real decoded frame with source PTS
  -> plate read and hashed evidence
  -> reviewer-confirmed sighting
  -> bounded pursuit schedule
  -> actual analyzed-frame coverage
  -> signed Search Proof with gaps
```

Each step has persisted data or an explicit uncertainty label. A generic CCTV dashboard may show streams or alerts; SakhyaPath is designed to show **why a search result is credible and where it is incomplete**. This is a product distinction, not a claim that nobody else has built similar components or that a hackathon win is guaranteed.

## What “implemented” means here

The backend is FastAPI/Python with SQLite, PyAV/OpenCV capture, FastALPR, local evidence storage, report generation and Ed25519 proof signing. The light-mode browser UI uses React, Vite and Leaflet. The local suite passed **28 backend tests**; the frontend production build, fresh-server HTTP smoke, browser checks and a migration test on a copy of the existing database passed. These checks establish local integration, not Government-feed compatibility or statewide scale. See the [verification report](VERIFICATION_REPORT_2026-09-28.md) for the exact tests.

The five advanced features below are integrated with the existing four modules. They share camera IDs, sightings, pursuits, health, timestamps and department permissions rather than operating as independent mock screens. The existing server on port 8000 was an older Python process at the last check; it needs a restart with its current key and database settings preserved before showing new endpoints there.

## Module 1: camera grid, GIS and source integrity

### 1. Persistent camera registry and GIS map

**Implemented:** authenticated camera import, list and detail APIs; stable camera IDs; department, coordinates, source type, catalogue and health status; and a Leaflet map whose marker colour reflects decoded-feed health. Records survive backend restart. The UI also displays registered/discovered, connected, viewed and analyzed counts separately.

**Why it matters:** a camera appearing in a catalogue is only a candidate source. SakhyaPath waits for a successfully decoded recent frame before calling it online. This avoids overstating live coverage.

**Verified locally:** import/restart/map and API tests. A real Sentinel catalogue has not been queried because authorised origin and access were not supplied.

### 2. Read-only Sentinel catalogue adapter

**Implemented:** `GET /api/ingest` client behind `POST /api/v1/cameras/sync-sentinel`. It consumes URLs and metadata returned by the catalogue, updates changed IDs/properties, and marks removed cameras absent. It never constructs a stream URL from a numeric ID, calls the Sentinel control API, or publishes to the gateway.

**Distinctive contribution:** the app can reconcile a changing, heterogeneous external grid while keeping source discovery separate from health and analysis. The strict read-only contract supports the organiser's feed rules.

**Verified locally:** stub catalogue changes, removal and URL handling. **Government integration remains unverified.**

### 3. Heterogeneous, on-demand feed capture

**Implemented:** RTSP-over-TCP capture with HLS fallback; H.264/H.265 decoding on owned sources; source PTS/timebase retention; variable frame interval handling; bounded reconnect backoff; stream-generation changes after reconnect; decoder health history; and a backend-controlled JPEG preview. Preview and analysis consumers share one capture worker per active camera; idle capture closes when unused.

**Why it matters:** the design does not need to pull every registered stream at once. It also avoids treating arrival time or reported FPS as the original media clock. Raw stream URLs and credentials stay on the server side.

**Verified locally:** owned RTSP/HLS tests, interruption/recovery, PTS and browser preview. Real Government codec/network behavior remains pending.

### 4. Operator authentication and scoped access

**Implemented:** local operator/department key login, HttpOnly session cookie, CSRF on browser writes, department filtering of cameras and dependent evidence, and operator-only actions where required. Source URLs are withheld from normal camera API responses.

**Why it matters:** the GIS and evidence flow is permission aware from the API, rather than depending on hidden UI controls. The prototype key/session design still needs approved identity and service security for production.

## Module 2: real-frame plate intelligence and alerting

### 5. Bounded frame sampling and observable inference

**Implemented:** a latest-frame sampler that consumes decoded packets with camera ID, PTS, timebase, generation and source mode. It records received, selected, analyzed and dropped frames, inference provider, and actual applied rate. A slow model skips old frames instead of silently building a long queue.

**Distinctive contribution:** operators can tell how much video the recognizer processed. The same counters feed Active Pursuit and the coverage ledger, so requested work cannot masquerade as delivered analysis.

### 6. Plate detection, OCR and cautious confirmation

**Implemented:** pinned FastALPR detector/OCR pair on actual decoded owned frames; raw and normalized plate text; model scores/version; repeated-reading confirmation; a Gujarat-format gate; and review candidates for ambiguous results such as O/0. Repeated same-plate frames from one encounter are grouped.

**Why it matters:** a single OCR guess does not automatically become a law-enforcement-style confirmed hit. The synthetic O/0 case exposed a real model ambiguity; the system keeps it for review rather than silently rewriting it.

**Verified locally:** owned RTSP model smoke using FastALPR's official sample and synthetic plate tests. No Indian-road exact-plate accuracy, false-positive or miss rate is claimed.

### 7. Evidence-backed sightings and integrity checks

**Implemented:** persisted sighting ID, camera, source PTS/generation, raw readings, confidence, model version, review status, best evidence crop and SHA-256 hash. Evidence access is authenticated; missing or altered evidence yields an explicit error. Sightings remain searchable after restart.

**Distinctive contribution:** journey points and alerts link back to inspectable source evidence and its hash, not to a transient UI annotation.

### 8. Representative watchlist alerts

**Implemented:** add/list/disable watchlist entries with expiry, exact matching of confirmed reads, a deduplication window, persisted alerts, authenticated live server-sent event delivery, acknowledgement and history. Records are committed before notifications are sent.

**Boundary:** this is a representative team-managed watchlist. It is **not** connected to an official police or vehicle database.

## Module 3: evidence journey and review

### 9. Historical designated-registration search

**Implemented:** a saved plate pursuit/query that searches sightings made before the search began. The result retains camera, location, source type, raw/normalized text, evidence and review state. Queries and results survive restart.

**Why it matters:** an evaluator can supply a plate after its appearance; the app is not limited to alerts that were preconfigured in the watchlist.

### 10. Evidence Journey map with observed and inferred elements

**Implemented:** observed sightings as evidence-linked map points; possible cross-camera connections shown as inferred; reviewer confirmation/correction/rejection; preserved original OCR and audit history; and warnings for implausible jumps when suitable timing evidence exists.

**Distinctive contribution:** the interface distinguishes *where a camera actually saw the target* from a proposed movement between cameras. It does not draw a straight GIS segment and call it the road route.

### 11. Honest cross-camera time handling

**Implemented:** each sighting carries source PTS/timebase, stream generation and timestamp provenance. A verified PTS-to-UTC mapping can be attached to the current generation; without it, the journey labels time order approximate and blocks precise travel-time conclusions. A reconnect invalidates an older generation's mapping.

**Why it matters:** one camera's monotonic PTS cannot be compared to another camera's PTS without a shared UTC anchor. This explicit clock contract makes route claims safer and more technically credible.

### 12. Evidence report and reviewer audit trail

**Implemented:** a downloadable PDF from the same persisted journey payload used by the UI. It includes observed/inferred status, timing provenance, evidence hashes, reviews and coverage information. The reviewer can change a conclusion without deleting the original sighting.

**Boundary:** a report is only as strong as the footage, recognition and timestamp evidence supplied to it. A Government-feed report has not been generated.

## Module 4: Active Pursuit and Coverage Integrity

### 13. Measured capacity before scheduling

**Implemented:** an end-to-end owned-feed benchmark record and a scheduling ceiling at 70% of observed sustainable analyzed fps, leaving 30% headroom for decode, API, UI and spikes. The scheduler accounts for existing manual worker reservations and refuses to silently exceed the budget.

**Evidence:** the recorded two-feed laptop run measured **12.067 analyzed fps** and stored an **8.447 fps** ceiling under that feed mix and host. This is a narrow local calibration, not a capacity claim for Government infrastructure or 80,000 simultaneous streams. See the [raw benchmark](../output/benchmarks/module4_owned_pipeline.json).

### 14. Confirmed-sighting Active Pursuit

**Implemented:** transparent ranking of eligible cameras after the latest confirmed sighting using current feed health, straight-line proximity, resolution as an uncalibrated readability/cost proxy and measured queue age when available. Schedule revisions include reason, inputs, requested rates, worker applied-rate acknowledgements and counters. A feed outage or new confirmed hit can change the allocation.

**Distinctive contribution:** it uses a limited measured frame budget to look harder where there is an evidence-supported reason, while leaving multiple candidates and uncovered cameras visible. The ranking is a heuristic, **not** a calibrated route probability or road ETA.

### 15. Coverage Integrity Ledger

**Implemented:** per-pursuit, per-camera, per-window planned/received/analyzed counts, health and errors, with four outcomes: `observed`, `not observed in sampled frames`, `feed unavailable`, and `insufficient coverage`. Window counter baselines prevent later work from inflating old coverage. The dashboard and report show these states.

**Why it matters:** a negative result is explicitly limited to the frames actually analyzed. A camera outside the worker budget or down during the window becomes a visible coverage gap.

### 16. Deployment HLD and scale calculation

**Implemented as documentation and tools:** a regional architecture HLD, a staged pilot path, sizing equations and local benchmarking scripts. The design separates an 80,000-camera **registry** from the much smaller active subset whose streams are actually opened and analyzed.

**Boundary:** regional PostgreSQL/PostGIS, durable event bus, KMS, encrypted evidence store, identity integration and failover are proposed production components, not completed deployment features. See the [HLD](MODULE4_HLD.md) and [production gate](PRODUCTION_GATE.md).

## Five integrated differentiators

### 17. Search Proof: signed record of the search

**Implemented:** an operator can freeze a pursuit into signed JSON and PDF receipts. The snapshot records search scope, eligible cameras, health/PTS/generation, analyzed counts and schedule-window coverage, skipped/unavailable gaps, matching sightings, model versions, evidence hashes, alerts and reviews. Ed25519 signatures and a public-key endpoint support verification; an independent script detects changes to exported files. The signing key persists across local restarts.

**Why it is distinctive:** the receipt makes the *quality of the search itself* inspectable. A reviewer can see both findings and missing coverage, and tampering with the exported record fails verification. It never claims that zero hits prove the vehicle absent from unsampled video.

**Verified locally:** JSON/PDF signatures, tamper failure, restart, no source URL disclosure and gap wording. Production needs approved KMS/HSM, key rotation, trusted timestamping and retention.

### 18. Department-scoped regional query agents

**Implemented:** a separate regional service with its own database and configured department scope; central fan-out searches only configured agents and returns permitted hit metadata. The agent refuses requests outside its department. Source video, crops and URLs are excluded from the federated response. Partial failures or no configured permitted agents produce `complete=false`.

**Why it is distinctive:** the centre can coordinate a multi-department search without requiring every raw stream to be copied to one server. The scope and incomplete-result semantics remain visible.

**Verified locally:** two isolated agent databases, scoped fan-out, cross-department denial and failure cases. Independent network deployments, mTLS and a Government departmental pilot remain to be tested.

### 19. Shadow pursuit scheduler and one-slot exploration

**Implemented:** each active schedule revision records the applied adaptive camera choice and a rotating uniform **counterfactual decision** under the same FPS and camera-slot budget. The comparison uses one capture per camera. The operator can enable one exploration slot for a lower-ranked eligible camera; the preference persists and does not raise total requested FPS.

**Why it is distinctive:** rather than declaring that adaptive scheduling always wins, SakhyaPath exposes where its choices differ from a fair baseline and deliberately samples outside its strongest route guess. This creates a testable hypothesis for multiple annotated route replays.

**Boundary:** a shadow decision is not a second inference run. Improvement in target reacquisition remains unproven until equal-budget outcome tests are repeated on annotated routes.

### 20. Camera and clock trust scorecard

**Implemented:** a per-camera inspection endpoint and UI card combining catalogue presence, recent decoded-frame health, codec/resolution, measured FPS and PTS intervals, discontinuities, stream generation, queue age, worker state and any current attested UTC mapping. Precise cross-camera timing stays blocked if the mapping is absent or too uncertain.

**Why it is distinctive:** operators see whether each camera is truly useful for recognition and whether its timing can support a route conclusion. Connectivity, decode quality and clock trust are separate facts.

**Verified locally:** owned RTSP PTS statistics, trust UI, reconnect/generation behavior and blocked precise timing without mapping. Source-side Government clock attestation is pending.

### 21. Low-connectivity regional metadata mode

**Implemented:** a regional SQLite outbox holds strictly allowed sighting and feed-health metadata when the central connection fails. A background loop retries delivery; stable IDs make central ingestion idempotent. Pending counts and gaps are visible, and the central UI does not pretend to know events still queued remotely. Video URLs or extra fields are rejected by the event schema.

**Why it is distinctive:** intermittent wide-area links do not have to stop bounded local analysis, and recovery does not silently duplicate events or erase the outage. The gap is part of the investigation record.

**Verified locally:** simulated outage, automatic retry, persistence across restart, duplicate acknowledgement and forbidden-field rejection. A real two-process WAN partition, durable production queue and failover remain to be tested.

## One coherent user workflow

1. Sign in and inspect registered cameras on the Gujarat GIS map. Choose only authorised feeds.
2. Open a preview or start analysis; actual decoded frames, not catalogue flags, establish live health.
3. The recognizer processes selected frames and stores evidence-backed plate sightings; confirmed exact matches can create representative watchlist alerts.
4. Search a designated plate, including past sightings. Inspect observed journey points, uncertain links, source timing and reviewer decisions.
5. Run Active Pursuit from a confirmed sighting. Watch a measured budget shift, an exploration slot and the uniform shadow choice without adding another capture.
6. Inspect four-state coverage, camera/clock trust, regional partial responses and any outage gap.
7. Export the journey report and signed Search Proof; independently verify the receipt and show exactly which frames and cameras the result covers.

This is the demonstration story to use in slides or a 2-3 minute owned-feed recording. Every screenshot should label the source as owned, replay or Government live **only when that source really was used**.

## Why this is a stronger hackathon story

| Common weak claim | What SakhyaPath can demonstrate locally |
| --- | --- |
| “We integrated every camera.” | Registry count is separate from decoded, viewed and analyzed counts. |
| “No alert means the vehicle was absent.” | Search Proof and the coverage ledger show analyzed frames and gaps. |
| “Our AI knows the vehicle route.” | Observed sightings are linked to evidence; connections and time uncertainty are labelled. |
| “Adaptive AI is always better.” | Equal-budget shadow choices and exploration are visible; real outcome superiority must be measured. |
| “All video should go to a central server.” | Regional agents return scoped metadata; video can remain near the authorised source. |
| “Offline regions are invisible until they recover.” | Bounded metadata outbox, retry, idempotent replay and explicit incomplete status. |

The distinctive pitch is **evidence-backed search plus honest coverage plus measured pursuit**, packaged for a regional CCTV estate. It is technically interesting because the features constrain one another: timestamps limit route claims, inference counters limit coverage claims, reviewer state limits pursuit anchors, and regional scope limits what the centre can retrieve.

## Current limits and the precise next proof

1. **Government-feed access:** the organiser has not supplied the authorised Sentinel origin and access method. The read-only adapter has passed stub tests only. A private live test must record discovered, connected, viewed and analyzed counts.
2. **Indian-road accuracy:** the local model smoke and synthetic plate examples do not supply an exact-plate accuracy, miss or false-positive rate. Use permission-cleared annotated data or organiser-approved derived scoring.
3. **Cross-camera clock:** do not claim precise route travel times until a shared UTC mapping and uncertainty are verified for each relevant stream generation.
4. **Adaptive outcome:** the scheduling comparison includes decision logs and limited recorded examples; several reset, annotated, equal-budget routes are needed for a credible benefit claim.
5. **Production deployment:** SQLite, local files, process-local capture/sessions, one active pursuit and a default four-camera analysis cap are prototype choices. Regional database, event durability, identity, encryption, retention, monitoring and restore/failover require a staged pilot.
6. **Current localhost process:** at the last verification, the process on port 8000 served old routes. Restart that process with its current operator key, database path and other environment variables preserved before demonstrating the new features there.

## Evidence and source links

- [Integrated verification report](VERIFICATION_REPORT_2026-09-28.md) - exact local pass record and limitations.
- [Advanced feature implementation log](FEATURE_IMPLEMENTATION_LOG.md) - detailed API flow, demo and slide claim for the five differentiators.
- [Four-module implementation plan](../SakhyaPath_4_module_implementation_plan.md) - acceptance gates across Modules 1-4.
- [Teammate PRD](SakhyaPath_PRD_Team_Handoff.md) - requirements, roles, architecture and work packages.
- [Hackathon source index](../hackathon_source_index/README.md) and [Sentinel reference index](../sentinel_source_index/README.md) - supplied external requirements, which are constraints rather than proof of our integration.

**Ready-to-share summary:** “SakhyaPath is a working local prototype that turns CCTV vehicle search into an auditable investigation. It connects real owned streams, plate evidence, reviewer decisions, measured adaptive sampling and honest coverage into one workflow. Its signed Search Proof and regional metadata model make the result inspectable and give the design a credible deployment path. Government-feed compatibility, Indian-road recognition quality and production scale still require the organiser's private live evaluation and a measured pilot.”
