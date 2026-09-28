# Production deployment gate

The prototype is a single-process FastAPI/SQLite app with local evidence files, process-local capture and sessions, one active pursuit, and a default four-camera analysis limit. [The HLD](MODULE4_HLD.md) describes regional deployment, but none of the controls below has been accepted by a Government operator. Use the [capacity calculator](../scripts/capacity_plan.py) for transparent scenarios, then replace every assumption with pilot measurements and local prices.

## Phased implementation

| Phase | Work | Exit evidence |
|---|---|---|
| Local submission | Keep source labels and existing four-module demo truthful; run tests and own-feed recording | Reproducible local run, report, deck and demo link |
| Authorised ~50-feed pilot | Catalogue sync, mixed codec decode, permission checks, real ANPR evaluation, concurrent-view/analysis counts | Measured per-feed quality, latency, CPU/GPU/RAM/network, error and reconnection report |
| Regional pilot | Move capture and inference near source, introduce authenticated regional gateway, PostgreSQL/PostGIS and object evidence store | Two-region failure/recovery trial, restored backup, evidence hash verification and approved retention |
| Expansion | Partition registry and events by region/time, distribute worker leases, add capacity/failover monitoring | Demonstrated load and recovery on each server/feed class; procurement model with actual costs |

## Required changes before operational use

- **Data:** migrate SQLite camera, sightings, review, alerts, schedule and coverage tables into PostgreSQL/PostGIS with stable event IDs and explicit migration/rollback tests. Store evidence in approved object storage, verify SHA-256 on retrieval, and apply approved retention and deletion holds.
- **Workers:** use a regional durable event bus, one bounded lease per active camera, GPU worker pools and relay monitoring. Preserve source PTS, timebase, generation and any verified UTC mapping through each hop. Test that a relay does not multiply upstream camera connections.
- **Identity:** replace shared keys and memory sessions with the approved identity provider, department and role claims, durable revocation, TLS/mTLS, short-lived credentials and secret-manager references. Encrypt camera URLs/secrets and backups. Test cross-department denial and export audit.
- **Reliability:** establish recovery objectives, encrypted backups, restore drills, two-region failover and link-loss tests. A configuration file is not proof of disaster recovery.
- **Safety of results:** validate Indian plate accuracy by condition, require human review for uncertain OCR, and treat coverage gaps as uncertainty. Never treat an alert as automatic enforcement or a straight line as a driven route.
- **Operations:** monitor discovered/connected/viewed/analyzed counts, applied vs requested fps, queue age, frame-to-alert latency, model failures, feed health, hash failures, storage use and all coverage codes. Alert on missed capacity acknowledgement and sustained unavailable coverage.

The sample [50-camera scenario](../output/benchmarks/capacity_50_assumptions.json) assumes 20% active at 1 fps and 2 Mb/s. The sample [80,000-camera scenario](../output/benchmarks/capacity_80000_assumptions.json) assumes 5% active. Worker counts extrapolate the two-feed laptop budget and are **illustrative**, not procurement figures. Costs remain blank until approved hardware, energy, network, licensing, storage and support prices are supplied.
