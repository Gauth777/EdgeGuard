# Brief → implementation → remaining validation

| Requirement | Implementation | Validation / limit |
|---|---|---|
| Noisy and incomplete streams | Finite-value validation, validity flags, median ML inputs | Missing/invalid/stale tests; hardware noise calibration pending |
| Detect abnormal behaviour | Immediate critical rules, debounced warnings, optional Isolation Forest | Rules tested; no pre-trained industrial model or real-world accuracy claim |
| Classify urgency | Normal/warning/critical; unknown data quality separately | Rule tests and interface badges |
| Reduce cloud traffic | 15-second summaries instead of raw continuous forwarding | Byte counters implemented; no fixed reduction claim |
| Continue during outage | Edge ingestion/detection independent of cloud requests | Cloud-outage integration test |
| Buffer information | Transactional SQLite outgoing queue and incident evidence | Restart and capacity rollback tests |
| Synchronise later | Ack-driven deletion, retries, deduplication and versions | Lost-ack and reverse-delivery tests |
| Limited CPU/memory/bandwidth | Model one thread, bounded history/queue, bounded HTTP payloads and paced sender | Caps implemented; fleet load test and hardware profiling pending |
| Dynamic event during anomaly | Protected cloud failure injection plus real process shutdown option | Outage test preserves local incident creation |

## User-facing capabilities already built

HTTP registration/ingestion; local and cloud interfaces; sensor history; incident acknowledgement, notes, recovery and close; evidence JSON export; delivery inspection; test publisher; machine-bound model training/loading; optional MQTT adapter and Compose package.

## Deliberately not claimed complete

Industrial hardware connection, trained/validated machine-specific model, MQTT/Docker execution in this development environment, threshold editing, device identities, archive workflow, real industrial pilot certification, final narrated submission video.
