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
