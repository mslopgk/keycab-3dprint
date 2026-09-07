"""Stop whatever the printer is currently doing.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE

Sends the MQTT stop command and waits for the reported state to leave
RUNNING/PREPARE, so the result is confirmed rather than assumed.
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
    print(f"mqtt connect: {reason_code}", flush=True)
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
    if block.get("command") == "stop":
        print(f"  ACK stop: result={block.get('result')} reason={block.get('reason')}",
              flush=True)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-stop")
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
task = merged.get("print", {}).get("subtask_name")
print(f"state before stop: {state}  task={task!r}")

if state in ("RUNNING", "PREPARE", "PAUSE", "SLICING"):
    client.publish(REQUEST, json.dumps({
        "print": {"sequence_id": "90", "command": "stop", "param": ""}
    }), qos=0)
    print("stop sent; waiting for the state to change ...")
    deadline = time.time() + 45
    while time.time() < deadline:
        now = merged.get("print", {}).get("gcode_state")
        if now not in ("RUNNING", "PREPARE", "PAUSE", "SLICING"):
            print(f"  state is now {now}")
            break
        time.sleep(1.0)
else:
    print("nothing to stop")

block = merged.get("print", {})
print("\n=== final ===")
for key in ("gcode_state", "subtask_name", "mc_percent", "layer_num",
            "nozzle_temper", "nozzle_target_temper", "bed_target_temper",
            "print_error", "hms"):
    if key in block:
        print(f"  {key}: {block[key]}")

client.loop_stop()
client.disconnect()
