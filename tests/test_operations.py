import asyncio
import gzip
import json
import time
import uuid

import httpx
from fastapi.testclient import TestClient

from edgeguard.api import SyncWorker, create_app
from edgeguard.core import Store
from edgeguard.runtime import RuntimeMonitor

KEY = 'operations-test-key-at-least-24-chars'


def sample():
    return dict(machine_id='M-01', message_id=str(uuid.uuid4()), timestamp=time.time(),
                values=dict(temperature=110, vibration=None, pressure=5, current=8, rpm=1480))


def test_offline_measurements_quality_and_restart(tmp_path):
    store = Store(tmp_path / 'edge.db')
    store.register('M-01', 'Motor')
    monitor = RuntimeMonitor()
    monitor.cloud_offline = True
    row = sample()
    monitor.ingest(store, row, None)
    monitor.ingest(store, row, None)
    metrics = monitor.snapshot()
    assert metrics['offline_readings'] == metrics['offline_critical'] == 1
    assert metrics['accepted'] == 1
    assert metrics['processing_p95_ms'] >= 0
    saved = store.history('M-01')[0]
    assert saved['quality']['vibration'] == 'MISSING'
    assert saved['level'] == 'CRITICAL'
    assert saved['filtered'] == {}
    store.log_operation('CLOUD_OFFLINE', 'Test connection failure')
    restarted = Store(store.path).operations()
    assert restarted['timeline'][0]['kind'] == 'CLOUD_OFFLINE'
    assert restarted['retained_readings'] == 1
    assert restarted['queue_by_priority'][0]['priority'] == 3


def test_pacing_and_retry_byte_accounting(tmp_path):
    store = Store(tmp_path / 'edge.db')
    store.register('M-01', 'Motor')
    store.ingest(sample())
    worker = SyncWorker(store, 'http://cloud', KEY)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            worker.next_send_at = time.monotonic() + 60
            await worker.once(client)
            assert worker.paced and not requests
            worker.next_send_at = 0
            await worker.once(client)
            assert worker.status == 'OFFLINE'
            with store.tx() as c:
                c.execute('UPDATE outbox SET due=0')
            worker.next_send_at = 0
            await worker.once(client)
    asyncio.run(exercise())
    counters = store.snapshot()['counters']
    assert len(requests) == 2
    assert counters['retry_payload_bytes'] > 0
    assert counters['attempted_payload_bytes'] == counters['first_attempt_payload_bytes'] + counters['retry_payload_bytes']
    assert json.loads(gzip.decompress(requests[0].content))['id'] == json.loads(gzip.decompress(requests[1].content))['id']


def test_lab_auth_enablement_lifecycle_and_budgets(tmp_path, monkeypatch):
    monkeypatch.delenv('EDGEGUARD_ENABLE_FAULTS', raising=False)
    app = create_app(path=tmp_path / 'edge.db', key=KEY, background=False)
    headers = {'X-API-Key': KEY}
    with TestClient(app) as client:
        assert client.get('/api/operations').status_code == 401
        assert client.post('/api/testing/scenario', headers=headers, json={'scenario':'normal'}).status_code == 404
        monkeypatch.setenv('EDGEGUARD_ENABLE_FAULTS', '1')
        assert client.post('/api/testing/bandwidth', headers=headers, json={'bytes_per_second':0}).status_code == 422
        assert client.post('/api/testing/bandwidth', headers=headers, json={'bytes_per_second':4096}).status_code == 200
        assert client.post('/api/testing/scenario', headers=headers, json={'scenario':'normal'}).status_code == 200
        assert client.post('/api/testing/scenario', headers=headers, json={'scenario':'critical'}).status_code == 409
        ops = client.get('/api/operations', headers=headers).json()
        assert ops['lab']['status'] == 'RUNNING'
        assert ops['bandwidth']['bytes_per_second'] == 4096
        assert sum(x['kind'] == 'SCENARIO_STARTED' for x in ops['timeline']) == 1
        assert client.post('/api/testing/stop', headers=headers).status_code == 200
        assert client.get('/api/operations', headers=headers).json()['lab']['status'] == 'STOPPED'
