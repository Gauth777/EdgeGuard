# Verification performed on 2026-10-02

- Backend: **16 tests passed**, covering outage operation, restart persistence, duplicate delivery, acknowledgement loss, version ordering, missing/invalid/stale sensors, debounce/recovery, bounded retention, queue-pressure rollback, authentication, body size and failed-model fallback.
- Frontend: TypeScript check and Vite production build passed.
- Live HTTP: both independent services started; a 70-second publisher run created a critical incident, completed evidence capture and recorded recovery. Cloud synchronisation ran over HTTP.
- Browser: Chromium desktop (1440 × 1000) and mobile (390 × 844) inspected. Registration, machine view, incident acknowledgement, note saving, persistence after page reload and JSON evidence download verified. No page-level JavaScript errors detected.
- Training smoke check: training/loading infrastructure exercised using 400 synthetic normal samples. This checks executable code only and is not industrial model evaluation. No synthetic model is enabled or committed.
- Python/JS formatters run; Python undefined/unused-name checks pass.

Not executed here: Docker build/Compose startup, MQTT broker integration, Windows installation, real hardware ingestion, fleet throughput/resource benchmarks, externally deployed HTTPS, real industrial anomaly accuracy, narrated video recording.

A Starlette TestClient deprecation warning is emitted by the pinned dependency set; tests still pass. The frontend emits a bundle-size advisory (~616 kB minified JS before gzip). Assets are local and do not require an external CDN at runtime.

## ML update — 2026-10-03

- 23 backend tests passed, including shared training/runtime preprocessing, normal-only calibration, model schema validation, model-to-machine binding, synthetic provenance retention and preservation of existing .env settings.
- Synthetic evaluation rerun through the full ingestion/incident path; see ml-report.md and the complete JSON.
- TypeScript and production build pass.
- The trained binary remains local/ignored; scripts.setup_ml generates and enables it explicitly.
- Live browser verification: below-threshold telemetry generated a model-only incident (no rule trigger); synthetic origin, model version and signal evidence displayed correctly. No JavaScript page errors detected.

## Operations console update — 2026-10-03

- 32 backend tests passed, including authenticated/disabled lab controls, scenario start/stop and duplicate-start rejection, upload pacing, first-attempt versus retry byte accounting, deduplicated offline counters, persisted connection journal, and critical detection with a missing sensor.
- Existing outage/restart, lost-acknowledgement, data-flow, queue pressure and ML tests pass. The lost-ack test advances both retry and pacing gates before retrying.
- TypeScript and Vite production build pass. Bundle-size advisory remains (~653 kB minified JS).
- Browser visual verification of this redesign was blocked: the cloud browser refused the local preview URL with ERR_BLOCKED_BY_CLIENT. No new claim of desktop/mobile visual QA is made.
- Docker enforcement, Windows runtime measurements, MQTT and representative hundreds-of-machine capacity have not been newly verified. Process resource metrics are instrumentation, not benchmark results.

## Cloud visibility correction — 2026-10-03

- Existing 32 tests pass; three additional cloud tests pass (35 total): persisted receipt metadata for the applied incident revision, delayed-version/duplicate safety, legacy SQLite migration without fabricated timestamps, and visible cloud fault mode.
- Frontend production build passes. Browser visual verification remains unavailable in this environment.
- Cloud incident opening time is explicitly labelled and distinct from receipt time. Machine sensor time and receipt time are shown separately, with a stale warning. Cloud Delivery reports unique incoming receipts and duplicate retries rather than edge-only counters.
- This verifies the code path; it does not establish the cause of an individual laptop's stale data. Check the source machine ID, source completion, local outgoing errors, and cloud fault mode.

## Efficiency and measured experiment — 2026-10-03

- 38 backend tests pass; TypeScript and production build pass.
- New tests cover gzip cloud ingestion/deduplication, malformed/truncated gzip and decompression size limits, routine replacement preserving incident/attempted/in-flight events, and a full isolated warning → failed cloud requests → critical → offline actions → recovery → sync → lost-ack retry experiment.
- First observed isolated run: all seven checks passed, six buffered important event IDs all received, no missing IDs; one duplicate attempt ignored; normal 61-reading upload bodies 2,853 B versus 11,529 B uncompressed raw baseline (75.25% reduction). These bytes/timings vary slightly with IDs, timestamps and jitter. This is a combined summary/compression comparison, not an equally compressed raw-stream baseline. No HTTP/TLS overhead is counted.
- Scenario Lab results are generated at execution, expandable and downloadable, not prefilled from this document. In-process HTTP and accelerated sensor time do not establish real-network, industrial or fleet-scale performance.
- Prior browser-access limitation remains; visual QA of the new panel has not been completed.
