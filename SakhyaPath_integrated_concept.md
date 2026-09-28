# SakhyaPath: evidence-backed active pursuit

## Choice for the application

Select **Hybrid / Innovative Architecture** and confirm **Model 1: centralised CCTV registry and GIS foundation**. The system combines Model 1 asset visibility, Model 2 unified viewing and selective analytics, and Model 3-style adapters for existing departmental VMS systems. It does not require replacing departmental storage or centrally recording all video.

This is a proposed design, not an implemented platform. The current workspace contains the indexed challenge sources and this concept, but no application code.

## One integrated product

1. **Observe:** Register each camera with department, coordinates, protocol, status, and source capability. Onboard accessible feeds, offer authorised viewing, and sample frames continuously for ANPR.
2. **Detect and alert:** Combine multiple OCR reads for a plate, compare accepted sightings with a representative watchlist, and alert on strong matches. Preserve raw reading, confidence, timestamp, camera, and a short evidence image or clip.
3. **Explain the past:** The Evidence Journey Graph joins sightings into a timestamped map. It distinguishes a camera observation from an inferred travel segment and flags implausible or uncertain links for review.
4. **Search forward:** A confirmed sighting starts Active Pursuit. A scheduler ranks plausible next cameras by time and distance, feed health, image quality, and processing cost. It raises sampling on the best candidates while maintaining baseline monitoring elsewhere. New sightings update priorities.
5. **Account for gaps:** The **Coverage Integrity Ledger** records, for every camera considered during a pursuit, whether it was reachable, healthy, actually sampled, and capable of producing readable evidence in the relevant time window. It labels an unobserved vehicle as *not seen in sampled frames*, *feed unavailable*, or *insufficient coverage*. It never treats a missing detection as proof that the vehicle was absent. The ledger makes blind spots, outages, and future camera-placement priorities visible.

The distinctive demonstration is the combined loop: watchlist hit -> evidence-backed route -> predicted next cameras -> live processing priority change -> new sighting and alert -> coverage explanation. The comparison against fixed-rate sampling uses the same compute budget and reports measured time-to-sighting, alert delay, processed frames, and unresolved gaps. These are evaluation targets, not claimed results.

## 48-hour prototype boundary

- First secure the mandatory path: camera registry/GIS, two source types, viewing, ANPR, watchlist, alert, designated-plate search, timestamped route, and output report.
- Then add a simple, deterministic pursuit scheduler using geographic distance and configurable travel-time bounds. It shows priority changes in the UI and sends sampling-rate instructions to the workers. The number of accelerated feeds is set from an RTX 4060 benchmark.
- Add a ledger row for each candidate camera/time window using measured feed health and sampling telemetry. Show one successful observation and one outage or inadequate-coverage example in the demo.
- Use real owned footage for the own-feed demonstration; connect Government feeds when access is granted. Never label replay as a live Government result. Record the required videos, HLD, presentation, and measured performance report.

For statewide deployment, regional workers analyze feeds close to existing VMS infrastructure and send compact sightings and health events centrally. The registry, alerting, evidence graph, pursuit scheduler, and ledger use durable stores and audited access. PostgreSQL/PostGIS, a durable event bus, object storage, encrypted credentials, retention policy, and disaster recovery are specified in the HLD. Capacity and cost are calculated from measured per-worker throughput rather than an assumed 80,000-camera benchmark.

## Form text

### Proposed Solution

SakhyaPath is a hybrid CCTV platform that combines evidence-backed vehicle journeys with active, coverage-aware pursuit. Its mandatory camera registry and GIS layer connects existing departmental feeds through adaptable interfaces. Continuous ANPR creates searchable, timestamped sightings and checks a watchlist for real-time alerts. Each sighting carries its source image, camera, time, and recognition confidence; observed locations are distinguished from inferred travel. After a target is seen, a compute-aware scheduler prioritises cameras that could plausibly see it next and shifts limited GPU processing toward them. A Coverage Integrity Ledger records which expected cameras were healthy and adequately sampled, clearly separating a missed detection from a feed outage or blind spot. Regional processing and central event sharing provide a practical path to statewide scale without transferring every full video stream.

### Key Features (one per line)

Mandatory camera registry, GIS mapping, and feed-health monitoring

Unified viewing and adaptable onboarding of departmental CCTV feeds

Continuous multi-frame ANPR, watchlist matching, and real-time alerts

Evidence Journey Graph with timestamped, source-linked vehicle sightings

Active Pursuit that ranks plausible next cameras and shifts GPU sampling priority

Coverage Integrity Ledger explaining outages, insufficient sampling, and blind spots

Clear separation of observed sightings, uncertain matches, and inferred route segments

Searchable vehicle history, GIS playback, and timestamped evidence export

Regional event-first architecture designed to scale by adding workers

### Expected Impact

The prototype aims to onboard the accessible evaluation feeds, trace the designated vehicle across cameras, generate watchlist alerts, and export a timestamped GIS movement history. Active Pursuit aims to detect the next sighting sooner than uniform sampling under the same GPU budget; the demo will report measured latency, throughput, and false matches. The evidence graph and Coverage Integrity Ledger should reduce manual review and prevent outages or weak OCR results from appearing as confirmed route facts. Reusing existing VMS systems and adding regional processing workers provides a measurable, cost-aware route toward approximately 80,000 cameras.

## Claims to avoid

- Do not claim the system, 50-camera operation, Government-feed results, or timing improvements have already been implemented or measured.
- Do not claim a missing detection proves a vehicle was absent.
- Do not promise a win or worldwide novelty. The distinctive contribution is the working combination of active pursuit, traceable evidence, and coverage accounting under a measured compute budget.
