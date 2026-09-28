# SakhyaPath submission readiness

**Evidence date:** 28 September 2026. This file separates working local evidence from inputs that have not been supplied. The [source index](../hackathon_source_index/README.md) records the hackathon brief and its page/line locations; the [Sentinel index](../sentinel_source_index/README.md) records the live-feed rules. Attached references describe constraints, not proof of our own integration.

## What is ready now

| Item | Current evidence | Status |
|---|---|---|
| Mandatory Model 1 registry and GIS | Authenticated camera registry/map, owned RTSP/HLS capture and preview, read-only `GET /api/ingest` adapter exercised with a stub | Local implementation |
| ANPR and representative watchlist | Real FastALPR official sample on owned RTSP replay, persisted sightings/crops/hashes, exact-match alert, audit and review flow | Local implementation |
| Designated registration search | Historical query, observed GIS points, inferred links, reviewer corrections, PDF; three-camera annotated **fixture** | Local implementation |
| Active Pursuit and ledger | Measured budget, applied worker rates, schedule revisions, real counters and four ledger states | Local implementation |
| HLD and scale explanation | [Deployment HLD](MODULE4_HLD.md), [production gate](PRODUCTION_GATE.md), [scenario calculator](../scripts/capacity_plan.py) | Design, not deployment |
| Pitch presentation | [Live-only SakhyaPath pitch deck](../output/presentation/SakhyaPath_Hackathon_Pitch_LiveOnly.pptx) | Prepared; private evaluation pending |
| Source handoff | [Offline readiness ZIP](../output/package/SakhyaPath_Offline_Readiness_Package.zip) with SHA-256 manifest, rebuildable via [bundle script](../scripts/build_source_bundle.py) | Prepared; no hosted code link yet |

On 28 September, the full local suite passed **23 tests** and the frontend production build passed. The local two-feed owned replay benchmark in [module4_owned_pipeline.json](../output/benchmarks/module4_owned_pipeline.json) measured 249 analyzed frames in 20.634 seconds, 12.067 observed analyzed fps and an 8.447 fps scheduler budget after the 30% reserve. It is **not** a measurement on Government cameras. The controlled equal-budget comparison in [module4_equal_budget_comparison.json](../output/benchmarks/module4_equal_budget_comparison.json) has a mixed outcome. Neither establishes an Indian-road accuracy rate or universal adaptive benefit.

## What is pending and the exact completion test

1. **Sentinel access.** Obtain approved account access and the organiser-supplied catalogue origin and authentication. See [the live-only readiness check](SENTINEL_OFFLINE_READINESS.md) and [access procedure](SENTINEL_ACCESS_AND_LIVE_GATE.md). A pending-access stub is saved at `output/benchmarks/sentinel_preflight.json`; an authorised preflight defaults to ignored `backend/data/sentinel_preflight.json`. At evaluation, record actual decoded/viewed/analyzed/concurrent counts. Do not treat a catalogue `live` flag as a decoded frame.
2. **Indian-plate quality.** The organiser will test with private live footage. If the team independently obtains permission-cleared annotated images, [the holdout tool](../scripts/evaluate_holdout.py) can measure exact-plate precision/recall, misses and false reads by condition; it does not require or request Government recordings. During the private evaluation, ask for the organiser's ground-truth scoring or approved derived metrics. A frame-to-alert latency claim needs verified event UTC.
3. **Cross-camera route.** Keep route timestamps approximate until the organiser verifies a shared UTC mapping for each stream generation. The optional [recorded comparison tool](../scripts/compare_recorded_sampling.py) applies only to team-owned or independently approved data. For private Government feeds, demonstrate the route and uncertainty live to evaluators without copying their footage.
4. **Operational own-feed video, 2–3 minutes.** Record the real application processing a team-controlled live/replay feed, not slides or a simulated UI. Use [the demo shot list](DEMO_AND_LINK_CHECKLIST.md). An official model sample replay can prove wiring but not Gujarat-road quality. No final recording is present yet.
5. **Government-feed evaluation.** The organiser tests the live client with private feeds and target vehicles. Show catalogue onboarding, real preview/analysis, timed plate results and a derived report in the approved environment. Record or export Government media only when the organiser permits it; otherwise ask what redacted report or live demonstration satisfies the brief's video requirement. No Government video or report is present here.
6. **Submission links.** Upload the deck, HLD, code and the owned-feed demo to the approved destination. Include Government-derived results or a live-test recording only through the organiser-approved route. Test each viewer link in a private window with no project credentials. Create a repository remote only in an account the user controls. No repository remote or public links exist in this workspace today.

## Factual boundaries for the presentation

- The ~50-feed test is an **upcoming authorised evaluation**, not an achieved feed count.
- The ~80,000-camera design is a regional architecture and sizing exercise, not a demonstrated deployment.
- Source PTS establishes per-stream media order; a cross-camera UTC timeline requires verified mapping.
- The present ranking uses straight-line distance and an uncalibrated resolution readability proxy. Queue age is measured locally. No destination probability or road ETA is claimed.
- A negative coverage window means only that the target was not observed in the sampled frames.
- The demonstration uses a representative watchlist; there is no official police or vehicle-database connector.

## Ready-to-run commands

```powershell
$env:SAKHYAPATH_CUDA_DLL_DIR = 'path-to-local-Torch-DLL-directory'
.\.venv\Scripts\python -m pytest -q
npm run build --prefix frontend
.\.venv\Scripts\python scripts/sentinel_preflight.py
.\.venv\Scripts\python scripts/capacity_plan.py --registered 50 --active-fraction 0.2 --sample-fps 1 --bitrate-mbps 2
```

The current preflight deliberately reports `pending_access` until the authorised origin is configured. The capacity example assumes 20% concurrent activity and 2 Mb/s per feed; replace both with measured pilot values. See [production gate](PRODUCTION_GATE.md) before describing the system as deployable for Government operations.
