# SakhyaPath

SakhyaPath is a proposed hybrid camera-grid and evidence-backed vehicle-tracking platform for the Gujarat CCTV hackathon. **Modules 1–4 are locally implemented**: camera registry/GIS, Sentinel catalogue adapter, owned-feed RTSP/HLS preview, FastALPR plate sightings, evidence crops, representative watchlist alerts, historical registration search, evidence journey map, reviewer corrections, downloadable PDF report, measured-budget Active Pursuit, and a Coverage Integrity Ledger.

Five optional advanced features are now implemented for owned-feed testing: signed Search Proof JSON/PDF receipts, department-scoped regional query agents, a shadow uniform-versus-adaptive scheduler with bounded exploration, a camera/clock trust scorecard, and regional metadata buffering across link outages. The [feature implementation log](docs/FEATURE_IMPLEMENTATION_LOG.md) records API/data flow, exact demo steps, verification, limitations, and slide-ready claims for each.

## Run the prototype

See the [Module 4 runbook](docs/MODULE4_RUNBOOK.md) for benchmarking, scheduling, coverage and demo evidence, and the [deployment HLD](docs/MODULE4_HLD.md) for the proposed regional path. The [Module 3 runbook](docs/MODULE3_RUNBOOK.md) covers journey, clock, permission, and PDF export. The [Module 2 runbook](docs/MODULE2_RUNBOOK.md) covers installation, models, and benchmarks; the [Module 1 runbook](docs/MODULE1_RUNBOOK.md) covers feed setup and Sentinel access. The [four-module plan](SakhyaPath_4_module_implementation_plan.md) defines the gates. The [technical blueprint](SakhyaPath_technical_blueprint.md) explains the concept.

The supplied hackathon files are indexed in [hackathon_source_index](hackathon_source_index/README.md); the later Sentinel feed guide is indexed in [sentinel_source_index](sentinel_source_index/README.md).

For a teammate handoff, use the [detailed editable PRD](docs/SakhyaPath_PRD_Team_Handoff.md) or its [shareable PDF](output/pdf/SakhyaPath_PRD_Team_Handoff.pdf). The [integrated verification report](docs/VERIFICATION_REPORT_2026-09-28.md) separates passing local checks from open live and production gates.

For a feature-by-feature explanation and hackathon differentiation, share [Implemented Features and Uniqueness](docs/SakhyaPath_Implemented_Features_and_Uniqueness.md).

For a private judges-only live prototype URL, follow the [single-VM demo hosting guide](deploy/demo/README.md) and its service, environment, and HTTPS templates.
For the quickest managed always-on demo, use the [paid Render single-service guide](deploy/render/README.md); it includes a Dockerfile and persistent-disk setup.
If the backend runs on an Oracle VM and the React frontend is deployed on Vercel, use the [Vercel + Oracle split guide](deploy/demo/VERCEL_ORACLE.md).

## Submission preparation

The [readiness matrix](docs/SUBMISSION_READINESS.md) names every remaining evidence gate. The [live-only pitch deck](output/presentation/SakhyaPath_Hackathon_Pitch_LiveOnly.pptx), [HLD](docs/MODULE4_HLD.md), [Sentinel readiness check](docs/SENTINEL_OFFLINE_READINESS.md), [access procedure](docs/SENTINEL_ACCESS_AND_LIVE_GATE.md), [demo shot list](docs/DEMO_AND_LINK_CHECKLIST.md), and [production gate](docs/PRODUCTION_GATE.md) are prepared. The [offline readiness package](output/package/SakhyaPath_Offline_Readiness_Package.zip) includes source, documentation, local measurements, and the deck with a SHA-256 file manifest. The optional [Indian-plate holdout](scripts/evaluate_holdout.py) and [recorded route comparison](scripts/compare_recorded_sampling.py) tools accept only independently permission-cleared team data. **The organiser keeps Government footage private and tests our live client against it; no Government recording needs to be sent to this project.**

## Current verification boundary

The local tests use owned synthetic RTSP/HLS streams and an official FastALPR sample image. They do not establish Government-feed connectivity, Indian-road accuracy, or a deployable 80,000-camera capacity. The actual Sentinel base URL and access details were not included in the supplied files. Once authorised access is provided, configure the origin, sync `GET /api/ingest`, and repeat the live-feed and model evaluation gates without calling the Sentinel gateway's control API.
