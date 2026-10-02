# Verification performed on 2026-10-02

- Backend: **16 tests passed**, covering outage operation, restart persistence, duplicate delivery, acknowledgement loss, version ordering, missing/invalid/stale sensors, debounce/recovery, bounded retention, queue-pressure rollback, authentication, body size and failed-model fallback.
- Frontend: TypeScript check and Vite production build passed.
- Live HTTP: both independent services started; a 70-second publisher run created a critical incident, completed evidence capture and recorded recovery. Cloud synchronisation ran over HTTP.
- Browser: Chromium desktop (1440 × 1000) and mobile (390 × 844) inspected. Registration, machine view, incident acknowledgement, note saving, persistence after page reload and JSON evidence download verified. No page-level JavaScript errors detected.
- Training smoke check: training/loading infrastructure exercised using 400 synthetic normal samples. This checks executable code only and is not industrial model evaluation. No synthetic model is enabled or committed.
- Python/JS formatters run; Python undefined/unused-name checks pass.

Not executed here: Docker build/Compose startup, MQTT broker integration, Windows installation, real hardware ingestion, fleet throughput/resource benchmarks, externally deployed HTTPS, real industrial anomaly accuracy, narrated video recording.

A Starlette TestClient deprecation warning is emitted by the pinned dependency set; tests still pass. The frontend emits a bundle-size advisory (~616 kB minified JS before gzip). Assets are local and do not require an external CDN at runtime.
