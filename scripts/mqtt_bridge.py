"""MQTT QoS1 adapter: acknowledge broker delivery only after edge HTTP acceptance.
A failed message forces reconnect so the persistent broker session can redeliver.
"""

import logging
import os
import time
import httpx
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO)
client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="edgeguard-ingestion",
    clean_session=False,
    manual_ack=True,
)
http = httpx.Client(
    headers={"X-API-Key": os.environ["EDGEGUARD_API_KEY"]}, timeout=5, trust_env=False
)
url = os.getenv("EDGEGUARD_EDGE_URL", "http://127.0.0.1:8000")


def connected(c, u, f, rc, properties):
    if rc == 0:
        c.subscribe("edgeguard/+/telemetry", qos=1)


def message(c, u, msg):
    if len(msg.payload) > 16384:
        logging.error("Rejected oversize MQTT payload")
        c.ack(msg.mid, msg.qos)
        return
    try:
        r = http.post(
            url + "/api/readings",
            content=msg.payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code in (409, 422, 413):
            logging.error("Rejected invalid telemetry: %s", r.status_code)
            c.ack(msg.mid, msg.qos)
        else:
            r.raise_for_status()
            c.ack(msg.mid, msg.qos)
    except httpx.HTTPError:
        logging.exception("Edge unavailable; keeping broker message unacknowledged")
        c.disconnect()


client.on_connect = connected
client.on_message = message
while True:
    try:
        client.connect(os.getenv("MQTT_HOST", "127.0.0.1"), 1883)
        client.loop_forever()
    except OSError:
        logging.exception("MQTT reconnect required")
    time.sleep(3)
