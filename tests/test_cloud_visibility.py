import json
import sqlite3
import time

from fastapi.testclient import TestClient

from edgeguard.api import create_app
from edgeguard.core import Store

KEY = 'cloud-visibility-test-secret-12345'


def test_cloud_receipt_tracks_applied_version_not_retry_or_opening(tmp_path):
    edge = Store(tmp_path / 'edge.db')
    cloud = Store(tmp_path / 'cloud.db')
    edge.register('ML-01', 'Synthetic motor')
    now = time.time()
    edge.ingest(dict(machine_id='ML-01', message_id='critical-1', timestamp=now,
                     values=dict(temperature=110, vibration=2, pressure=5, current=8, rpm=1480)))
    first = json.loads(edge.pending()['body'])
    cloud.receive(first)
    incident_id = first['entity_id']
    edge.action(incident_id, 'acknowledge')
    with edge.tx() as c:
        updated = json.loads(c.execute('SELECT body FROM outbox WHERE priority=2').fetchone()[0])
    cloud.receive(updated)
    saved = cloud.snapshot(cloud=True)['incidents'][0]
    assert saved['status'] == 'ACKNOWLEDGED'
    assert saved['opened_at'] == now
    assert saved['cloud_event_id'] == updated['id']
    assert saved['cloud_received_at'] >= now
    cloud.receive(first)
    delayed = dict(first, id='late-old-version')
    cloud.receive(delayed)
    restarted = Store(cloud.path).snapshot(cloud=True)['incidents'][0]
    assert restarted == saved
    assert cloud.snapshot(cloud=True)['counters']['duplicates_ignored'] == 1


def test_legacy_cloud_schema_migrates_without_inventing_receipt(tmp_path):
    path = tmp_path / 'cloud.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE cloud_state(id TEXT PRIMARY KEY, version INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)')
        c.execute('INSERT INTO cloud_state VALUES(?,?,?,?)', ('old', 1, 'incident', json.dumps(dict(id='old', version=1, status='OPEN'))))
    cloud = Store(path)
    old = cloud.snapshot(cloud=True)['incidents'][0]
    assert old['cloud_received_at'] is None and old['cloud_event_id'] is None
    cloud.receive(dict(id='new', entity_id='old', kind='incident', version=2,
                       payload=dict(id='old', version=2, status='ACKNOWLEDGED', machine='ML-01')))
    assert cloud.snapshot(cloud=True)['incidents'][0]['cloud_event_id'] == 'new'


def test_cloud_receiver_status_is_not_edge_connectivity(tmp_path, monkeypatch):
    monkeypatch.setenv('EDGEGUARD_ENABLE_FAULTS', '1')
    app = create_app('cloud', tmp_path / 'cloud.db', KEY, background=False)
    headers = {'X-API-Key': KEY}
    with TestClient(app) as client:
        state = client.get('/api/state', headers=headers).json()
        assert state['connection']['status'] == 'ACCEPTING_EVENTS'
        assert state['last_received_at'] is None
        client.post('/api/testing/fault', headers=headers, json={'mode':'offline'})
        state = client.get('/api/state', headers=headers).json()
        assert state['connection']['status'] == 'INGESTION_PAUSED'
        assert state['cloud_fault_mode'] == 'offline'
        client.post('/api/testing/fault', headers=headers, json={'mode':'online'})
        assert client.get('/api/state', headers=headers).json()['connection']['status'] == 'ACCEPTING_EVENTS'
