"""HTTP edge/cloud processes. Run exactly one worker per SQLite database."""

import asyncio
import gzip
import zlib
import json
import uuid
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .core import CapacityError, Store
from .runtime import RuntimeMonitor, ScenarioLab

log = logging.getLogger("edgeguard")


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    machine_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    message_id: str = Field(min_length=1, max_length=80)
    timestamp: float = Field(gt=0)
    values: dict[
        Literal["temperature", "vibration", "pressure", "current", "rpm"], float | None
    ]


class Machine(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    label: str = Field(min_length=1, max_length=80)
    limits: dict[str, list[float]] | None = None


class Action(BaseModel):
    action: Literal["acknowledge", "note", "close"]
    note: str = Field(default="", max_length=1000)


class Event(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=3)
    id: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=80)
    kind: Literal["machine", "incident"]
    version: int = Field(ge=1)
    payload: dict


class Fault(BaseModel):
    mode: Literal["online", "offline", "lose_ack"]


class LabRequest(BaseModel):
    scenario: Literal[
        "normal",
        "noisy_normal",
        "missing",
        "critical",
        "subthreshold",
        "combination",
        "healthy_shift",
    ]
    seconds: int = Field(default=120, ge=90, le=600)


class BandwidthBudget(BaseModel):
    bytes_per_second: int = Field(ge=1024, le=1048576)


class SyncWorker:
    def __init__(self, store, url, key):
        self.store, self.url, self.key = store, url, key
        self.status = "STARTING"
        self.last_success = None
        self.last_error = None
        self.bytes_per_second = max(
            1024, int(os.getenv("EDGEGUARD_UPLOAD_BPS", "32768"))
        )
        self.next_send_at = 0.0
        self.paced = False
        self.network = "STARTING"

    def network_change(self, value):
        if hasattr(self, "monitor"):
            self.monitor.cloud_offline = value == "OFFLINE"
        if self.network != value:
            self.store.log_operation(
                "CLOUD_" + value,
                "Cloud link restored; pending events can synchronise."
                if value == "ONLINE"
                else "Cloud requests failed; detection and buffering remain local.",
            )
            self.network = value

    async def once(self, client):
        item = await asyncio.to_thread(self.store.pending)
        self.paced = bool(item and time.monotonic() < self.next_send_at)
        if self.paced:
            return
        if item:
            item = await asyncio.to_thread(self.store.pending, claim=True)
        try:
            if not item:
                response = await client.get(self.url + "/health")
                response.raise_for_status()
                self.status = "CONNECTED"
                self.last_success = time.time()
                self.last_error = None
                self.network_change("ONLINE")
                return
            raw = item["body"].encode()
            packed = gzip.compress(raw, mtime=0)
            payload = packed if len(packed) < len(raw) else raw
            encoding = {"Content-Encoding": "gzip"} if payload is packed else {}
            self.next_send_at = time.monotonic() + len(payload) / self.bytes_per_second
            with self.store.tx() as c:
                self.store.count(
                    c, "attempted_payload_bytes", len(payload)
                )
                self.store.count(
                    c,
                    "retry_payload_bytes" if item["attempts"] else "first_attempt_payload_bytes",
                    len(payload),
                )
                self.store.count(c, "uncompressed_attempt_bytes", len(raw))
                self.store.count(c, "compression_input_bytes", len(raw))
                self.store.count(c, "compression_output_bytes", len(payload))
            response = await client.post(
                self.url + "/api/events",
                content=payload,
                headers={"X-API-Key": self.key, "Content-Type": "application/json", **encoding},
            )
            response.raise_for_status()
            if response.json().get("ack") != item["id"]:
                raise ValueError("Cloud returned an unexpected acknowledgement")
            await asyncio.to_thread(
                self.store.delivered, item["id"], len(payload)
            )
            self.status = "SYNCING" if self.store.snapshot()["pending"] else "CONNECTED"
            self.last_success = time.time()
            self.last_error = None
            self.network_change("ONLINE")
        except (httpx.HTTPError, ValueError) as exc:
            self.status = "OFFLINE"
            self.last_error = str(exc)[:200]
            self.network_change("OFFLINE")
            if item:
                await asyncio.to_thread(self.store.failed, item["id"], str(exc))

    async def run(self):
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            while True:
                await self.once(client)
                # At most four payloads per second; each payload capped by HTTP layer.
                await asyncio.sleep(0.25 if self.status == "SYNCING" else 1)


def create_app(role=None, path=None, key=None, background=True):
    role = role or os.getenv("EDGEGUARD_ROLE", "edge")
    if role not in ("edge", "cloud"):
        raise ValueError("EDGEGUARD_ROLE must be edge or cloud")
    key = key or os.getenv("EDGEGUARD_API_KEY", "")
    if len(key) < 24:
        raise RuntimeError(
            "Set EDGEGUARD_API_KEY to a random secret of at least 24 characters"
        )
    store = Store(
        path or os.getenv("EDGEGUARD_DB", f"data/{role}.db"),
        max_queue=int(os.getenv("EDGEGUARD_QUEUE_LIMIT", "2000")),
    )
    worker = SyncWorker(
        store,
        os.getenv("EDGEGUARD_CLOUD_URL", "http://127.0.0.1:8001"),
        os.getenv("EDGEGUARD_CLOUD_KEY", key),
    )
    detector = None
    model_path = os.getenv("EDGEGUARD_MODEL")
    model_machine = os.getenv("EDGEGUARD_MODEL_MACHINE")
    if model_path and role == "edge":
        if not model_machine:
            raise RuntimeError(
                "Set EDGEGUARD_MODEL_MACHINE to bind the calibrated model to one machine"
            )
        from .model import Detector

        detector = Detector(model_path)
    tasks = []
    monitor = RuntimeMonitor()
    worker.monitor = monitor
    lab = ScenarioLab(store, monitor, detector, model_machine)

    @asynccontextmanager
    async def lifespan(app):
        if role == "edge" and background:
            tasks.append(asyncio.create_task(worker.run()))
        yield
        await lab.stop()
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title=f"EdgeGuard {role}", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.store = store
    app.state.worker = worker
    app.state.fault = "online"
    app.state.lab = lab

    async def auth(x_api_key: str = Header(default="")):
        if not secrets.compare_digest(x_api_key, key):
            raise HTTPException(401, "Valid X-API-Key required")

    @app.middleware("http")
    async def size_limit(request: Request, call_next):
        # Bound bytes even for chunked requests, before Pydantic allocates a payload.
        if request.method in ("POST", "PUT", "PATCH"):
            body = bytearray()
            async for part in request.stream():
                body.extend(part)
                if len(body) > 262144:
                    return JSONResponse({"detail": "Payload exceeds 256 KiB"}, 413)
            if request.headers.get("content-encoding", "identity") == "gzip":
                try:
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    body = decoder.decompress(bytes(body), 262145)
                    if len(body) > 262144 or decoder.unconsumed_tail:
                        return JSONResponse({"detail": "Expanded payload exceeds 256 KiB"}, 413)
                    if not decoder.eof or decoder.unused_data:
                        return JSONResponse({"detail": "Invalid gzip body"}, 400)
                except zlib.error:
                    return JSONResponse({"detail": "Invalid gzip body"}, 400)
            elif request.headers.get("content-encoding", "identity") != "identity":
                return JSONResponse({"detail": "Unsupported content encoding"}, 415)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(CapacityError)
    async def capacity(request, exc):
        return JSONResponse({"detail": str(exc)}, 503, headers={"Retry-After": "30"})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.get("/health")
    def health():
        if role == "cloud" and app.state.fault == "offline":
            raise HTTPException(503, "Injected cloud outage")
        return {"role": role, "status": "ok"}

    @app.get("/api/state", dependencies=[Depends(auth)])
    def state():
        return dict(
            store.snapshot(cloud=role == "cloud"),
            role=role,
            connection=dict(
                status=worker.status if role == "edge" else ("INGESTION_PAUSED" if app.state.fault == "offline" else "ACCEPTING_EVENTS"),
                last_success=worker.last_success,
                error=worker.last_error,
            ),
            model=dict(
                status="AVAILABLE" if detector else "NOT_CALIBRATED",
                machine=model_machine if role == "edge" else None,
                version=detector.version if detector else None,
                source_type=detector.source_type if detector else None,
                threshold=detector.threshold if detector else None,
            ),
            fault_controls=os.getenv("EDGEGUARD_ENABLE_FAULTS") == "1",
            cloud_fault_mode=app.state.fault if role == "cloud" else None,
        )

    @app.get("/api/data-flow", dependencies=[Depends(auth)])
    def data_flow(
        machine: str | None = None, limit: int = Query(default=100, ge=1, le=100)
    ):
        return store.data_flow(machine, limit, cloud=role == "cloud")

    @app.get("/api/operations", dependencies=[Depends(auth)])
    def operations():
        return dict(
            store.operations(),
            runtime=monitor.snapshot(),
            bandwidth=dict(
                bytes_per_second=worker.bytes_per_second,
                paced=worker.paced,
                wait_seconds=max(0, worker.next_send_at - time.monotonic()),
                burst_bytes=262144,
            ),
            lab=dict(lab.state),
            fault=app.state.fault if role == "cloud" else None,
        )

    @app.get("/api/experiments", dependencies=[Depends(auth)])
    def experiments():
        with store.tx() as c:
            return [json.loads(r["body"]) for r in c.execute("SELECT body FROM experiments ORDER BY rowid DESC LIMIT 5")]

    if role == "edge":

        @app.post("/api/testing/experiment", dependencies=[Depends(auth)])
        async def experiment():
            require_lab()
            if getattr(app.state, "experiment_running", False):
                raise HTTPException(409, "Experiment already running")
            from .experiment import run_experiment
            app.state.experiment_running = True
            run_id = str(uuid.uuid4())
            with store.tx() as c:
                c.execute("INSERT INTO experiments VALUES(?,?)", (run_id, json.dumps(dict(id=run_id, status="RUNNING"))))
            async def execute():
                try:
                    result = await run_experiment()
                    result.update(id=run_id)
                except Exception as exc:
                    result = dict(id=run_id, status="FAIL", error=str(exc))
                finally:
                    app.state.experiment_running = False
                with store.tx() as c:
                    c.execute("UPDATE experiments SET body=? WHERE id=?", (json.dumps(result), run_id))
                    c.execute("DELETE FROM experiments WHERE id NOT IN (SELECT id FROM experiments ORDER BY rowid DESC LIMIT 5)")
            tasks[:] = [task for task in tasks if not task.done()]
            tasks.append(asyncio.create_task(execute()))
            return {"id": run_id, "status": "RUNNING"}

        def require_lab():
            if os.getenv("EDGEGUARD_ENABLE_FAULTS") != "1":
                raise HTTPException(
                    404,
                    "Set EDGEGUARD_ENABLE_FAULTS=1 and restart to enable Scenario Lab",
                )

        @app.post("/api/testing/scenario", dependencies=[Depends(auth)])
        async def start_scenario(body: LabRequest):
            require_lab()
            result = await lab.start(body.scenario, body.seconds)
            store.log_operation(
                "SCENARIO_STARTED", "Synthetic scenario: " + body.scenario
            )
            return result

        @app.post("/api/testing/stop", dependencies=[Depends(auth)])
        async def stop_scenario():
            require_lab()
            return await lab.stop()

        @app.post("/api/testing/bandwidth", dependencies=[Depends(auth)])
        def bandwidth(body: BandwidthBudget):
            require_lab()
            worker.bytes_per_second = body.bytes_per_second
            store.log_operation(
                "BANDWIDTH_CHANGED",
                f"Upload budget: {body.bytes_per_second} payload bytes/s; effective for subsequent sends.",
            )
            return {"bytes_per_second": worker.bytes_per_second}

        @app.post("/api/testing/cloud", dependencies=[Depends(auth)])
        async def cloud_fault(body: Fault):
            require_lab()
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                try:
                    response = await client.post(
                        worker.url + "/api/testing/fault",
                        json=body.model_dump(),
                        headers={"X-API-Key": worker.key},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise HTTPException(
                        502,
                        "Cloud control request failed. Check cloud availability and enable fault controls on both nodes.",
                    ) from exc
            store.log_operation("FAULT_CONTROL", "Requested cloud mode: " + body.mode)
            return response.json()

        @app.post("/api/machines", dependencies=[Depends(auth)], status_code=201)
        def register(machine: Machine):
            return store.register(machine.id, machine.label, machine.limits)

        @app.post("/api/readings", dependencies=[Depends(auth)])
        def ingest(reading: Reading):
            return monitor.ingest(
                store,
                reading.model_dump(),
                detector if reading.machine_id == model_machine else None,
            )

        @app.get("/api/machines/{machine}/history", dependencies=[Depends(auth)])
        def history(machine: str):
            return store.history(machine)

        @app.post("/api/incidents/{incident}/actions", dependencies=[Depends(auth)])
        def incident_action(incident: str, action: Action):
            return store.action(incident, action.action, action.note)

    if role == "cloud":

        @app.post("/api/events", dependencies=[Depends(auth)])
        def event(event: Event):
            if app.state.fault == "offline":
                raise HTTPException(503, "Injected cloud outage")
            if (
                event.payload.get("id") != event.entity_id
                or event.payload.get("version") != event.version
            ):
                raise HTTPException(422, "Envelope and payload do not match")
            result = store.receive(event.model_dump())
            if app.state.fault == "lose_ack":
                app.state.fault = "online"
                raise HTTPException(
                    503, "Event committed, acknowledgement deliberately withheld"
                )
            return result

        @app.post("/api/testing/fault", dependencies=[Depends(auth)])
        def fault(fault: Fault):
            if os.getenv("EDGEGUARD_ENABLE_FAULTS") != "1":
                raise HTTPException(404)
            app.state.fault = fault.mode
            return {"mode": fault.mode}

    static = Path(os.getenv("EDGEGUARD_STATIC", "frontend/dist"))
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="interface")
    return app
