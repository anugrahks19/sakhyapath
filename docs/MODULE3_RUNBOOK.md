# Module 3: Evidence Journey, historical search, and PDF report

## Local status

The local app can now search persisted plate sightings from before a search began, save the query as a pursuit, show all matching records and evidence on a GIS map, record reviewer decisions without changing raw OCR, flag impossible clock-attested jumps, and download a PDF built from the same journey payload as the UI. The deterministic test uses owned annotated fixture sightings across three cameras and preserves Module 2's separate real decoded RTSP-to-ALPR smoke test. No Government feed or common Sentinel UTC clock was provided; those gates remain open.

Run `npm run build --prefix frontend` and start the backend as described in [Module 2](MODULE2_RUNBOOK.md). Search a known registration in the **Evidence Journey** section. The search is saved, so it can be reopened after a browser or backend restart. Use the review controls to confirm, correct, or reject a candidate; the original reading, image hash, and audit history remain in place. The PDF download uses the same current persisted query and reflects later reviews or evidence integrity failures.

To create the clearly labelled synthetic sample PDF used for layout QA:

```powershell
.\.venv\Scripts\python scripts/create_module3_demo.py
```

The output is [module3_owned_fixture_report.pdf](../output/pdf/module3_owned_fixture_report.pdf). Its three observations and one rejected example are **synthetic owned fixtures**, not detected Government vehicles.

## API and data contract

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/sightings` | Historical search by normalized plate, camera, timezone-aware `from_utc`/`to_utc`, effective review state, and limit. Results include camera location/source, raw and corrected OCR, PTS/generation, time provenance, evidence status, and hash. |
| `POST /api/v1/pursuits` | Save a designated-registration query and its filters. |
| `GET /api/v1/pursuits`, `GET /api/v1/pursuits/{id}` | Reopen saved searches. |
| `GET /api/v1/pursuits/{id}/journey` | Return all records, supported observed points, dashed inferred links, alerts, gaps, and latest supported confirmed point for Module 4. |
| `GET /api/v1/pursuits/{id}/report` | Download a PDF rendered from that same journey result. |
| `POST /api/v1/sightings/{id}/review` | Add a `confirmed` or `rejected` decision, optional corrected plate, and note. This never rewrites Module 2's raw OCR or creates an automatic watchlist hit. |
| `GET /api/v1/sightings/{id}/review-history` | Full audit history of reviewer changes. |
| `POST /api/v1/cameras/{id}/time-mappings` | Operator-only PTS-to-UTC attestation for an **owned** source and one stream generation. Requires an evidence note and uncertainty bound. |

Module 3 adds schema migration 3: `pursuits`, `sighting_reviews`, append-only `sighting_review_history`, and `time_mappings`. The original sightings and crops remain in Module 2 storage. A rejected candidate stays searchable as an audit record but is removed from solid map observations. A corrected candidate enters a target query through its separately stored correction. Evidence whose file is missing, outside the configured store, or fails SHA-256 stays in the record with an explicit status and is excluded from supported observed points.

## What map times and links mean

Source PTS is meaningful only within a stream generation. A reconnect or loop restart does not inherit the previous mapping. Without an attested mapping for that camera and generation, the UI and report label receive UTC as **approximate** and decline to calculate cross-camera travel time. A mapping supplies a PTS anchor, an operator-attested UTC anchor, an uncertainty bound, and a note describing the owned recording's common clock. This is not automatic proof of a shared clock; the operator must validate the recording clock and note externally.

Solid blue points are confirmed or reviewer-confirmed sightings with intact evidence. Hollow amber points are candidates or evidence-unsupported records; grey points are rejected. Lines are dashed because a connection between two observed cameras is only an inference. Straight-line distance is a lower bound, never the actual road route. The implausible-jump check uses the **most favourable** travel time allowed by both clock uncertainty bounds and flags a jump only when even that bound exceeds the saved search's speed threshold. Unaligned points get a `time_unaligned` link instead of a speed estimate. Module 4 may consume `latest_confirmed`, but must keep its time-provenance caveat.

## Department scope

The prototype can accept optional department reviewer keys through `SAKHYAPATH_DEPARTMENT_KEYS`, a JSON map from exact department name to a unique key of at least 16 characters, for example:

```powershell
$env:SAKHYAPATH_DEPARTMENT_KEYS = '{"Traffic A":"replace-with-a-unique-long-key"}'
```

The main operator key sees all departments and alone can import cameras, sync Sentinel, manage the representative watchlist, and attest owned clock mappings. A department reviewer sees only its cameras, sightings, alerts, saved searches, evidence, reviews, and PDF reports. API checks use the session's department; direct IDs from another department return 404. This is a prototype permission boundary, not Government identity integration. Keys and sessions are process-local; production needs an approved identity provider, department/role claims, TLS, durable revocation, audit retention, and encrypted secrets.

## Verification and remaining gate

- The Module 3 integration test uses three owned annotated camera records with a common attested fixture clock, then checks GIS observations and the PDF contain the same history. It adds an unaligned reconnect generation, a rejected false positive, a corrected OCR candidate, an impossible jump, tampered/missing evidence, cross-department denial, time/status filters, and restart persistence.
- The sample PDF was rendered as two pages and visually checked for text, map, hashes, inferred links, review history, source labels, and a legible footer. It is regenerated by the script above.
- The full local suite passed **13 tests** on 28 September 2026; the frontend production build passed. The real FastALPR RTSP smoke test now continues through historical search and a generated PDF report.
- [ ] Obtain authorised Sentinel access and verify the real stream metadata, department rules, and whether a trustworthy common UTC clock exists. Until then, precise Government cross-camera chronology is an unverified claim.
- [ ] Run the evaluator's actual designated registration on authorised footage, measure retrieval and report times at representative record volume, and reconcile any reviewer corrections with approved operational policy.
- [ ] Migrate beyond the single-process SQLite prototype for regional scale, with indexed PostgreSQL/PostGIS queries, object-store evidence, retention, encryption, backup/restore, and load tests. The current search examines at most 5,000 candidate rows and returns at most 500 records per journey.
