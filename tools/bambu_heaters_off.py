"""Zero both heater targets now and confirm they really went to zero.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE
    FAN_OFF=1   also stop the part-cooling fan once cool

Stopping a job does not necessarily zero the heaters: after a self-pause the A1
holds the bed at its printing temperature and parks the nozzle at a standby
value, and it will sit there indefinitely. That is fine while someone is in the
room and not fine overnight, so this is separate from bambu_stop.py -- it reads
the targets back rather than trusting that the stop was enough.
"""

import json
import os
import ssl
import time

import paho.mqtt.client as mqtt

HOST = os.environ["BAMBU_HOST"]
SERIAL = os.environ["BAMBU_SERIAL"]
CODE = os.environ["BAMBU_CODE"]
FAN_OFF = os.environ.get("FAN_OFF", "1") == "1"

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
    if block.get("command") == "gcode_line":
        acks.append(block.get("result"))


def send(client, lines, seq):
    client.publish(REQUEST, json.dumps({
        "print": {"sequence_id": str(seq), "command": "gcode_line",
                  "param": "\n".join(lines) + "\n"}
    }), qos=0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-heatoff")
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

block = merged.get("print", {})
print(f"before: state={block.get('gcode_state')} "
      f"nozzle {block.get('nozzle_temper')}C -> target {block.get('nozzle_target_temper')}  "
      f"bed {block.get('bed_temper')}C -> target {block.get('bed_target_temper')}")

lines = ["M104 S0", "M140 S0"]
if FAN_OFF:
    lines.append("M106 P1 S255")     # part fan full while it drops
send(client, lines, 60)
time.sleep(4.0)
send(client, ["M104 S0", "M140 S0"], 61)   # once more; the first can land mid-stop

deadline = time.time() + 60
while time.time() < deadline:
    block = merged.get("print", {})
    if block.get("nozzle_target_temper") == 0 and block.get("bed_target_temper") == 0:
        break
    time.sleep(2.0)

block = merged.get("print", {})
nozzle_target = block.get("nozzle_target_temper")
bed_target = block.get("bed_target_temper")
print(f"after : state={block.get('gcode_state')} "
      f"nozzle {block.get('nozzle_temper')}C -> target {nozzle_target}  "
      f"bed {block.get('bed_temper')}C -> target {bed_target}")
print(f"gcode ACKs: {acks}")

if nozzle_target == 0 and bed_target == 0:
    print("HEATERS OFF -- both targets confirmed at zero")
else:
    raise SystemExit(
        f"targets did NOT reach zero (nozzle={nozzle_target}, bed={bed_target}); "
        "do not leave the printer unattended"
    )
