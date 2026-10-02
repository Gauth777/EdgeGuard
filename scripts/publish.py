"""Reproducible test publisher; every sample enters the real HTTP or MQTT interface."""

import argparse
import json
import os
import random
import time
import uuid
import httpx

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8000")
p.add_argument("--machine", default="M-01")
p.add_argument(
    "--scenario", choices=["normal", "incident", "missing", "noise"], default="normal"
)
p.add_argument("--seconds", type=int, default=90)
p.add_argument("--mqtt-host", default=None)
a = p.parse_args()
from edgeguard.config import load_env

load_env()
key = os.environ["EDGEGUARD_API_KEY"]
rng = random.Random(42)
mqtt = None
if a.mqtt_host:
    import paho.mqtt.client as mqtt_client

    mqtt = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2)
    mqtt.connect(a.mqtt_host, 1883)
    mqtt.loop_start()
with httpx.Client(headers={"X-API-Key": key}, timeout=10, trust_env=False) as client:
    response = client.post(
        a.url + "/api/machines", json={"id": a.machine, "label": "Motor " + a.machine}
    )
    if response.status_code not in (201, 409):
        response.raise_for_status()
    for tick in range(a.seconds):
        abnormal = a.scenario == "incident" and 15 <= tick < 55
        values = dict(
            temperature=round(rng.gauss(105 if abnormal else 60, 1), 2),
            vibration=round(rng.gauss(10 if abnormal else 2.4, 0.15), 2),
            pressure=round(rng.gauss(5, 0.1), 2),
            current=round(rng.gauss(12 if abnormal else 8, 0.2), 2),
            rpm=round(rng.gauss(1480, 5), 2),
        )
        if a.scenario == "missing":
            values["vibration"] = None
        if a.scenario == "noise" and tick % 9 == 0:
            values["vibration"] = -1  # invalid instrument reading, not machine fault
        message = dict(
            machine_id=a.machine,
            message_id=str(uuid.uuid4()),
            timestamp=time.time(),
            values=values,
        )
        if mqtt:
            mqtt.publish(
                "edgeguard/" + a.machine + "/telemetry", json.dumps(message), qos=1
            ).wait_for_publish()
        else:
            response = client.post(a.url + "/api/readings", json=message)
            response.raise_for_status()
        print(tick, values, flush=True)
        time.sleep(1)
if mqtt:
    mqtt.disconnect()
    mqtt.loop_stop()
