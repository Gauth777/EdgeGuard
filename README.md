# EdgeGuard

**Industrial monitoring that keeps local incident handling available when the cloud link fails.**

EdgeGuard is an executable monitoring pilot with independent edge and cloud processes, a React operator console, HTTP telemetry ingestion, an optional MQTT adapter, deterministic urgency rules, optional locally trained Isolation Forest inference, durable incident evidence and retry-safe synchronisation.

## Start on Windows (PowerShell)

Install Python 3.12+ and Node.js 22+. From a terminal:

```powershell
git clone https://github.com/Gauth777/EdgeGuard.git
cd EdgeGuard
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
.\.venv\Scripts\python.exe scripts/configure.py
.\.venv\Scripts\python.exe -m scripts.run
```

Open **http://127.0.0.1:8000** for the local console and **http://127.0.0.1:8001** for cloud monitoring. Open `.env` locally, copy `EDGEGUARD_API_KEY`, and use it to unlock each console. Do not share or commit this key. It stays in browser memory, not local storage.

In another terminal, from the repository root, start a test equipment publisher:

```powershell
.\.venv\Scripts\python.exe -m scripts.publish --scenario incident --seconds 90
```

This registers `M-01`, sends normal readings for 15 seconds, sends abnormal temperature/vibration for 40 seconds, then returns to normal. Every reading enters the real HTTP ingestion endpoint. No simulation runs inside the detector or UI. `--scenario normal`, `missing`, and `noise` are also available. The console starts empty without an equipment source.

On Linux/macOS use `python3 -m venv .venv` and `.venv/bin/python` instead of the Windows interpreter path. `Ctrl+C` stops both services; SQLite state remains on disk.

## Test the cloud outage

Stop both services, set `EDGEGUARD_ENABLE_FAULTS=1` in `.env`, then restart. Cloud console → Delivery exposes `offline`, `lose ack`, and `online` controls. These endpoints are absent in normal mode (return 404).

1. Start the incident publisher and wait for the incident to appear.
2. In the cloud console choose **offline** during the incident.
3. On the local console inspect fresh readings, acknowledge the incident and add a note. Pending delivery increases.
4. Restore **online** and inspect delivery. Retry backoff can take up to 30 seconds.
5. Choose **lose ack** before a new incident update. The cloud commits the next event and returns an error. The edge retries the same ID; the cloud duplicate counter increases without duplicating the incident.
6. To test durable recovery, interrupt and restart the services with pending events. Do not delete `data/`.

The cloud fault switch deliberately returns failures from its ingestion/health endpoints. For a true process outage, launch the two roles separately and stop only the cloud process. The edge must remain running. The cloud web page can remain reachable during an injected ingestion outage; actual cloud process failure makes that page unreachable too.

## Connect real telemetry

Register a machine first using `POST /api/machines`, with `X-API-Key` and JSON:

```json
{"id":"M-01","label":"Circulation motor","limits":{"temperature":[80,100],"vibration":[5,9],"pressure":[8,12],"current":[15,22],"rpm":[1800,2200]}}
```

**These numbers are illustrative, not equipment safety limits.** Review them against the actual machine's engineering documentation. Registration is immutable in v0.1; threshold editing/audit is not yet implemented. All five sensor limit pairs are required when supplying custom limits. Upper thresholds only are supported.

`POST /api/readings` accepts:

```json
{"machine_id":"M-01","message_id":"device-generated-unique-id","timestamp":1790960000.0,"values":{"temperature":61.2,"vibration":2.4,"pressure":5.1,"current":8.6,"rpm":1480}}
```

Replace `timestamp` with the current Unix time in seconds. Vibration must already be an RMS feature in mm/s, not a raw accelerometer waveform. Missing values are omitted or `null`. Validation limits reject impossible readings from detection; the quality flag still records them. A fresh valid critical measurement can alert even when another sensor is missing. Ingestion rejects out-of-order messages rather than corrupting current state. Publishers should retry the same ID after timeouts/503. Deduplication of readings covers the retained 600 readings; older retries are rejected by timestamp.

No direct PLC, OPC UA, or Modbus connector is included. A gateway must translate its measurements to this schema. HTTP binding defaults to localhost. For LAN or remote deployment, add TLS, firewall rules and properly scoped device/operator credentials; the pilot currently uses one shared node key.

## Optional MQTT

```sh
docker compose --profile mqtt up --build
python -m scripts.publish --mqtt-host 127.0.0.1 --scenario incident
```

The adapter subscribes to `edgeguard/+/telemetry` with a persistent QoS 1 session and acknowledges a delivery only after the edge accepts it (or rejects malformed data). MQTT publishers must set QoS 1. The broker is published only on localhost and is anonymous for that local pilot. Configure broker authentication, per-device ACLs and TLS before changing its network binding. Broker persistence autosaves every 30 seconds; this is not a zero-loss power-failure guarantee. Docker/MQTT integration has not been executed in the development environment because no Docker daemon is available.

## Optional edge ML

The default is **rules active / ML not calibrated**, not a synthetic model disguised as a production detector. Use a CSV of operator-reviewed normal operation with columns `temperature,vibration,pressure,current,rpm`:

```sh
python -m scripts.train normal.csv --output data/model.joblib
```

The script needs at least 200 complete rows, trains 64 trees with one CPU thread, and reports a false-alert fraction on the last chronological 20% of normal rows. This is not anomaly recall or evidence of predictive maintenance. Validate independently with real abnormal sequences and operating modes before enabling.

Set `EDGEGUARD_MODEL=data/model.joblib` and `EDGEGUARD_MODEL_MACHINE=M-01` in `.env`, then restart. Models are bound to one machine. The median of up to five recent valid samples feeds the model; raw fresh values always feed rules. The decision score is not a probability. Only load trusted local joblib files.

## Interface

- **Overview:** inventory, condition, freshness and active incidents.
- **Machine:** five measurements, raw history, thresholds and model status. Invalid samples make chart gaps. Cloud shows received summaries instead of reading the edge database.
- **Incidents:** reasons, acknowledgement, notes, recovery, close action, evidence export and timeline.
- **Delivery:** persistent queue, priority, retries and byte accounting. Attempted payload bytes include evidence and retries; no fabricated bandwidth-saving percentage.

The edge owns edits. Cloud is read-only. Acknowledgement is not recovery. Five consecutive complete normal readings mark recovery; closing also requires fresh readings and a completed capture window.

## Reliability and bounded resources

- SQLite WAL + FULL synchronous; incident changes and outgoing records share one transaction.
- At-least-once delivery, stable event IDs, idempotent cloud receipt and monotonic entity versions.
- Critical notification precedes lower-priority evidence; sustained critical traffic can delay routine data.
- 15-second normal telemetry windows carry min/max/mean/count plus the latest state.
- 600 retained readings per machine, 100 registered machines, 2,000 outgoing events and 1,000 retained incidents by default. These are caps, **not a claim of validated throughput for 100 machines**.
- Evidence retains up to 61 pre-event and 61 post-event samples over nominal 30-second windows. Best suited to approximately 1 Hz feature telemetry. High-rate streams need upstream aggregation.
- Routine outgoing events are evicted first under pressure, with an explicit counter. If only important events remain, a new important change is rejected with 503 and rolled back. Publishers must retain/retry; unlimited offline retention is impossible.
- HTTP bodies capped at 256 KiB; MQTT bodies at 16 KiB. Sync attempts at most four payloads per second with a 3-second HTTP timeout and backoff capped at 30 seconds. No adaptive bytes-per-second shaping yet.
- Docker caps each application at 1 CPU / 512 MiB. Resource caps are configuration, not measured fleet-scale performance. No GPU needed.
- Evidence capture may remain incomplete when telemetry stops. Exported timestamps expose gaps; `capture_complete` means the window elapsed, not uninterrupted data.

## Tests

```sh
python -m pytest -q
npm run build --prefix frontend
```

The backend suite covers persistence after restart, outage during anomaly, acknowledgement loss, duplicate and reordered delivery, missing/invalid/stale sensors, warning debounce, evidence windows, incident actions, capacity rollback, retention, API authentication and payload limits.

See [architecture](docs/architecture.md), [requirement coverage](docs/requirements.md), and [recording guide](docs/recording.md).

## Pilot limitations

No hardware validation, regulatory/safety certification, automatic machine actuation, user accounts, per-device credentials, full audit identity, threshold editing, machine deletion, archival UI, adaptive drift handling, TLS termination, or direct PLC drivers. Cloud receipts currently grow until administratively archived. Disk-full/hardware failures remain an operational risk; backup/export and storage monitoring are required. Only a single API worker and edge-owned edits are supported. Browser login uses one shared operator key. Do not expose this configuration directly to the public internet.
