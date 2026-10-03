"""Measured process usage and an explicitly synthetic scenario source."""

import asyncio
import ctypes
import os
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path


def memory_rss():
    if sys.platform.startswith("linux"):
        return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf(
            "SC_PAGE_SIZE"
        )
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (x, ctypes.c_size_t)
                for x in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                )
            ]

        values = Counters()
        values.cb = ctypes.sizeof(values)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(values), values.cb
        ):
            return values.WorkingSetSize
    return None


class RuntimeMonitor:
    def __init__(self):
        self.started = time.monotonic()
        self.last_wall = self.started
        self.last_cpu = time.process_time()
        self.cpu = None
        self.timings = deque(maxlen=256)
        self.lock = threading.Lock()
        self.accepted = 0
        self.errors = 0
        self.recent = deque(maxlen=10000)
        self.cloud_offline = False
        self.offline_readings = 0
        self.offline_critical = 0

    def ingest(self, store, message, detector):
        start = time.perf_counter()
        try:
            result = store.ingest(message, detector)
            with self.lock:
                self.accepted += not result.get("duplicate", False)
                if not result.get("duplicate", False):
                    self.recent.append(time.monotonic())
                    if self.cloud_offline:
                        self.offline_readings += 1
                        self.offline_critical += (
                            result["machine"]["health"] == "CRITICAL"
                        )
            return result
        except Exception:
            with self.lock:
                self.errors += 1
            raise
        finally:
            with self.lock:
                self.timings.append((time.perf_counter() - start) * 1000)

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            cpu = time.process_time()
            if now - self.last_wall >= 0.5:
                self.cpu = 100 * (cpu - self.last_cpu) / (now - self.last_wall)
                self.last_wall, self.last_cpu = now, cpu
            durations = sorted(self.timings)
            try:
                rss = memory_rss()
            except (OSError, ValueError, IndexError):
                rss = None
            return dict(
                cpu_percent=self.cpu,
                rss_bytes=rss,
                uptime_seconds=now - self.started,
                processing_p95_ms=durations[
                    min(len(durations) - 1, int(len(durations) * 0.95))
                ]
                if durations
                else None,
                processing_samples=len(durations),
                accepted=self.accepted,
                rejected=self.errors,
                readings_per_second=sum(t >= now - 10 for t in self.recent)
                / max(1, min(10, now - self.started)),
                offline_readings=self.offline_readings,
                offline_critical=self.offline_critical,
                memory_budget_mb=int(os.getenv("EDGEGUARD_MEMORY_BUDGET_MB", "512")),
                cpu_budget_percent=100,
                native_limits="observed, not OS-enforced",
            )


class ScenarioLab:
    def __init__(self, store, monitor, detector, model_machine):
        self.store, self.monitor, self.detector, self.model_machine = (
            store,
            monitor,
            detector,
            model_machine,
        )
        self.task = None
        self.state = dict(
            status="IDLE", scenario=None, machine=None, sent=0, seconds=0, error=None
        )

    async def start(self, scenario, seconds=120):
        if self.task and not self.task.done():
            raise ValueError("Stop the current scenario before starting another")
        # Never feed generated data to a model calibrated on real equipment.
        synthetic_model = (
            self.detector and getattr(self.detector, "source_type", None) == "synthetic"
        )
        machine = self.model_machine if synthetic_model else "LAB-01"
        model = self.detector if synthetic_model else None
        with self.store.tx() as c:
            exists = c.execute(
                "SELECT body FROM machines WHERE id=?", (machine,)
            ).fetchone()
        if exists and not synthetic_model:
            import json

            if json.loads(exists["body"])["label"] != "Synthetic test motor":
                raise ValueError(
                    "LAB-01 is already used by other equipment; choose another machine ID for that equipment before using the lab"
                )
        if not exists:
            self.store.register(machine, "Synthetic test motor")
        self.state = dict(
            status="RUNNING",
            scenario=scenario,
            machine=machine,
            sent=0,
            seconds=seconds,
            error=None,
            started_at=time.time(),
            ml_enabled=bool(model),
        )
        self.task = asyncio.create_task(self.run(scenario, seconds, machine, model))
        return dict(self.state)

    async def run(self, scenario, seconds, machine, model):
        from .synthetic import sequence

        rows = sequence(
            7777, scenario, length=seconds, onset=15, end=min(70, seconds - 35)
        )
        try:
            for row in rows:
                message = dict(
                    machine_id=machine,
                    message_id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    values=row["values"],
                    source="synthetic_lab",
                )
                await asyncio.to_thread(self.monitor.ingest, self.store, message, model)
                self.state["sent"] += 1
                await asyncio.sleep(1)
            self.state["status"] = "COMPLETED"
        except asyncio.CancelledError:
            self.state["status"] = "STOPPED"
            raise
        except Exception as exc:
            self.state.update(status="ERROR", error=str(exc)[:240])

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        return dict(self.state)
