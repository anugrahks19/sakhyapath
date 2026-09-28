# Gujarat CCTV Hackathon source index

This index covers the two supplied files as source material. Line numbers refer to `GUJtxt.txt` and page numbers to `GUJ.pdf`. It records claims made by the supplied material; it does not verify current event dates, links, or Government policy.

The subsequently supplied Sentinel camera-grid integration reference is indexed separately in [`../sentinel_source_index/README.md`](../sentinel_source_index/README.md), with its complete line-level records and sandbox-specific API and streaming constraints.

## Complete, searchable records

- [`GUJtxt_lines.tsv`](GUJtxt_lines.tsv): every one of the 554 source text lines, including blank lines, in original order. Search the `text` column and use `line` to return to the exact location.
- [`GUJpdf_pages_and_lines.tsv`](GUJpdf_pages_and_lines.tsv): every line returned by PDF text extraction, labeled with its page and extracted line number. PDF extraction preserves content but its line wrapping and reading order are not always identical to the visual page.
- [`full_text.json`](full_text.json): complete extracted PDF text by page, source hashes and sizes, and an inventory of all six embedded images.
- [`contact_sheet_1.png`](contact_sheet_1.png) and [`contact_sheet_2.png`](contact_sheet_2.png): visual overview of all 20 PDF pages. Full rendered pages containing embedded images are saved as `page_01.png`, `page_02.png`, `page_05.png`, and `page_07.png`.

## Topic index

| Topic | Text lines | PDF pages | Key point |
|---|---:|---:|---|
| Event and participant journey | 1–23, 61–84, 306–336, 348–371, 396–410, 452–517 | 1–2, 13–20 | Seven steps from understanding the challenge through evaluation. |
| Background and core goal | 24–60 | 2–5 | 26 departments have disparate analog/IP CCTV, vendors, storage, retention, and geography; integrate existing public-domain assets securely and economically. |
| Model 1: registry and GIS foundation | 85–136 | 5–7 | Mandatory common metadata and GIS layer; no central video recording or streaming by itself. |
| Model 2: unified viewing and metadata analytics | 137–184 | 7–9 | Direct feed/VMS connections, unified viewer, selective ANPR and searchable metadata while existing systems retain control. |
| Model 3: VMS federation and middleware | 185–231 | 9–11 | Vendor adapters and a common federation layer for metadata, events, correlation, and downstream apps. |
| Model 4: central VMS and AI | 232–280 | 11–13 | Central ingest, recording, storage, analytics, tracking, and stronger infrastructure needs. |
| Hybrid/custom architecture | 281–304, 337–346 | 13–14 | Combine models or propose a custom design; open, modular, standards based, vendor neutral. |
| Expected solution and watchlist workflow | 306–346 | 13–14 | Continuous analysis of supplied feeds against representative watchlists, match logic, alerts, database, and interface. |
| Technical evaluation and expected output | 348–391 | 14–15 | Onboard about 50 heterogeneous feeds; track a designated registration number across cameras; show route, timestamps, GIS, searchable history, and watchlist alerts. |
| Presentation and HLD | 396–431 | 15–16 | Explain model choice, architecture, integrations, analytics, alerting, security, scalability, prerequisites, and impact. |
| Own-feed and Government-feed demonstrations | 432–444 | 16–17 | Own-feed operational video of 2–3 minutes; Government feed onboarding/viewing/analytics, screen recording, and timestamped vehicle/plate output report. |
| Submission links | 445–451 | 17–18 | Unlisted YouTube; Google Drive or OneDrive with anyone-with-link viewer access; optional hosted demo and repository links. |
| Statewide scale plan | 452–491 | 18 | Plan for about 80,000 cameras: compute, GPU, bandwidth, storage tiers, monitoring, resilience, cybersecurity, and costs. |
| Evaluation criteria and bonus | 492–554 | 18–20 | Seven common evaluation areas; bonus only for demonstrated features beyond mandatory requirements. |

## Critical requirements to remember

1. The platform must actually run with a backend. The source says mock-ups, animation, simulated interfaces, and concept-only videos are not accepted for the own-feed demo (text lines 432–439; PDF p. 17).
2. The live test uses approximately 50 geographically dispersed, technically heterogeneous Government cameras, available after registration through the hackathon Resources page (lines 372–385; PDF pp. 14–15).
3. Evaluators supply a vehicle registration number. The solution must identify the vehicle across cameras and present a time- and location-stamped route, movement history, searchable events, and GIS view (lines 348–391; PDF pp. 14–15; page 2 infographic).
4. Continuous comparison of video analytics results with a working, representative watchlist database and automatic real-time alerts is expected. Teams may construct representative data (lines 310–334, 372–390; PDF pp. 14–15).
5. Model 1's camera registry/GIS is described as the common mandatory foundation for feed integration under Models 2–4 (lines 85–99; PDF pp. 5–6; page 5 screenshot).
6. The proposal must show a credible route from prototype to around 80,000 cameras, including network, compute, storage/retention, availability, disaster recovery, security, and cost assumptions (lines 452–491; PDF p. 18).
7. Submitted material includes presentation, HLD, working own-feed demo, Government-feed demo plus timestamped detection report, and accessible links (lines 410–451; PDF pp. 15–18).

## Image index (all six embedded PDF images)

| Page / image | Saved image | Visible content that text extraction can miss |
|---|---|
| 1 / 1 | [`pdf_image_p01_01.png`](pdf_image_p01_01.png) | Website screenshot headed “GUJARAT CCTV HACKATHON 2026” and “Problem Statement & Solution Flow”; seven-step participant journey; Step 1 challenge cards; start of Step 2. A badge reads “ANNOUNCEMENT Date Extended: 12–13 Oct.” The badge itself does not show a year. |
| 1 / 2 | [`pdf_image_p01_02.png`](pdf_image_p01_02.png) | Step 2 model choice cards: Model 1 marked mandatory, Models 2–4, hybrid; Step 3 expected solution and design topics: overall architecture, AI/video analytics, integration, cybersecurity, deployment, sizing, cost-benefit, department-wise information, scalability, roadmap. |
| 2 / 1 | [`pdf_image_p02_01.png`](pdf_image_p02_01.png) | Step 4 live test checklist (onboard about 50, integrate feeds, track vehicle, alerts/history, GIS, route/search); Step 5 submission checklist (presentation, HLD, own-feed demo, Government-feed demo, output report, links); Step 6 scale checklist. |
| 2 / 2 | [`pdf_image_p02_02.png`](pdf_image_p02_02.png) | Step 6 scale checklist is repeated; Step 7 evaluation cards: successful test, presentation, architecture, working demo, analytics quality, scalability/PoC readiness, bonus consideration. |
| 5 / 1 | [`pdf_image_p05_01.png`](pdf_image_p05_01.png) | Screenshot of the model accordion. Model 1 is the common CCTV registry/GIS foundation; the accordion shows Models 1 and 2. |
| 7 / 1 | [`pdf_image_p07_01.png`](pdf_image_p07_01.png) | Screenshot of the accordion listing Models 2–4 and hybrid with their descriptive subtitles. |

The process-flow diagrams on PDF pp. 7, 9, 10–13 are PDF text and vector shapes rather than embedded bitmap images. Their labels are captured in the page-line TSV. In brief: Model 1 goes from assets to onboarding to registry to PostGIS to GIS dashboard; Model 2 from departmental VMS to protocols/APIs to stream gateway to analytics to control-room view; Model 3 from vendor VMS to connectors to federation middleware to event bus to dashboard; Model 4 from statewide sources to central ingestion to VMS to storage/AI to command centre.

## Source ambiguities and limits

- The material alternates between **four numbered models plus hybrid** and “five reference solution models” (text lines 61–84, 281–289, 340–346; PDF pp. 13–15). Preserve both wordings when describing the source; clarify the competition's official model count before a formal submission.
- The source uses “AI” and sometimes visually/typographically “Al”. These are treated as the same intended term in this topic index, while the full-text records retain the original characters.
- The date announcement is visible only in the screenshot on PDF p. 1. The supplied files do not establish whether that date is still current or what exact deadline action it governs.
- Camera feed URLs, registration instructions, exact evaluation dates, and an official submission portal URL are absent from these two files.
