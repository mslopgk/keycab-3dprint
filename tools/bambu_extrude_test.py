"""Heat the nozzle and push a measured length of filament, to see if it feeds.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE
    EXTRUDE_TEMP_C   nozzle temperature (default 220)
    EXTRUDE_MM       how much to push (default 50)
    EXTRUDE_RATE     mm/min (default 120, slow enough to watch)

After a clog or a ground filament, the question at every repair step is simply
"does material come out of the nozzle now". A 14-minute test cube answers that
expensively; this answers it in under a minute, and can be repeated after each
attempted fix. Watch the nozzle while it runs -- the printer cannot tell you
whether anything actually emerged.

Refuses to run unless the printer is idle.
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
TEMP = int(os.environ.get("EXTRUDE_TEMP_C", 220))
LENGTH = float(os.environ.get("EXTRUDE_MM", 50))
RATE = float(os.environ.get("EXTRUDE_RATE", 120))

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
        print(f"  ACK gcode_line: {block.get('result')} / {block.get('reason')}", flush=True)


def send(client, lines, seq):
    client.publish(REQUEST, json.dumps({
        "print": {"sequence_id": str(seq), "command": "gcode_line",
                  "param": "\n".join(lines) + "\n"}
    }), qos=0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-extrude")
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
state = block.get("gcode_state")
print(f"state: {state}   nozzle {block.get('nozzle_temper')}C")
if state not in ("IDLE", "FINISH", "FAILED", None):
    client.loop_stop()
    sys.exit(f"refusing to run while the printer is {state}")

print(f"\nheating to {TEMP}C ...")
send(client, [f"M104 S{TEMP}", f"M109 S{TEMP}"], 40)

deadline = time.time() + 300
while time.time() < deadline:
    now = merged.get("print", {}).get("nozzle_temper")
    if now is not None and now >= TEMP - 3:
        print(f"  reached {now:.1f}C")
        break
    time.sleep(3.0)
else:
    client.loop_stop()
    sys.exit("nozzle never reached temperature")

print(f"\nextruding {LENGTH}mm at {RATE}mm/min -- WATCH THE NOZZLE")
send(client, ["M83", f"G1 E{LENGTH} F{RATE}"], 41)

wait = LENGTH / RATE * 60.0 + 8.0
print(f"  (takes about {wait:.0f}s)")
time.sleep(wait)

print("\nturning the heater off")
send(client, ["M104 S0"], 42)
time.sleep(2.0)

block = merged.get("print", {})
print("\n=== after ===")
print(f"  nozzle       : {block.get('nozzle_temper')}C  target {block.get('nozzle_target_temper')}")
print(f"  hw_switch    : {block.get('hw_switch_state')}  (filament seen at the sensor)")
print(f"  print_error  : {block.get('print_error')}")
print(f"  hms          : {block.get('hms')}")
print(f"  gcode ACKs   : {acks}")
print()
print("  The printer cannot report whether filament actually emerged.")
print("  Material came out -> feeding works. Nothing came out -> still blocked.")

client.loop_stop()
client.disconnect()
