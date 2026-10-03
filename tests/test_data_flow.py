import json
import time
import uuid

from fastapi.testclient import TestClient

from edgeguard.api import create_app
from edgeguard.core import Store

KEY = "test-data-flow-secret-at-least-24-chars"


def reading(ts, **values):
    return dict(
        machine_id="M-01",
        message_id=str(uuid.uuid4()),
        timestamp=ts,
        values=dict(
            temperature=values.get("temperature", 60),
            vibration=values.get("vibration", 2),
            pressure=5,
            current=8,
            rpm=1480,
        ),
    )


def edge(tmp_path, **kwargs):
    s = Store(tmp_path / "edge.db", **kwargs)
    s.register("M-01", "Motor")
    return s


def test_summary_routes_quality_and_restart(tmp_path):
    s = edge(tmp_path)
    ts = time.time()
    s.ingest(reading(ts, vibration=None), now=ts)
    flow = s.data_flow()
    r = flow["readings"][0]
    assert r["quality"]["vibration"] == "MISSING"
    assert {x["representation"] for x in r["routes"]} == {
        "AGGREGATE",
        "LATEST_SNAPSHOT",
    }
    assert flow["events"][0]["detail"]["summary"]["vibration"] is None
    assert flow["events"][0]["detail"]["summary"]["temperature"]["count"] == 1
    restarted = Store(s.path)
    assert restarted.data_flow()["readings"][0]["routes"] == r["routes"]
    assert restarted.data_flow()["storage"]["readings"] == 1


def test_lost_ack_is_received_in_cloud_but_retrying_at_edge(tmp_path):
    s = edge(tmp_path)
    ts = time.time()
    s.ingest(reading(ts, temperature=110), now=ts)
    cloud = Store(tmp_path / "cloud.db")
    item = s.pending()
    event = json.loads(item["body"])
    cloud.receive(event)
    s.failed(item["id"], "Acknowledgement lost")
    assert (
        next(e for e in s.data_flow()["events"] if e["id"] == item["id"])["status"]
        == "RETRYING"
    )
    assert cloud.data_flow(cloud=True)["events"][0]["status"] == "RECEIVED"
    assert cloud.receive(event)["duplicate"]
    assert len(cloud.data_flow(cloud=True)["events"]) == 1
    s.delivered(item["id"], len(item["body"]))
    record = next(
        e for e in Store(s.path).data_flow()["events"] if e["id"] == item["id"]
    )
    assert record["status"] == "ACKNOWLEDGED" and record["acknowledged"]
    assert record["attempts"] == 1
    assert s.data_flow()["readings"][0]["reasons"][0]["source"] == "rule"


def test_queue_pressure_is_dropped_not_delivered(tmp_path):
    s = edge(tmp_path, max_queue=2)
    ts = time.time()
    s.ingest(reading(ts), now=ts)
    first = s.pending()["id"]
    s.ingest(reading(ts + 16), now=ts + 16)
    s.ingest(reading(ts + 17, temperature=110), now=ts + 17)
    event = next(e for e in s.data_flow()["events"] if e["id"] == first)
    assert event["status"] == "DROPPED" and event["acknowledged"] is None
    assert any(
        r["status"] == "DROPPED" for r in s.data_flow()["readings"][-1]["routes"]
    )


def test_evidence_links_and_legacy_records(tmp_path):
    s = edge(tmp_path)
    ts = time.time()
    s.ingest(reading(ts), now=ts)
    s.ingest(reading(ts + 1, temperature=110), now=ts + 1)
    s.ingest(reading(ts + 31, temperature=110), now=ts + 31)
    rows = s.data_flow()["readings"]
    assert all(
        any(route["representation"] == "INCIDENT_EVIDENCE" for route in row["routes"])
        for row in rows
    )
    with s.tx() as c:
        c.execute("DELETE FROM reading_routes")
        c.execute("DELETE FROM event_audit")
        c.execute("DELETE FROM outbox")
        body = json.loads(c.execute("SELECT body FROM readings LIMIT 1").fetchone()[0])
        body.pop("decision_version")
        c.execute(
            "UPDATE readings SET body=? WHERE id=?",
            (json.dumps(body), body["message_id"]),
        )
    assert not Store(s.path).data_flow()["events"]
    assert any(
        "decision_version" not in r and not r["routes"]
        for r in s.data_flow()["readings"]
    )


def test_api_auth_machine_filter_and_limits(tmp_path):
    app = create_app(path=tmp_path / "edge.db", key=KEY, background=False)
    s = app.state.store
    s.register("M-01", "Motor")
    s.ingest(reading(time.time()))
    client = TestClient(app)
    assert client.get("/api/data-flow").status_code == 401
    headers = {"X-API-Key": KEY}
    assert client.get("/api/data-flow?limit=101", headers=headers).status_code == 422
    result = client.get("/api/data-flow?machine=OTHER", headers=headers).json()
    assert (
        not result["readings"]
        and not result["events"]
        and result["storage"]["readings"] == 0
    )
    assert (
        client.get("/api/data-flow", headers=headers).json()["storage"]["readings"] == 1
    )


def test_completed_ledger_is_bounded_and_pending_survives(tmp_path):
    s = edge(tmp_path)
    with s.tx() as c:
        c.executemany(
            "INSERT INTO event_audit VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (str(i), "M-01", "machine", 0, "ACKNOWLEDGED", 0, i, i, None, 1, "{}")
                for i in range(2005)
            ],
        )
        c.execute(
            "INSERT INTO event_audit VALUES('pending','M-01','incident',3,'RETRYING',1,0,NULL,'offline',1,'{}')"
        )
        s.prune_audit(c)
        assert (
            c.execute(
                "SELECT COUNT(*) FROM event_audit WHERE status='ACKNOWLEDGED'"
            ).fetchone()[0]
            == 2000
        )
        assert (
            c.execute("SELECT status FROM event_audit WHERE id='pending'").fetchone()[0]
            == "RETRYING"
        )
