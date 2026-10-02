# Suggested 6–8 minute walkthrough

Check the actual submission's duration requirements before recording.

1. Explain the problem: network interruption must not stop local detection or incident handling.
2. Show separate edge and cloud URLs and the architecture. State that equipment readings are supplied by a test publisher through the same API a gateway uses.
3. Start `python -m scripts.publish --scenario incident --seconds 90`. Show normal readings and cloud summaries.
4. At around 20 seconds, open the critical incident. Explain the triggering threshold and the difference between machine condition and sensor quality.
5. In cloud → Delivery activate offline. Return to local console. Acknowledge and annotate the incident while cloud ingestion fails. Observe the queue.
6. Inspect evidence coverage and export the incident. It contains pre-event readings, post-event readings and timestamped operator actions.
7. Restore cloud online. Allow up to 30 seconds for retry backoff. Show pending count reducing and the cloud's incident revision matching local state.
8. Demonstrate `lose ack` with another note. Explain stable event IDs and the duplicate counter.
9. Finish with measured test output, resource limits and honest boundaries: calibration, hardware, authentication scope and finite storage.

Optional separate restart clip: stop and restart edge while pending records remain, then recover cloud delivery. Do not claim the edge keeps executing while its own process is stopped; claim the stored incident/outbox survives restart.

## Interview anchors

- Why local? Network-independent detection and operator access.
- Why SQLite? Transactional durability and low operational overhead for a single node.
- What is atomic? Incident change plus outgoing event; cloud receipt plus materialised update.
- What does acknowledgement mean? The cloud confirmed durable acceptance of this event ID.
- Why not call the score a probability? Isolation Forest decision values are not calibrated failure probabilities.
- What if storage fills? Explicitly discard routine summaries first, then reject important mutations with backpressure; no promise of infinite buffering.
- What is distinctive? Operators can inspect both incident evidence quality and delivery history through an outage.
