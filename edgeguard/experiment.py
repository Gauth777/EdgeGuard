"""Isolated functional experiment; accelerated sensor time, real retry/pacing waits."""
import asyncio
import tempfile
import time
import uuid
from pathlib import Path

import httpx


async def run_experiment():
    from .api import SyncWorker, create_app
    from .core import Store
    from .runtime import RuntimeMonitor

    checks = []
    def check(name, passed, detail):
        checks.append(dict(name=name, status='PASS' if passed else 'FAIL', detail=detail))

    with tempfile.TemporaryDirectory(prefix='edgeguard-experiment-') as folder:
        key = 'isolated-experiment-key-123456789'
        cloud = create_app('cloud', Path(folder) / 'cloud.db', key, background=False)
        edge = Store(Path(folder) / 'edge.db')
        edge.register('CHECK-01', 'Isolated synthetic motor')
        worker = SyncWorker(edge, 'http://isolated-cloud', key)
        monitor = RuntimeMonitor()
        worker.monitor = monitor
        base = time.time() - 180
        # Historical timestamps must still be fresh relative to ingestion. Exercise the domain
        # with an explicit simulated clock, as the deterministic evaluation does.
        def feed(t, temp):
            return edge.ingest(dict(machine_id='CHECK-01', message_id=str(uuid.uuid4()), timestamp=base+t,
                values=dict(temperature=temp, vibration=2, pressure=5, current=8, rpm=1480)), now=base+t)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=cloud), base_url='http://isolated-cloud') as client:
            async def drain(timeout=15):
                started = time.monotonic()
                while edge.snapshot()['pending'] and time.monotonic()-started < timeout:
                    await worker.once(client)
                    await asyncio.sleep(0.05)
                return time.monotonic()-started

            feed(0, 60)
            await drain()
            for t in (1,2,3): feed(t, 85)
            await drain()
            incident = edge.snapshot()['incidents'][0]
            check('Warning before outage', incident['severity']=='WARNING', {'incident_id':incident['id'], 'sensor_time':base+3})
            cloud.state.fault = 'offline'
            feed(4, 85)
            # Create a real failed cloud request before critical escalation.
            edge.action(incident['id'], 'note', 'Outage checkpoint')
            await worker.once(client)
            if worker.status != 'OFFLINE':
                await asyncio.sleep(max(0,worker.next_send_at-time.monotonic())+.01)
                await worker.once(client)
            critical = feed(5, 110)
            event = next(e for e in edge.data_flow()['events'] if e['priority']==3)
            check('Critical detected while cloud rejects requests', worker.status=='OFFLINE' and critical['machine']['health']=='CRITICAL', {'event_id':event['id'], 'sensor_time':base+5, 'cloud_status':worker.status})
            edge.action(incident['id'], 'acknowledge')
            edge.action(incident['id'], 'note', 'OFFLINE VERIFIED '+incident['id'])
            for t in range(6,40): feed(t, 110)
            before = cloud.state.store.snapshot(cloud=True)['incidents'][0]
            check('Offline actions isolated and evidence buffered', before['acknowledged_at'] is None and edge.snapshot()['pending']>0 and edge.snapshot()['incidents'][0]['capture_complete'], {'pending':edge.snapshot()['pending'], 'cloud_revision':before['version']})
            # Every important buffered event must have a matching receipt after recovery.
            with edge.tx() as c:
                important = [r[0] for r in c.execute('SELECT id FROM outbox WHERE priority>0')]
            for t in range(40,46): feed(t,60)
            with edge.tx() as c:
                important = [r[0] for r in c.execute('SELECT id FROM outbox WHERE priority>0')]
            cloud.state.fault = 'online'
            elapsed = await drain()
            remote = cloud.state.store.snapshot(cloud=True)['incidents'][0]
            with cloud.state.store.tx() as c:
                receipts = {r[0] for r in c.execute('SELECT id FROM receipts')}
            missing = sorted(set(important)-receipts)
            check('Buffered incident events received', not missing and edge.snapshot()['pending']==0, {'expected_event_ids':important,'missing_event_ids':missing,'drain_wall_seconds':round(elapsed,3)})
            check('Acknowledgement, note and recovery synchronised', remote['acknowledged_at'] is not None and any(n['text'].startswith('OFFLINE VERIFIED') for n in remote['notes']) and remote['status']=='RECOVERED', {'incident_id':remote['id'],'cloud_revision':remote['version'],'status':remote['status']})
            # Lose the response after committing; the worker must retry the same ID.
            edge.action(incident['id'], 'note', 'Lost acknowledgement exercise')
            lost = edge.pending()['id']
            cloud.state.fault = 'lose_ack'
            await drain()
            counts = cloud.state.store.snapshot(cloud=True)['counters']
            check('Lost acknowledgement deduplicated', counts.get('duplicates_ignored',0)>=1 and edge.snapshot()['pending']==0, {'retried_event_id':lost,'duplicate_attempts_ignored':counts.get('duplicates_ignored',0)})
            # Separate normal-operation comparison, not incident-heavy traffic.
            normal = Store(Path(folder) / 'normal.db')
            normal.register('NORMAL-01','Normal payload comparison')
            normal_worker = SyncWorker(normal,'http://isolated-cloud',key)
            for t in range(61):
                normal.ingest(dict(machine_id='NORMAL-01',message_id=str(uuid.uuid4()), timestamp=base+t,
                    values=dict(temperature=60+t%3/10,vibration=2,pressure=5,current=8,rpm=1480)),now=base+t)
                if normal.snapshot()['pending']:
                    await asyncio.sleep(max(0,normal_worker.next_send_at-time.monotonic()))
                    await normal_worker.once(client)
            metrics = normal.snapshot()['counters']
            baseline = metrics.get('baseline_payload_bytes',0)
            sent = metrics.get('attempted_payload_bytes',0)
            check('Normal payload reduction', sent<baseline and normal.snapshot()['pending']==0, {'raw_baseline_bytes':baseline,'upload_body_bytes':sent,'reduction_percent':round(100*(1-sent/baseline),2),'readings':61,'http_overhead_included':False})
        counters = edge.snapshot()['counters']
        return dict(status='PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL', completed_at=time.time(),
            scope='Isolated synthetic functional test. Accelerated sensor timestamps; in-process HTTP; real retry/pacing waits. No hardware, real-network or ML accuracy claim.', checks=checks,
            superseded_summaries=counters.get('routine_events_superseded',0), retry_payload_bytes=counters.get('retry_payload_bytes',0))


if __name__ == '__main__':
    import json
    print(json.dumps(asyncio.run(run_experiment()), indent=2))
