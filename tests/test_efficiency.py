import asyncio
import gzip
import json
import time
import uuid

from fastapi.testclient import TestClient

from edgeguard.api import create_app
from edgeguard.core import Store
from edgeguard.experiment import run_experiment

KEY='efficiency-test-secret-123456789'


def feed(store,t,temp=60):
    return store.ingest(dict(machine_id='M-01',message_id=str(uuid.uuid4()),timestamp=t,
        values=dict(temperature=temp,vibration=2,pressure=5,current=8,rpm=1480)),now=t)


def test_coalescing_preserves_incidents_attempted_and_inflight(tmp_path):
    store=Store(tmp_path/'edge.db');store.register('M-01','Motor');t=time.time()
    feed(store,t);first=store.pending()['id']
    feed(store,t+16)
    assert next(e for e in store.data_flow()['events'] if e['id']==first)['status']=='SUPERSEDED'
    assert store.snapshot()['pending']==1
    claimed=store.pending(claim=True)['id']
    feed(store,t+32)
    assert store.snapshot()['pending']==2
    store.failed(claimed,'Offline')
    feed(store,t+48)
    with store.tx() as c:
        assert c.execute('SELECT 1 FROM outbox WHERE id=?',(claimed,)).fetchone()
    feed(store,t+49,110)
    with store.tx() as c:
        incident_ids={r[0] for r in c.execute('SELECT id FROM outbox WHERE priority>0')}
    feed(store,t+65)
    with store.tx() as c:
        assert incident_ids <= {r[0] for r in c.execute('SELECT id FROM outbox')}
    assert Store(store.path).snapshot()['counters']['routine_events_superseded']>=2


def test_gzip_ingestion_and_expansion_limits(tmp_path):
    app=create_app('cloud',tmp_path/'cloud.db',KEY,background=False)
    headers={'X-API-Key':KEY,'Content-Encoding':'gzip','Content-Type':'application/json'}
    payload=dict(id='e1',entity_id='i1',version=1,kind='incident',priority=3,
        payload=dict(id='i1',machine='M-01',version=1,status='OPEN'))
    with TestClient(app) as c:
        packed=gzip.compress(json.dumps(payload).encode())
        assert c.post('/api/events',content=packed,headers=headers).json()['ack']=='e1'
        assert c.post('/api/events',content=packed,headers=headers).json()['duplicate']
        assert c.post('/api/events',content=b'invalid',headers=headers).status_code==400
        assert c.post('/api/events',content=gzip.compress(b'a'*300000),headers=headers).status_code==413
        assert c.post('/api/events',content=packed[:-5],headers=headers).status_code==400


def test_isolated_experiment():
    result=asyncio.run(run_experiment())
    assert result['status']=='PASS', result
    assert len(result['checks'])==7
    assert result['superseded_summaries']>0
    assert result['retry_payload_bytes']>0
