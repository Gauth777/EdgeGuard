"""Transactional edge domain. No networking or framework dependencies."""

import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

SENSORS = {
    "temperature": "°C",
    "vibration": "mm/s RMS",
    "pressure": "bar",
    "current": "A",
    "rpm": "RPM",
}
RANGES = {
    "temperature": (-50, 500),
    "vibration": (0, 200),
    "pressure": (0, 1000),
    "current": (0, 10000),
    "rpm": (0, 100000),
}
DEFAULT_LIMITS = {
    "temperature": [80, 100],
    "vibration": [5, 9],
    "pressure": [8, 12],
    "current": [15, 22],
    "rpm": [1800, 2200],
}


def dumps(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


class CapacityError(Exception):
    pass


class Store:
    def __init__(self, path, max_queue=2000, max_machines=100, max_incidents=1000):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path, self.max_queue, self.max_machines, self.max_incidents = (
            str(path),
            max_queue,
            max_machines,
            max_incidents,
        )
        self.lock = RLock()
        self.capacity_errors = 0
        with self.tx() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS machines(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS readings(id TEXT PRIMARY KEY, machine TEXT NOT NULL, ts REAL NOT NULL, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS readings_machine_ts ON readings(machine,ts);
            CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, machine TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, priority INTEGER NOT NULL, body TEXT NOT NULL, attempts INTEGER DEFAULT 0, due REAL DEFAULT 0, error TEXT);
            CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS cloud_state(id TEXT PRIMARY KEY, version INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS counters(key TEXT PRIMARY KEY, value REAL NOT NULL);
            """)

    @contextmanager
    def tx(self):
        with self.lock:
            c = sqlite3.connect(self.path, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA synchronous=FULL")
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def count(self, c, key, value=1):
        c.execute(
            "INSERT INTO counters VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value",
            (key, value),
        )

    def register(self, machine, label, limits=None):
        limits = limits or DEFAULT_LIMITS
        if set(limits) != set(SENSORS):
            raise ValueError("Supply limits for all five sensors")
        for key, pair in limits.items():
            if (
                len(pair) != 2
                or not all(
                    isinstance(x, (float, int)) and math.isfinite(x) for x in pair
                )
                or not RANGES[key][0] <= pair[0] < pair[1] <= RANGES[key][1]
            ):
                raise ValueError("Limits require valid warning < critical values")
        with self.tx() as c:
            if c.execute("SELECT 1 FROM machines WHERE id=?", (machine,)).fetchone():
                raise ValueError(
                    "Machine already registered; configuration is immutable in v0.1"
                )
            if (
                c.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
                >= self.max_machines
            ):
                raise CapacityError("Configured machine limit reached")
            body = dict(
                id=machine,
                label=label,
                limits=limits,
                health="UNKNOWN",
                quality={},
                latest=None,
                last_ts=0,
                version=0,
                normal_run=0,
                warning_run=0,
                active=None,
                last_summary=0,
            )
            c.execute("INSERT INTO machines VALUES(?,?)", (machine, dumps(body)))
        return body

    def enqueue(self, c, kind, body, priority):
        size = c.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        if size >= self.max_queue:
            expendable = c.execute(
                "SELECT id FROM outbox WHERE priority=0 ORDER BY rowid LIMIT 1"
            ).fetchone()
            if expendable:
                c.execute("DELETE FROM outbox WHERE id=?", (expendable["id"],))
                self.count(c, "routine_events_dropped")
            elif priority == 0:
                self.count(c, "routine_events_dropped")
                return
            else:
                self.capacity_errors += 1
                raise CapacityError(
                    "Incident queue full: ingestion rejected, publisher must retry; restore cloud or export records"
                )
        event = dict(
            id=str(uuid.uuid4()),
            kind=kind,
            version=body["version"],
            entity_id=body["id"],
            payload=body,
        )
        c.execute(
            "INSERT INTO outbox(id,priority,body) VALUES(?,?,?)",
            (event["id"], priority, dumps(event)),
        )
        self.count(c, "events_created")

    def save_incident(self, c, incident, priority=2):
        incident["version"] += 1
        c.execute(
            "INSERT INTO incidents VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (incident["id"], incident["machine"], dumps(incident)),
        )
        self.enqueue(c, "incident", incident, priority)

    def ingest(self, message, detector=None, now=None):
        now = time.time() if now is None else now
        mid, ts = message["machine_id"], message["timestamp"]
        with self.tx() as c:
            row = c.execute("SELECT body FROM machines WHERE id=?", (mid,)).fetchone()
            if not row:
                raise ValueError("Register this machine first")
            m = json.loads(row["body"])
            prior = c.execute(
                "SELECT body FROM readings WHERE id=?", (message["message_id"],)
            ).fetchone()
            if prior:
                old = json.loads(prior["body"])
                if (
                    old["machine_id"] != mid
                    or old["timestamp"] != ts
                    or old["values"] != message["values"]
                ):
                    raise ValueError("Message ID reused with different data")
                return {"duplicate": True, "machine": m}
            if ts <= m["last_ts"]:
                raise ValueError(
                    "Out-of-order timestamp; current machine state was not changed"
                )
            if ts > now + 5:
                raise ValueError("Timestamp more than five seconds in the future")
            quality, valid, reasons, level = {}, {}, [], "NORMAL"
            for sensor in SENSORS:
                value = message["values"].get(sensor)
                if value is None:
                    quality[sensor] = "MISSING"
                elif (
                    not math.isfinite(value)
                    or not RANGES[sensor][0] <= value <= RANGES[sensor][1]
                ):
                    quality[sensor] = "INVALID"
                elif now - ts > 10:
                    quality[sensor] = "STALE"
                else:
                    quality[sensor] = "VALID"
                    valid[sensor] = value
                    warn, crit = m["limits"][sensor]
                    if value >= warn:
                        severity = "CRITICAL" if value >= crit else "WARNING"
                        reasons.append(
                            dict(
                                sensor=sensor,
                                value=value,
                                threshold=crit if severity == "CRITICAL" else warn,
                                severity=severity,
                                source="rule",
                            )
                        )
                        if severity == "CRITICAL" or level == "NORMAL":
                            level = severity
            previous = [
                json.loads(r["body"])
                for r in c.execute(
                    "SELECT body FROM readings WHERE machine=? ORDER BY ts DESC LIMIT 4",
                    (mid,),
                )
            ]
            ml = {"status": "NOT_CALIBRATED", "score": None}
            if detector:
                ml.update(
                    model=getattr(detector, "version", None),
                    source_type=getattr(detector, "source_type", None),
                )
            if detector and len(valid) == 5:
                # Filtering affects ML only; deterministic limits always see fresh raw values.
                from .preprocessing import filter_values

                filtered = filter_values(valid, ts, previous)
                try:
                    ml = detector.evaluate(filtered)
                except Exception:
                    # A failed model must not suppress deterministic threshold alerts.
                    ml.update(status="MODEL_ERROR", score=None)
                if ml["status"] == "ANOMALY":
                    reasons.append(
                        dict(
                            source="model",
                            severity="WARNING",
                            detail="Unusual sensor pattern; not a failure diagnosis",
                            model=ml.get("model"),
                            score=ml.get("score"),
                            source_type=ml.get("source_type", "unknown"),
                            signals=ml.get("signals", []),
                        )
                    )
                    if level == "NORMAL":
                        level = "WARNING"
            elif detector:
                ml["status"] = "INSUFFICIENT_DATA"
            reading = dict(message, quality=quality, level=level, ml=ml)
            c.execute(
                "INSERT INTO readings VALUES(?,?,?,?)",
                (message["message_id"], mid, ts, dumps(reading)),
            )
            self.count(c, "readings_processed")
            self.count(c, "baseline_payload_bytes", len(dumps(message).encode()))
            m["warning_run"] = m["warning_run"] + 1 if level == "WARNING" else 0
            m["normal_run"] = (
                m["normal_run"] + 1 if level == "NORMAL" and len(valid) == 5 else 0
            )
            trigger = level == "CRITICAL" or m["warning_run"] >= 3
            incident = None
            if m["active"]:
                incident = json.loads(
                    c.execute(
                        "SELECT body FROM incidents WHERE id=?", (m["active"],)
                    ).fetchone()["body"]
                )
                if trigger and incident["status"] == "RECOVERED":
                    incident["status"] = "OPEN"
                    incident["timeline"].append(
                        dict(at=now, action="Abnormal behaviour resumed")
                    )
                    self.save_incident(c, incident)
                if level == "CRITICAL" and incident["severity"] != "CRITICAL":
                    incident["severity"] = "CRITICAL"
                    incident["reasons"] = reasons
                    incident["timeline"].append(
                        dict(at=now, action="Escalated to CRITICAL")
                    )
                    self.save_incident(c, incident, 3)
                if m["normal_run"] >= 5 and incident["status"] in (
                    "OPEN",
                    "ACKNOWLEDGED",
                ):
                    incident["status"] = "RECOVERED"
                    incident["timeline"].append(
                        dict(at=now, action="Five consecutive complete normal readings")
                    )
                    self.save_incident(c, incident)
            elif trigger:
                if (
                    c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
                    >= self.max_incidents
                ):
                    self.capacity_errors += 1
                    raise CapacityError(
                        "Incident retention limit reached; export/archive required before accepting more incidents"
                    )
                before = [
                    json.loads(r["body"])
                    for r in c.execute(
                        "SELECT body FROM readings WHERE machine=? AND ts>=? ORDER BY ts LIMIT 61",
                        (mid, ts - 30),
                    )
                ]
                incident = dict(
                    id=str(uuid.uuid4()),
                    machine=mid,
                    version=0,
                    status="OPEN",
                    severity=level,
                    opened_at=ts,
                    reasons=reasons,
                    limits=m["limits"],
                    model=ml.get("model", "none"),
                    acknowledged_at=None,
                    notes=[],
                    timeline=[dict(at=now, action="Incident opened")],
                    evidence=[],
                    capture_complete=False,
                    pre_seconds=round(ts - before[0]["timestamp"], 2) if before else 0,
                    pre=before,
                )
                m["active"] = incident["id"]
                # First delivery is a compact notification; evidence is sent later.
                compact = dict(incident, pre=[])
                self.save_incident(c, compact, 3 if level == "CRITICAL" else 2)
                c.execute(
                    "UPDATE incidents SET body=? WHERE id=?",
                    (dumps(dict(incident, version=compact["version"])), incident["id"]),
                )
                incident["version"] = compact["version"]
            if (
                incident
                and not incident["capture_complete"]
                and ts >= incident["opened_at"] + 30
            ):
                after = [
                    json.loads(r["body"])
                    for r in c.execute(
                        "SELECT body FROM readings WHERE machine=? AND ts>? AND ts<=? ORDER BY ts LIMIT 61",
                        (mid, incident["opened_at"], incident["opened_at"] + 30),
                    )
                ]
                incident["evidence"] = (incident.pop("pre", []) + after)[:122]
                incident["capture_complete"] = True
                incident["timeline"].append(
                    dict(
                        at=now,
                        action="Evidence window completed; inspect missing sensors and sample gaps",
                    )
                )
                self.save_incident(c, incident, 1)
            m.update(
                latest=reading,
                last_ts=ts,
                quality=quality,
                version=m["version"] + 1,
                health=level
                if level != "NORMAL"
                else ("NORMAL" if len(valid) == 5 else "UNKNOWN"),
            )
            if now - m["last_summary"] >= 15:
                window = [
                    json.loads(r["body"])
                    for r in c.execute(
                        "SELECT body FROM readings WHERE machine=? AND ts>=? ORDER BY ts LIMIT 600",
                        (mid, ts - 15),
                    )
                ]
                summary = {}
                for s in SENSORS:
                    values = [
                        r["values"][s] for r in window if r["quality"][s] == "VALID"
                    ]
                    summary[s] = (
                        dict(
                            min=min(values),
                            max=max(values),
                            mean=sum(values) / len(values),
                            count=len(values),
                        )
                        if values
                        else None
                    )
                self.enqueue(c, "machine", dict(m, summary=summary), 0)
                m["last_summary"] = now
            c.execute("UPDATE machines SET body=? WHERE id=?", (dumps(m), mid))
            c.execute(
                "DELETE FROM readings WHERE machine=? AND id NOT IN (SELECT id FROM readings WHERE machine=? ORDER BY ts DESC LIMIT 600)",
                (mid, mid),
            )
        return {"duplicate": False, "machine": m}

    def action(self, incident_id, action, note=""):
        with self.tx() as c:
            row = c.execute(
                "SELECT body FROM incidents WHERE id=?", (incident_id,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown incident")
            i = json.loads(row["body"])
            if i["status"] == "CLOSED":
                raise ValueError("Incident already closed")
            if len(i["timeline"]) >= 100 or len(i["notes"]) >= 50:
                raise CapacityError("Incident audit entry limit reached")
            now = time.time()
            if action == "acknowledge":
                if i["acknowledged_at"] is not None:
                    return i
                i["acknowledged_at"] = now
                if i["status"] == "OPEN":
                    i["status"] = "ACKNOWLEDGED"
            elif action == "close":
                m = json.loads(
                    c.execute(
                        "SELECT body FROM machines WHERE id=?", (i["machine"],)
                    ).fetchone()["body"]
                )
                if (
                    i["status"] != "RECOVERED"
                    or now - m["last_ts"] > 10
                    or m["health"] != "NORMAL"
                ):
                    raise ValueError("Close only after confirmed, fresh recovery")
                if not i["capture_complete"]:
                    raise ValueError("Wait for evidence capture to complete")
                i["status"] = "CLOSED"
                m["active"] = None
                c.execute("UPDATE machines SET body=? WHERE id=?", (dumps(m), m["id"]))
            elif action == "note":
                if not note.strip():
                    raise ValueError("Note cannot be empty")
                i["notes"].append(dict(at=now, text=note.strip()))
            else:
                raise ValueError("Unknown action")
            i["timeline"].append(dict(at=now, action=action))
            self.save_incident(c, i)
            return i

    def snapshot(self, cloud=False):
        now = time.time()
        with self.tx() as c:
            if cloud:
                all_items = [
                    (r["kind"], json.loads(r["body"]))
                    for r in c.execute("SELECT kind,body FROM cloud_state")
                ]
                machines = [b for k, b in all_items if k == "machine"]
                incidents = [b for k, b in all_items if k == "incident"]
            else:
                machines = [
                    json.loads(r["body"])
                    for r in c.execute("SELECT body FROM machines")
                ]
                incidents = [
                    json.loads(r["body"])
                    for r in c.execute(
                        "SELECT body FROM incidents ORDER BY rowid DESC LIMIT 200"
                    )
                ]
            for m in machines:
                m["age_seconds"] = (
                    round(now - m["last_ts"], 1) if m["last_ts"] else None
                )
                m["stale"] = not m["last_ts"] or now - m["last_ts"] > (
                    35 if cloud else 10
                )
                if m["stale"]:
                    m["health"] = "UNKNOWN"
                    m["quality"] = {s: "STALE" for s in SENSORS}
            queue = [
                dict(r)
                for r in c.execute(
                    "SELECT id,priority,attempts,due,error FROM outbox ORDER BY priority DESC,rowid LIMIT 100"
                )
            ]
            counters = {
                r["key"]: r["value"] for r in c.execute("SELECT * FROM counters")
            }
            pending = c.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        return dict(
            machines=machines,
            incidents=incidents,
            queue=queue,
            pending=pending,
            counters=counters,
            capacity_errors=self.capacity_errors,
            limits=dict(
                queue=self.max_queue,
                machines=self.max_machines,
                incidents=self.max_incidents,
                readings_per_machine=600,
            ),
            server_time=now,
        )

    def history(self, machine):
        with self.tx() as c:
            return [
                json.loads(r["body"])
                for r in c.execute(
                    "SELECT body FROM readings WHERE machine=? ORDER BY ts DESC LIMIT 120",
                    (machine,),
                )
            ][::-1]

    def pending(self, now=None):
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM outbox WHERE due<=? ORDER BY priority DESC,rowid LIMIT 1",
                (time.time() if now is None else now,),
            ).fetchone()
            return dict(row) if row else None

    def delivered(self, event_id, byte_count):
        with self.tx() as c:
            c.execute("DELETE FROM outbox WHERE id=?", (event_id,))
            self.count(c, "events_delivered")
            self.count(c, "delivered_payload_bytes", byte_count)

    def failed(self, event_id, error):
        with self.tx() as c:
            row = c.execute(
                "SELECT attempts FROM outbox WHERE id=?", (event_id,)
            ).fetchone()
            if row:
                attempt = row["attempts"] + 1
                c.execute(
                    "UPDATE outbox SET attempts=?,due=?,error=? WHERE id=?",
                    (
                        attempt,
                        time.time() + min(30, 2 ** min(attempt, 5)),
                        error[:200],
                        event_id,
                    ),
                )
                self.count(c, "retry_failures")

    def receive(self, event):
        with self.tx() as c:
            exists = c.execute(
                "SELECT 1 FROM receipts WHERE id=?", (event["id"],)
            ).fetchone()
            if not exists:
                c.execute(
                    "INSERT INTO receipts VALUES(?,?)", (event["id"], time.time())
                )
                c.execute(
                    "INSERT INTO cloud_state VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,kind=excluded.kind,body=excluded.body WHERE excluded.version>cloud_state.version",
                    (
                        event["entity_id"],
                        event["version"],
                        event["kind"],
                        dumps(event["payload"]),
                    ),
                )
                self.count(c, "unique_events_received")
            else:
                self.count(c, "duplicates_ignored")
        return {"ack": event["id"], "duplicate": bool(exists)}
