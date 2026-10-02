import asyncio
import json
import time
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient
from edgeguard.api import SyncWorker, create_app
from edgeguard.core import CapacityError, Store

KEY = "test-only-key-not-for-deployment-1234"


def sample(ts=None, **values):
    return dict(
        machine_id="M-01",
        message_id=str(uuid.uuid4()),
        timestamp=ts or time.time(),
        values=dict(
            temperature=values.get("temperature", 60),
            vibration=values.get("vibration", 2.4),
            pressure=values.get("pressure", 5),
            current=values.get("current", 8),
            rpm=values.get("rpm", 1480),
        ),
    )


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "edge.db")
    s.register("M-01", "Motor")
    return s


def test_critical_survives_restart_and_synchronises(store, tmp_path):
    store.ingest(sample(temperature=110))
    restarted = Store(store.path)
    assert restarted.snapshot()["incidents"][0]["severity"] == "CRITICAL"
    cloud = Store(tmp_path / "cloud.db")
    while item := restarted.pending():
        cloud.receive(json.loads(item["body"]))
        restarted.delivered(item["id"], len(item["body"]))
    assert restarted.snapshot()["pending"] == 0
    assert cloud.snapshot(cloud=True)["incidents"][0]["severity"] == "CRITICAL"


def test_replay_after_lost_ack_is_idempotent(store, tmp_path):
    store.ingest(sample(temperature=110))
    cloud = Store(tmp_path / "cloud.db")
    item = store.pending()
    event = json.loads(item["body"])
    assert cloud.receive(event)["duplicate"] is False
    assert cloud.receive(event)["duplicate"] is True
    assert len(cloud.snapshot(cloud=True)["incidents"]) == 1
    assert cloud.snapshot(cloud=True)["counters"]["duplicates_ignored"] == 1


def test_duplicate_reading_and_conflicting_id(store):
    r = sample()
    store.ingest(r)
    assert store.ingest(r)["duplicate"]
    assert store.snapshot()["counters"]["readings_processed"] == 1
    r["values"]["temperature"] = 110
    with pytest.raises(ValueError, match="reused"):
        store.ingest(r)


def test_missing_invalid_and_stale_inputs(store):
    now = time.time()
    store.ingest(sample(now - 30, vibration=None, pressure=-1), now=now)
    m = store.snapshot()["machines"][0]
    assert m["health"] == "UNKNOWN"
    assert not store.snapshot()["incidents"]
    store.ingest(sample(now, temperature=110, vibration=None))
    m = store.snapshot()["machines"][0]
    assert m["health"] == "CRITICAL"
    assert m["quality"]["vibration"] == "MISSING"
    assert len(store.snapshot()["incidents"]) == 1


def test_out_of_order_never_overwrites(store):
    now = time.time()
    store.ingest(sample(now, temperature=110))
    with pytest.raises(ValueError, match="Out-of-order"):
        store.ingest(sample(now - 1))
    assert store.snapshot()["machines"][0]["health"] == "CRITICAL"


def test_warning_debounce(store):
    now = time.time()
    for i in range(2):
        store.ingest(sample(now + i, temperature=85), now=now + i)
    assert not store.snapshot()["incidents"]
    store.ingest(sample(now + 2, temperature=85), now=now + 2)
    assert len(store.snapshot()["incidents"]) == 1


def test_evidence_and_operator_workflow(store):
    now = time.time() - 70
    for i in range(66):
        store.ingest(
            sample(now + i, temperature=110 if 30 <= i < 35 else 60), now=now + i
        )
    incident = store.snapshot()["incidents"][0]
    assert incident["capture_complete"]
    assert incident["pre_seconds"] == 30
    assert len(incident["evidence"]) == 61
    assert incident["status"] == "RECOVERED"
    store.action(incident["id"], "acknowledge")
    store.action(incident["id"], "note", "Inspected bearing mount")
    store.action(incident["id"], "close")
    assert store.snapshot()["incidents"][0]["status"] == "CLOSED"
    assert store.snapshot()["machines"][0]["active"] is None


def test_cannot_close_active_or_stale_incident(store):
    store.ingest(sample(temperature=110))
    incident = store.snapshot()["incidents"][0]
    with pytest.raises(ValueError, match="confirmed"):
        store.action(incident["id"], "close")


def test_capacity_drops_routine_first_and_rolls_back_incident(tmp_path):
    s = Store(tmp_path / "tiny.db", max_queue=1)
    s.register("M-01", "Motor")
    now = time.time()
    s.ingest(sample(now))
    s.ingest(sample(now + 0.1, temperature=110), now=now + 0.1)
    assert s.snapshot()["counters"]["routine_events_dropped"] == 1
    incident = s.snapshot()["incidents"][0]
    with pytest.raises(CapacityError):
        s.action(incident["id"], "note", "Must not partially commit")
    assert s.snapshot()["incidents"][0]["notes"] == []
    assert s.snapshot()["pending"] == 1


def test_newer_cloud_version_wins(store, tmp_path):
    store.ingest(sample(temperature=110))
    i = store.snapshot()["incidents"][0]
    store.action(i["id"], "acknowledge")
    cloud = Store(tmp_path / "cloud.db")
    with store.tx() as c:
        events = [
            json.loads(r["body"])
            for r in c.execute(
                "SELECT body FROM outbox WHERE priority>0 ORDER BY rowid DESC"
            )
        ]
    for event in events:
        cloud.receive(event)
    assert cloud.snapshot(cloud=True)["incidents"][0]["status"] == "ACKNOWLEDGED"


def test_rolling_retention(store):
    now = time.time() - 650
    for i in range(605):
        store.ingest(sample(now + i), now=now + i)
    with store.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 600


def test_auth_validation_and_real_http_ingestion(tmp_path):
    app = create_app("edge", tmp_path / "edge.db", KEY, background=False)
    with TestClient(app) as c:
        assert c.get("/api/state").status_code == 401
        h = {"X-API-Key": KEY}
        assert (
            c.post(
                "/api/machines", headers=h, json={"id": "M-01", "label": "Motor"}
            ).status_code
            == 201
        )
        assert (
            c.post("/api/readings", headers=h, json=sample(temperature=110)).status_code
            == 200
        )
        assert (
            c.get("/api/state", headers=h).json()["incidents"][0]["severity"]
            == "CRITICAL"
        )
        assert c.post("/api/readings", headers=h, json={"bad": True}).status_code == 422
        assert (
            c.post("/api/readings", headers=h, content="x" * 262145).status_code == 413
        )


def test_faults_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("EDGEGUARD_ENABLE_FAULTS", raising=False)
    with TestClient(
        create_app("cloud", tmp_path / "cloud.db", KEY, background=False)
    ) as c:
        assert (
            c.post(
                "/api/testing/fault",
                headers={"X-API-Key": KEY},
                json={"mode": "offline"},
            ).status_code
            == 404
        )


def test_worker_against_cloud_loss_of_ack(store, tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEGUARD_ENABLE_FAULTS", "1")
    cloud = create_app("cloud", tmp_path / "cloud.db", KEY, background=False)
    store.ingest(sample(temperature=110))
    cloud.state.fault = "lose_ack"
    worker = SyncWorker(store, "http://cloud", KEY)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cloud), base_url="http://cloud"
        ) as client:
            await worker.once(client)
            assert worker.status == "OFFLINE"
            assert store.snapshot()["pending"] > 0
            with store.tx() as c:
                c.execute("UPDATE outbox SET due=0")
            await worker.once(client)
            assert worker.status in ("CONNECTED", "SYNCING")

    asyncio.run(run())
    assert cloud.state.store.snapshot(cloud=True)["counters"]["duplicates_ignored"] == 1


def test_cloud_outage_does_not_block_ingestion(store, tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEGUARD_ENABLE_FAULTS", "1")
    cloud = create_app("cloud", tmp_path / "cloud.db", KEY, background=False)
    cloud.state.fault = "offline"
    store.ingest(sample(temperature=110))
    worker = SyncWorker(store, "http://cloud", KEY)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cloud)
        ) as client:
            await worker.once(client)

    asyncio.run(run())
    store.ingest(sample(temperature=111))
    assert store.snapshot()["counters"]["readings_processed"] == 2
    assert store.snapshot()["incidents"][0]["severity"] == "CRITICAL"
    assert worker.status == "OFFLINE"


def test_failed_model_cannot_disable_critical_rules(store):
    class Broken:
        def evaluate(self, values):
            raise RuntimeError("Model unavailable")

    store.ingest(sample(temperature=110), Broken())
    m = store.snapshot()["machines"][0]
    assert m["latest"]["ml"]["status"] == "MODEL_ERROR"
    assert m["health"] == "CRITICAL"
    assert store.snapshot()["incidents"][0]["severity"] == "CRITICAL"
