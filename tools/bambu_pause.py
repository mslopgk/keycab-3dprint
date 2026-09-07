"""Pause or resume a running job. Not bambu_stop.py -- this one is reversible.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE
    BAMBU_ACTION   "pause" (default) or "resume"

bambu_stop.py ends the job: the state goes to FAILED and the layer count is
gone for good. A pause holds position and temperature and picks up on the same
layer, which is what you want when you just need the printer to wait.
"""

import json
import os
import ssl
import time

import paho.mqtt.client as mqtt

HOST = os.environ["BAMBU_HOST"]
SERIAL = os.environ["BAMBU_SERIAL"]
CODE = os.environ["BAMBU_CODE"]
ACTION = os.environ.get("BAMBU_ACTION", "pause")
if ACTION not in ("pause", "resume"):
    raise SystemExit(f"BAMBU_ACTION must be pause or resume, got {ACTION!r}")

REQUEST = f"device/{SERIAL}/request"
REPORT = f"device/{SERIAL}/report"

merged = {}
acks = []


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
    if block.get("command") == ACTION:
        acks.append(f"{block.get('result')} / {block.get('reason')}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-pause")
client.username_pw_set("bblp", CODE)
context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
client.tls_set_context(context)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, 8883, keepalive=30)
client.loop_start()
time.sleep(2.0)

block = merged.get("print", {})
print(f"before: {block.get('gcode_state')}  layer {block.get('layer_num')}"
      f"/{block.get('total_layer_num')}  {block.get('mc_percent')}%  "
      f"task={block.get('subtask_name')!r}")

client.publish(REQUEST, json.dumps({
    "print": {"sequence_id": "20", "command": ACTION, "param": ""}
}), qos=0)
print(f"{ACTION} sent; waiting for the state to change ...")

want = "PAUSE" if ACTION == "pause" else "RUNNING"
deadline = time.time() + 40
while time.time() < deadline:
    if merged.get("print", {}).get("gcode_state") == want:
        break
    time.sleep(1.0)

block = merged.get("print", {})
print("\n=== final ===")
print(f"  gcode_state : {block.get('gcode_state')}")
print(f"  layer       : {block.get('layer_num')}/{block.get('total_layer_num')}"
      f"  ({block.get('mc_percent')}%)")
print(f"  nozzle      : {block.get('nozzle_temper')}C target {block.get('nozzle_target_temper')}")
print(f"  bed         : {block.get('bed_temper')}C target {block.get('bed_target_temper')}")
print(f"  ACKs        : {acks}")

client.loop_stop()
client.disconnect()

if block.get("gcode_state") != want:
    raise SystemExit(f"state is {block.get('gcode_state')}, expected {want}")
print(f"\n{want} confirmed. The job is intact -- resume with BAMBU_ACTION=resume.")
