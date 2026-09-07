"""Set the print speed level on a running job.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE, BAMBU_SPEED

spd_lvl: 1 silent, 2 standard, 3 sport, 4 ludicrous. The printer only accepts
this while a job is actually running, and resets it to 2 when the job ends.
"""

import json
import os
import ssl
import sys
import time

import paho.mqtt.client as mqtt

HOST = os.environ["BAMBU_HOST"]
SERIAL = os.environ["BAMBU_SERIAL"]
CODE = os.environ["BAMBU_CODE"]
SPEED = os.environ.get("BAMBU_SPEED", "4")

REPORT = f"device/{SERIAL}/report"
REQUEST = f"device/{SERIAL}/request"

merged = {}


def deep_merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            deep_merge(dst[key], value)
        else:
            dst[key] = value


def on_connect(client, userdata, flags, reason_code, properties=None):
    client.subscribe(REPORT, qos=0)
    client.publish(REQUEST, json.dumps({
        "pushing": {"sequence_id": "1", "command": "pushall", "version": 1,
                    "push_target": 1}
    }), qos=0)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
    except Exception:
        return
    deep_merge(merged, payload)
    block = payload.get("print", {})
    if block.get("command") == "print_speed":
        print(f"  ACK print_speed: result={block.get('result')} "
              f"reason={block.get('reason')}", flush=True)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-speed")
client.username_pw_set("bblp", CODE)
context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
client.tls_set_context(context)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, 8883, keepalive=30)
client.loop_start()

time.sleep(2.5)
state = merged.get("print", {}).get("gcode_state")
print(f"state: {state}  current spd_lvl: {merged.get('print', {}).get('spd_lvl')}")
if state != "RUNNING":
    client.loop_stop()
    sys.exit(f"not running ({state}); the printer only accepts print_speed while running")

client.publish(REQUEST, json.dumps({
    "print": {"sequence_id": "80", "command": "print_speed", "param": SPEED}
}), qos=0)

deadline = time.time() + 20
while time.time() < deadline:
    if str(merged.get("print", {}).get("spd_lvl")) == str(SPEED):
        break
    time.sleep(0.5)

print(f"spd_lvl is now {merged.get('print', {}).get('spd_lvl')}")
client.loop_stop()
client.disconnect()
