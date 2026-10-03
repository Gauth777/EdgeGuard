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

## Edge ML: reproducible synthetic evaluation

The default remains rules-only until you explicitly enable a model. To run the ML demonstration on the native Python launcher, stop the services, pull the update, and run:

```powershell
git pull
npm run build --prefix frontend
.\.venv\Scripts\python.exe -m scripts.setup_ml
.\.venv\Scripts\python.exe -m scripts.run
```

`setup_ml` trains on 2,400 synthetic normal rows, calibrates the score threshold using 1,200 separate normal rows, evaluates seven scenarios with four held-out seeds each through the real ingestion engine, saves `data/ml-evaluation.json`, and updates only the model path/machine entries in `.env`. Your access key and outage-test setting remain unchanged. It binds the model to **ML-01**. A synthetic model is not industrial calibration.

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.publish --profile synthetic --scenario subthreshold --machine ML-01 --seconds 120
```

Open **Machine → ML-01**. From about 15 seconds, abnormal generated readings remain below every rule threshold, but should produce an ML warning and an incident after filtering/debounce. At 55 seconds readings return to the synthetic normal profile. The UI shows the synthetic-data label, model version, calibrated score margin and any values outside its training reference range. **A negative margin is unusual, not a failure probability.**

Available synthetic scenarios: `normal`, `incident` (critical rule breach), `noise`, `missing`, `subthreshold`, `combination`, `healthy_shift`. Use `--profile synthetic` with this model. The legacy publisher has a different normal distribution and can legitimately be flagged as unfamiliar. `healthy_shift` intentionally demonstrates that a healthy new operating regime can cause ML false alerts.

Evaluation alone, without changing `.env`:

```sh
python -m scripts.evaluate_ml
```

Measured results and limitations: [ML evaluation report](docs/ml-report.md). The initial held-out synthetic evaluation caught 4/4 subthreshold and 4/4 combination episodes that rules missed, but also started 2 false incidents during 10 minutes of normal sequences and 5 during the healthy-shift sequences. These are small synthetic tests, not industrial accuracy estimates. Model-based warnings require operator investigation; never equate statistical novelty with confirmed failure.

To return to rules-only, remove `EDGEGUARD_MODEL` and `EDGEGUARD_MODEL_MACHINE` from `.env` and restart. This setup workflow configures the native launcher; it does not mount model files into Docker's named volumes.

### Train from reviewed equipment data

Use a CSV of operator-reviewed normal operation with columns `temperature,vibration,pressure,current,rpm`. An optional `timestamp` column must strictly increase; without it, 1 Hz is assumed.

```sh
python -m scripts.train normal.csv --output data/model.joblib
```

At least 600 complete rows are required. The first 60% trains the model; the next 20% calibrates the anomaly threshold; the final 20% is a normal-only holdout. The causal median preprocessing matches live inference, and history resets at each partition. Train only on complete, finite values in the accepted sensor ranges. The holdout flag fraction is not failure recall. Independent abnormal sequences and operating-mode validation are still required.

Set `EDGEGUARD_MODEL=data/model.joblib` and `EDGEGUARD_MODEL_MACHINE=<your-machine-id>` in `.env`, then restart. One model is bound to one machine. 64 trees, max 256 training samples per tree, one CPU thread. Missing inputs suspend inference. A failed model does not suppress critical deterministic rules. Only load trusted local joblib files. Version 1 model files must be retrained with the current script.

## Interface

- **Overview:** inventory, condition, freshness and active incidents.
- **Machine:** five measurements, raw history, thresholds and model status. Invalid samples make chart gaps. Cloud shows received summaries instead of reading the edge database.
- **Incidents:** reasons, acknowledgement, notes, recovery, close action, evidence export and timeline.
- **Delivery:** persistent queue, priority, retries and byte accounting. Attempted payload bytes include evidence and retries; no fabricated bandwidth-saving percentage.
- **Data Flow:** database-backed raw readings, quality at ingestion, saved rule/ML reasons, and actual links to summary, snapshot, notification and evidence events. Expand a reading to inspect event IDs, retries and acknowledgements. Filter by machine/condition, pause updates, or export the displayed database snapshot as JSON. The cloud view shows only received event records and their summary statistics.

### Inspect persistence and data selection

After updating, stop the services, run `git pull`, rebuild with `npm ci --prefix frontend` and `npm run build --prefix frontend`, then restart with `python -m scripts.run` (use your virtual environment's interpreter). Existing databases are upgraded automatically; do not delete `data/` or rerun model training for this UI update.

1. Open **Data Flow** locally and start a publisher. Each accepted message appears with its saved measurements, quality flags and detection reason. Normal readings remain locally available; valid values are represented in periodic summaries, alongside a latest-reading snapshot.
2. Expand **Transmission ledger → Inspect payload facts** to see real min/max/mean/count values and how many readings the summary window covered. A summary acknowledgement does not imply upload of every raw sample.
3. Start an incident and interrupt cloud ingestion. Local readings continue accumulating and events show queued/retrying. After reconnecting, their stable event IDs become acknowledged.
4. Use **lose ack** to observe the distinction: the cloud has a received record while the edge still shows retrying. After a successful retry the edge shows acknowledged, with one unique cloud receipt.
5. Restart the services. Saved readings and delivery records remain inspectable. The file-size card measures the SQLite database plus its current WAL transaction log, not historical readings processed.

The read-only `/api/data-flow` endpoint requires the node key, optionally filters by `machine`, and returns up to 100 recent raw readings and 50 recent events. A condition filter applies to those 100 readings. Local raw retention remains 600 readings per machine. Delivery tracking retains the latest 2,000 completed events plus pending events; older links may expire. Older delivered events and old detection reasons are not reconstructed. Existing pending events are backfilled from their actual payloads where possible. The dashboard explicitly reports missing tracking history instead of assuming delivery. All-machine cumulative counters are labelled separately from filtered stored-row counts.

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
