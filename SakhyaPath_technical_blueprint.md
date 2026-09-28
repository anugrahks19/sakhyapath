# SakhyaPath technical blueprint

**Status:** design and build instructions with an integrated local implementation of Modules 1–4. The module runbooks record owned-feed tests and the measured laptop benchmark. Actual Government-feed integration, Indian-plate quality, a verified live cross-camera route, and production security/scale have not been verified. See [docs/SUBMISSION_READINESS.md](docs/SUBMISSION_READINESS.md) for the evidence boundary.

The implementation is divided into four gated modules in [SakhyaPath_4_module_implementation_plan.md](SakhyaPath_4_module_implementation_plan.md). That plan defines deliverables, interfaces, test evidence, and completion criteria for each module.

**Competition selection:** Hybrid / Innovative Architecture, with the mandatory Model 1 CCTV registry and GIS foundation. The solution adds Model 2 unified viewing and selective analytics plus Model 3-style source adapters. The source requirements are indexed in [hackathon_source_index/README.md](hackathon_source_index/README.md), especially the approximately 50-camera test, designated-vehicle route, live watchlist alerts, deliverables, and approximately 80,000-camera scale plan.

## 1. What the product does

SakhyaPath connects existing departmental camera feeds without replacing their VMS or storage. It watches a measured number of frames from each accessible feed, recognizes vehicle plates, records sightings with source evidence, and compares accepted sightings with a representative watchlist. An operator can search a registration number to see where it was actually observed and the plausible travel segments between those observations.

Its active pursuit engine then asks a practical question: **which working cameras are worth analyzing more intensively now?** It ranks candidate cameras from the last confirmed location and time, reallocates a fixed GPU frame budget, and updates the ranking after each new sighting. This is a search priority, not a claim to know the vehicle's destination.

The distinctive extra is the **Coverage Integrity Ledger**. For each camera considered during the pursuit, it records whether the feed was online, whether frames arrived, whether the planned number of frames was analyzed, and whether a useful plate could be read. Thus the interface can say “not observed in sampled frames,” “feed unavailable,” or “coverage insufficient.” It never equates a missed detection with proof of absence.

The three visible outputs are:

1. **Evidence Journey:** timestamped observed sightings and separately marked inferred travel segments.
2. **Live Pursuit:** ranked next cameras, current sampling allocation, new sightings, and alerts.
3. **Coverage Integrity:** what the system actually checked, what failed, and where investigation remains uncertain.

## 2. Requirements and prototype proof

| Brief requirement | Prototype proof | Production direction |
|---|---|---|
| Model 1 registry and GIS | Bulk import, camera list/map, department, coordinates, owner, protocol, status, audit timestamp | PostGIS asset inventory and department-scoped workflows |
| Heterogeneous integration | Two working source types initially: RTSP and HLS or local replay; adapter interface for Government/VMS APIs | ONVIF/vendor SDK adapters, secure regional gateways |
| Unified viewing | Browser view for an authorized operator, camera health, searchable grid | Regional stream relays and controlled on-demand viewing |
| Continuous analytics | Measured baseline sampling and ANPR on every actively monitored feed | Camera substreams/motion events plus regional GPU workers |
| Watchlist and alerts | Representative watchlist, automatic exact-match alert, acknowledgement | Authorized database connectors, stronger identity and audit controls |
| Designated-vehicle test | Search the supplied number; show time/location sequence, evidence, GIS, report | Scalable cross-region sighting index |
| Approximately 50 feeds | Import and test every accessible feed; report how many were viewed and analyzed concurrently | Add regional workers using measured capacity |
| Approximately 80,000-camera plan | HLD with throughput, bandwidth, storage, security, rollout, and cost assumptions | Phased on-premises or Government-approved regional deployment |

The prototype must be an operational backend, not a mock-up. It must label owned or replayed footage as such. Government-feed performance is reported only after actual access and testing.

## 3. Logical architecture

~~~mermaid
flowchart LR
  A["Department cameras / VMS / replay"] --> B["Source adapters and MediaMTX relay"]
  B --> C["Browser viewer"]
  B --> D["Frame sampler and health monitor"]
  D --> E["GPU ANPR worker"]
  E --> F["Multi-frame plate fusion"]
  F --> G["Sighting and evidence store"]
  G --> H["Watchlist matcher and alerts"]
  G --> I["Evidence Journey service"]
  G --> J["Active Pursuit scheduler"]
  D --> K["Coverage Integrity Ledger"]
  J --> D
  J --> K
  H --> L["Operator dashboard / reports"]
  I --> L
  K --> L
  M["Camera registry + GIS"] --> B
  M --> I
  M --> J
  M --> L
~~~

The video path and event path are separate. Existing source systems keep their recordings. MediaMTX provides a single stream relay and browser-friendly output. The sampler reads from that relay; it does not create a second camera login when avoidable. Video frames are processed near the source in a future regional deployment. Only compact event records and selected evidence cross to the central service.

**48-hour stack:** native Windows FFmpeg and MediaMTX; Python/FastAPI, FastALPR with ONNX GPU, SQLite in WAL mode, a local evidence directory, React and Leaflet. This matches the current Windows laptop and RTX 4060 8 GB GPU; Docker and local PostgreSQL were not found in the workspace inspection. Use the same API and event shapes when moving to PostgreSQL/PostGIS, a durable event bus, and object storage later.

**Why these components:** MediaMTX documents RTSP/HLS/WebRTC proxying and Windows support; FastALPR documents Windows NVIDIA GPU inference. Their default models still require validation on the actual Gujarat camera angles and Indian plates. The chosen stack is a starting implementation, not a recognition-accuracy guarantee.

**Sentinel sandbox adapter (new supplied reference):** discover cameras and the actual RTSP, WHEP, and HLS URLs through the read-only `GET /api/ingest` catalogue; do not hard-code camera IDs or assume identical codecs, resolution, frame rates, or bitrate. Force RTSP over TCP for inference; use HLS when port 8554 is blocked. Consume only the streams needed by the current measured analytics schedule, and close idle captures because every client receives a separate copy. The Sentinel gateway is consume-only: never publish to it, request a bulk footage download, or call **its** control API. A MediaMTX relay owned by SakhyaPath is separate from the Sentinel gateway. The full indexed reference and its line citations are in [sentinel_source_index/README.md](sentinel_source_index/README.md).

## 4. Component contracts and data records

### Camera registry

Each camera record contains: stable camera ID, department, display name, latitude/longitude, source type, source endpoint without embedded password, secret reference, viewer path, analytics enabled flag, last frame time, health state, measured effective frame rate, and optional notes on placement and plate readability. A source adapter must expose probe, start, stop, health, and frame-timestamp operations. The first concrete adapters are RTSP and HLS/replay; an ONVIF or vendor adapter is added only when the supplied feed requires it.

Health is **online** when frames arrive within the configured timeout, **degraded** when frames arrive intermittently or decode errors rise, and **offline** when frames stop. A camera can be online yet unsuitable for plate reading; these are separate states.

### Sighting and evidence

Store a unique sighting ID, camera ID, source mode (live or replay), source presentation timestamp if available, UTC receive time, timestamp provenance, raw OCR string, normalized plate string, detector score, OCR score, model version, evidence image path, SHA-256 hash of the saved evidence, and review status. Preserve the raw OCR output even if normalization changes it. Do not overwrite a sighting when a reviewer corrects it; append a correction/audit record. On Sentinel feeds, source PTS drives inter-frame timing; reported FPS and frame-arrival times cannot serve as the motion timebase. Since the supplied reference does not define a shared PTS-to-UTC mapping across cameras, cross-camera order and UTC report timestamps require a verified synchronization method or an explicit uncertainty label.

Normalize plate strings by uppercasing and removing spaces and punctuation. Do not discard nonstandard plates through a strict Gujarat-only format rule. Possible OCR substitutions such as O/0 or I/1 can generate review candidates, but must not silently create a confirmed watchlist hit.

Group repeated readings of the same plate at the same camera over a short configurable window into one sighting and retain the best evidence crop plus the individual reads. This prevents an alert flood when a vehicle pauses.

### Watchlist, alert, and pursuit

A watchlist entry holds normalized plate, category, source label, creation/expiry times, active flag, and authorized owner. The demo uses representative data; official database connectors are interface definitions until access is granted. An alert links the watchlist entry and sighting, stores creation time, match basis, status (new, acknowledged, closed), and actor history. An alert is investigative information, not automatic enforcement.

A pursuit holds target plate, creation time, operator, last confirmed sighting, current state, and ranked candidate cameras. Its journey contains observed sightings and separately stored candidate travel links; it must be possible to remove or reject a bad link without deleting source evidence.

### Coverage Integrity Ledger

One ledger record covers one pursuit, one camera, and one expected time window. Store planned sample rate, frames received, frames actually analyzed, feed health, decode error count, camera quality estimate, any target observation, and a reason code. The UI labels the result as **observed**, **not observed in sampled frames**, **feed unavailable**, or **insufficient coverage**. The last three labels do not establish where the vehicle was.

### Minimum application interfaces

- Cameras: bulk import/list/detail/health and authorized viewing URL.
- Watchlist: create/list/disable representative entries.
- Sightings: search by normalized plate, time, camera, and review status.
- Pursuits: start by registration number; read observed journey and ranked next cameras; acknowledge or reject a candidate sighting.
- Alerts: live event stream plus acknowledgement.
- Reports: export timestamped sighting table, route map data, evidence references, and coverage ledger.

Use a versioned JSON API. Never send stream credentials or local evidence file paths to an unauthorized client. The viewer receives a server-controlled path or short-lived access token.

### Suggested implementation layout and start order

Keep the source index and planning documents separate from application code. A practical layout is:

~~~text
backend/
  app/
    api/             cameras, watchlist, sightings, pursuits, alerts, reports
    domain/          typed records and pursuit/coverage rules
    ingest/          RTSP, HLS, replay adapters and health probes
    vision/          sampler, ANPR, multi-frame fusion
    services/        matching, journey, scheduler, ledger, audit
    storage/         SQLite repositories and evidence files
frontend/
  src/               camera map, viewer, alerts, journey, pursuit, ledger
scripts/             sample-feed launcher, camera importer, benchmark, report export
tests/               fixture clips, expected sightings, negative cases
docs/                HLD, benchmark results, demo script, submission checklist
~~~

Define the event record once in the domain layer; ingestion, matching, journey, and reports must all use the same camera ID, time fields, plate normalization, and source-mode values. This prevents the dashboard from showing a different route from the exported report.

Implement the API in this order: camera import/list/health; sighting creation/search; watchlist match and alert stream; pursuit creation/detail; coverage windows; report export. Example paths are POST /api/v1/cameras/import, GET /api/v1/cameras, GET /api/v1/sightings, POST /api/v1/pursuits, GET /api/v1/pursuits/{id}, GET /api/v1/alerts/stream, and GET /api/v1/pursuits/{id}/report. Camera and watchlist writes require an authorized role. Pursuit reads must not expose evidence from a department the operator cannot view.

At startup, validate configuration and GPU provider, start the database/API, start MediaMTX, probe the source paths, then start sampler workers. The UI should connect only after the API health endpoint is ready. If GPU inference falls back to CPU, show that state visibly and rerun the throughput benchmark before claiming capacity. Pin dependency versions after the first working installation so a later package update cannot break the demo.

## 5. Exact data flow

### A. Camera onboarding

1. Import metadata and validate camera ID, department, coordinates, source type, and endpoint format.
2. Keep credentials outside the UI and source CSV. Probe a source using its adapter.
3. Register its MediaMTX path and verify that one decoded frame arrives.
4. Mark the camera on the GIS map with its real health state. Do not display an imported record as a connected feed.
5. Start or pause baseline analytics according to the measured worker budget. Log the actual schedule in the ledger.

### B. Continuous detection

1. FFmpeg or the decoder reads from the relay and emits frames retaining source PTS at the assigned sampling rate. Use actual PTS deltas for tracking; tolerate bursty arrival, irregular frame intervals, a feed restart, join-time H.264/H.265 decoder warnings, and a hard scene cut when a Sentinel feed loops. Reconnect with bounded exponential backoff, approximately 2–30 seconds.
2. A bounded latest-frame queue drops stale frames rather than allowing minutes of hidden backlog.
3. FastALPR returns plate boxes, text, and confidence. Multi-frame fusion combines consecutive reads of the same plate.
4. Persist the sighting and hashed evidence image. Record both media timestamp and receive timestamp, with provenance.
5. Compare accepted normalized text with active watchlist entries. A strong exact match creates an alert; weaker or fuzzy results remain candidates for review.
6. Push alert and sighting updates to the dashboard and update relevant pursuits.

### C. Historical vehicle search

1. The operator enters a plate. Search indexed sightings first, including sightings from before the query was started.
2. Deduplicate nearby readings and order by event time. Check whether each cross-camera transition is physically plausible using coordinate distance and configurable travel-time bounds.
3. Draw solid markers for observed evidence and dashed links for inferred travel. Split implausible sequences into separate hypotheses.
4. Show source image, time, camera, raw/normalized OCR, confidence, and review state for every observed point.

### D. Active pursuit

1. Start from the latest **confirmed** sighting. Consider healthy cameras in a plausible arrival window. When the direction is unknown, keep candidates in multiple directions.
2. Rank candidates by travel feasibility, camera health, historic plate-read quality, current queue delay, and GPU cost. Display the reasons; do not present an uncalibrated score as a probability.
3. Keep baseline sampling on the rest of the active camera set. Allocate the spare frame budget to the highest-ranked cameras. The worker acknowledges the schedule it actually applied.
4. On a new confirmed sighting, update candidate rankings and the evidence journey. If a camera goes offline, reallocate effort and mark the gap.
5. At the end of an arrival window, write its coverage-ledger result. No detection is only “not observed in sampled frames” when the feed and sampler were functioning adequately.

### E. Reporting

The report includes the searched registration number, UTC and displayed local time zone, ordered observed sightings, possible route links, alert history, per-camera coverage results, model version, evidence hashes, and any operator corrections. It identifies replayed versus live sources. Do not call the route complete when evidence has gaps.

## 6. Active scheduling rules for the first build

Measure the sustained end-to-end frame processing rate on the laptop using representative frame sizes. Reserve at least 30% headroom for decoding, API, UI, and latency spikes. Let the remaining measured rate be the scheduling budget.

Start with a low baseline rate across active cameras and use the rest for the top ranked pursuit candidates. A suggested trial is 0.2 frames/second per camera baseline and up to 2 frames/second for priority cameras; these are **trial settings**, not promises. If the measured budget cannot support the baseline, show a degraded coverage state and reduce the number of active cameras or add a worker. Never claim all 50 feeds are continuously analyzed at a rate that was not measured.

For the first prototype, travel feasibility uses the straight-line camera distance as a **lower bound** and broad configurable speed/time bounds. It does not claim to know an exact road route. A later regional deployment may use offline road-network travel times and learned camera transitions.

The scheduler must be deterministic and logged: given the same sightings, camera health, and budget, it should produce the same ranked candidates and sample-rate plan. This makes the bonus capability testable and explainable.

## 7. Security, privacy, and operations

**Prototype:** bind services to localhost or a controlled demo network; require an operator login; use role checks for registry edits, watchlist changes, and evidence access; keep source credentials in an environment/config secret store; redact secrets in logs; restrict MediaMTX paths and its control API; hash evidence files; record important user actions. Do not expose Government stream URLs through browser JavaScript or a public repository.

**Production:** department-scoped identity integration, TLS between services, encrypted secret management, network segmentation, regional access controls, audit retention, incident response, backup/restore, and disaster recovery. Separate VMS viewing rights from analytics rights. Define authorized retention periods with the relevant department before retaining video or evidence. Only approved connectors should access VAHAN, SARTHI, eGujCop, AFIS, or NAFIS; a hackathon representative watchlist does not constitute integration with those databases.

**Monitoring:** per-camera last-frame age, decode failures, stream reconnects, sampled frames, analyzed frames, GPU memory/latency, queue age, alert latency, and evidence-store errors. An offline camera or saturated worker must be visible in the UI and report; silent failure invalidates the coverage claim.

## 8. Statewide design and sizing

Run source adapters, relay, and GPU inference in regional or departmental zones. The central platform holds the registry, sightings, watchlists, alerts, pursuit state, and GIS. Regional workers send compact signed or authenticated event records; authorized operators retrieve video on demand from the relevant zone. Existing departmental recording and retention remain in place unless a separate policy requires change.

Size the network and hardware from measurement:

- Required inference frames/second = sum of each camera's scheduled frames/second, including priority bursts.
- Worker count = ceiling(required rate / (measured sustainable worker rate × target utilization)). Use target utilization no higher than 0.7 until load tests justify otherwise.
- Example only: 80,000 cameras at 2 Mb/s would represent 160 Gb/s of continuous raw video and about 12.1 PB for seven days of central recording, before replicas and overhead. The hybrid design avoids assuming all of that video must traverse a central link.
- Estimate hot/warm/cold storage separately for existing departmental video, selected evidence crops/clips, and central event metadata. State the assumed retention periods and costs.

Roll out in gates: a measured 50-feed pilot, then a multi-department regional pilot, then successive regional expansion. Advance only after interoperability, alert quality, recovery, security, and capacity tests pass. An approximately 80,000-camera plan is not an approximately 80,000-camera achievement.

## 9. Two-person, 48-hour build instructions

| Window | Owner A: video/analytics | Owner B: app/GIS | Gate |
|---|---|---|---|
| 0–4 h | Verify FFmpeg, GPU runtime, model on one owned clip | Create app skeleton, camera schema, map | A real plate result and one camera visible |
| 4–12 h | RTSP and second source adapter; health and frame timestamps | Bulk import, camera list/map, viewing | Two distinct working source types |
| 12–22 h | Multi-frame OCR, dedup, evidence save, watchlist event | Sightings, watchlist, alerts UI/API | Real watchlist hit reaches UI |
| 22–30 h | Measure processing budget and expose sample-rate control | Historical journey and route report | Three observed points with evidence |
| 30–38 h | Active ranking and schedule acknowledgements | Priority view and Coverage Integrity Ledger | Priority visibly changes after a sighting |
| 38–44 h | Government-feed integration if available; benchmark and failure cases | Review flow, report polish, HLD | Measured results and honest source labels |
| 44–48 h | Record own-feed and Government-feed demos if accessible | Presentation and submission package | Every mandatory link and report checked |

At each shift handoff, write down the current commit, commands to start services, sample feed/source used, known failures, last passing test, and the next single highest-priority task. Keep one known-good demo script and a separate experiment branch or configuration. Do not change model, streaming, database, and UI dependencies simultaneously near submission.

If time slips, finish in this order: Government/own feed operation, plate sightings, watchlist alerts, designated-vehicle route and report, registry/GIS, then active pursuit, then the ledger comparison. The unique feature cannot compensate for a missing mandatory requirement.

## 10. Verification and demonstration

**Functional acceptance:** import the accessible cameras; prove two different source types; inspect one live/replayed feed in browser; identify a plate on real footage; create an exact watchlist alert; search the evaluator's number; show at least three timestamped observed points when the footage contains them; export the report. If the target appears in fewer than three cameras, report the actual number observed.

**Quality checks:** annotate a small held-out set of clear and difficult plate frames. Report precision, recall, false positives, median/p95 processed-frame-to-alert time, and effective frames/second. State sample size and feed conditions. Never invent accuracy percentages.

**Distinctive-feature test:** replay the same recorded multi-camera scenario twice with the same measured GPU frame budget. First use uniform sampling, then active pursuit. Compare time to next valid sighting, frames processed, missed targets, and coverage gaps. The first run must not be silently pre-indexed for the second run; reset run-specific state between comparisons.

**Failure tests:** one feed disconnects/reconnects, one camera is online but unreadable, OCR confuses similar characters, a duplicate plate persists at one camera, timestamps drift, an impossible travel jump appears, and the GPU queue saturates. The route and ledger must reflect each condition without fabricated certainty.

**Demo story:** start with the camera GIS registry; show two live source types; trigger a representative watchlist match; open the evidence journey; start active pursuit; show the top camera priority and a new sighting; disconnect or degrade another feed and show the ledger's “unknown” explanation; export the report and show measured performance.

## 11. Do and do not

### Do

- Choose Hybrid / Innovative Architecture and explicitly include mandatory Model 1.
- Build and verify the mandatory test workflow before adding the distinctive scheduler.
- Keep observed evidence, inferred routes, and operator corrections visibly separate.
- Label each source as Government live, owned live, or replay, based on what it actually is.
- Measure throughput on the RTX 4060 and disclose the tested camera count and sampling rate.
- Use a representative watchlist until authorized database access exists.
- Keep credentials, stream links, and evidence access controlled.
- Show the actual 50-feed integration status if those feeds become available.
- Put architecture diagrams, measured limits, costs, security, and roll-out gates in the HLD.

### Do not

- Claim the software or all 50 feeds are working before tests prove it.
- Claim a complete road route from camera coordinates alone.
- Treat no OCR result as proof that a vehicle did not pass a camera.
- Convert low-confidence or fuzzy OCR into an unquestioned police alert.
- Upload Government footage, stream credentials, or sensitive watchlist data to a public demo or repository without authorization.
- Present simulated UI, prerecorded animation, or a concept video as the operational backend.
- Promise 80,000-camera real-time inference on one laptop or centralize all raw video by default.
- Spend the 48 hours on facial recognition, full central VMS recording, or extra analytics before the required vehicle test works.
- Claim a guaranteed win, unique invention, or measured improvement that has not been demonstrated.

## 12. Reference material

- Supplied challenge index: [hackathon_source_index/README.md](hackathon_source_index/README.md)
- Supplied Sentinel sandbox index: [sentinel_source_index/README.md](sentinel_source_index/README.md)
- [MediaMTX introduction and protocol support](https://mediamtx.org/docs/kickoff/introduction)
- [MediaMTX configuration and authentication](https://mediamtx.org/docs/references/configuration-file)
- [ONVIF profile overview](https://www.onvif.org/profiles/)
- [FastALPR project and platform support](https://github.com/ankandrew/fast-alpr)
- [PostGIS documentation](https://postgis.net/documentation/)
