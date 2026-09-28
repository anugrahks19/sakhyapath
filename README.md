# SakhyaPath

SakhyaPath is a proposed hybrid camera-grid and evidence-backed vehicle-tracking platform for the Gujarat CCTV hackathon. **Modules 1–4 are locally implemented**: camera registry/GIS, Sentinel catalogue adapter, owned-feed RTSP/HLS preview, FastALPR plate sightings, evidence crops, representative watchlist alerts, historical registration search, evidence journey map, reviewer corrections, downloadable PDF report, measured-budget Active Pursuit, and a Coverage Integrity Ledger.

## Run the prototype

See the [Module 4 runbook](docs/MODULE4_RUNBOOK.md) for benchmarking, scheduling, coverage and demo evidence, and the [deployment HLD](docs/MODULE4_HLD.md) for the proposed regional path. The [Module 3 runbook](docs/MODULE3_RUNBOOK.md) covers journey, clock, permission, and PDF export. The [Module 2 runbook](docs/MODULE2_RUNBOOK.md) covers installation, models, and benchmarks; the [Module 1 runbook](docs/MODULE1_RUNBOOK.md) covers feed setup and Sentinel access. The [four-module plan](SakhyaPath_4_module_implementation_plan.md) defines the gates. The [technical blueprint](SakhyaPath_technical_blueprint.md) explains the concept.

The supplied hackathon files are indexed in [hackathon_source_index](hackathon_source_index/README.md); the later Sentinel feed guide is indexed in [sentinel_source_index](sentinel_source_index/README.md).

## Submission preparation

The [readiness matrix](docs/SUBMISSION_READINESS.md) names every remaining evidence gate. The [pitch deck](output/presentation/SakhyaPath_Hackathon_Pitch.pptx), [HLD](docs/MODULE4_HLD.md), [access procedure](docs/SENTINEL_ACCESS_AND_LIVE_GATE.md), [demo shot list](docs/DEMO_AND_LINK_CHECKLIST.md), and [production gate](docs/PRODUCTION_GATE.md) are prepared. The [pre-footage package](output/package/SakhyaPath_PreFootage_Package.zip) includes source, documentation, local measurements, and the deck with a SHA-256 file manifest. The validation scripts accept future footage: [Indian-plate holdout](scripts/evaluate_holdout.py) and [recorded route comparison](scripts/compare_recorded_sampling.py). No Government or permission-cleared road footage has been supplied yet, so live-demo videos and field-quality metrics remain pending.

## Current verification boundary

The local tests use owned synthetic RTSP/HLS streams and an official FastALPR sample image. They do not establish Government-feed connectivity, Indian-road accuracy, or a deployable 80,000-camera capacity. The actual Sentinel base URL and access details were not included in the supplied files. Once authorised access is provided, configure the origin, sync `GET /api/ingest`, and repeat the live-feed and model evaluation gates without calling the Sentinel gateway's control API.
