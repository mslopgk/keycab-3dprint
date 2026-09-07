"""Watch a job to completion, then hold the printer preheated for the next one.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE
    HOLD_BED_C      bed temperature to hold  (default 65)
    HOLD_NOZZLE_C   nozzle standby           (default 150)
    HOLD_MINUTES    how long to keep holding (default 90)
    WAIT_MINUTES    give up waiting for the job (default 90)
    CYCLES          how many print-then-hold rounds to sit through (default 1)

The opposite of bambu_watch_cooldown.py, and for the opposite situation: when
the same small part is printed over and over, the printer's end gcode zeroes
both heaters and the next job then spends its whole ~6 minute overhead heating
them again. Re-asserting the targets the moment the job ends keeps that.

The nozzle standby is well under printing temperature on purpose. Parking it at
205C for an hour cooks the filament sitting in the melt zone, which oozes and
eventually clogs; 150C is cool enough to be inert and hot enough that the ramp
to 205C takes seconds.

Targets are re-sent on a timer, not once: the firmware zeroes them again at
various points, and one M140 at the wrong moment is silently lost.

CYCLES > 1 makes it sit through several rounds. Holding stops the moment the
next job starts -- that job sets its own temperatures -- and then it goes back
to watching, so one invocation covers a whole run of repeats instead of needing
to be relaunched after each one.
"""

import json
import os
import ssl
import time

import paho.mqtt.client as mqtt

HOST = os.environ["BAMBU_HOST"]
SERIAL = os.environ["BAMBU_SERIAL"]
CODE = os.environ["BAMBU_CODE"]
BED = int(os.environ.get("HOLD_BED_C", 65))
NOZZLE = int(os.environ.get("HOLD_NOZZLE_C", 150))
HOLD_MINUTES = float(os.environ.get("HOLD_MINUTES", 90))
WAIT_MINUTES = float(os.environ.get("WAIT_MINUTES", 90))
CYCLES = int(os.environ.get("CYCLES", 1))

REQUEST = f"device/{SERIAL}/request"
REPORT = f"device/{SERIAL}/report"

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


def block():
    return merged.get("print", {})


def send(client, lines, seq):
    client.publish(REQUEST, json.dumps({
        "print": {"sequence_id": str(seq), "command": "gcode_line",
                  "param": "\n".join(lines) + "\n"}
    }), qos=0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-holdwarm")
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

seq = 70
paused = False

for cycle in range(1, CYCLES + 1):
    start_state = block().get("gcode_state")
    task = block().get("subtask_name")
    print(f"\n--- cycle {cycle}/{CYCLES} --- watching {task!r}, state {start_state}")

    # Wait for the job to leave RUNNING. A job that self-pauses (runout, tangle)
    # is reported instead -- preheating a paused printer is not the ask.
    deadline = time.time() + WAIT_MINUTES * 60.0
    outcome = start_state
    seen_running = start_state in ("RUNNING", "PREPARE")
    while time.time() < deadline:
        state = block().get("gcode_state")
        if state in ("RUNNING", "PREPARE"):
            seen_running = True
        elif seen_running and state in ("FINISH", "FAILED", "IDLE"):
            outcome = state
            break
        elif state == "PAUSE":
            outcome = "PAUSE"
            break
        print(f"  {state}  layer {block().get('layer_num')}"
              f"/{block().get('total_layer_num')}  {block().get('mc_percent')}%",
              flush=True)
        time.sleep(20.0)
    else:
        outcome = block().get("gcode_state")
        print("  gave up waiting")

    print(f"  job ended: {outcome}")
    if outcome == "PAUSE":
        print("  PAUSED, not finished -- not preheating. Deal with the pause first:")
        print(f"    print_error {block().get('print_error')}  "
              f"hw_switch {block().get('hw_switch_state')}")
        paused = True
        break

    print(f"  holding bed {BED}C / nozzle {NOZZLE}C, up to {HOLD_MINUTES:.0f} min")
    hold_until = time.time() + HOLD_MINUTES * 60.0
    handed_over = False
    while time.time() < hold_until:
        state = block().get("gcode_state")
        if state in ("RUNNING", "PREPARE"):
            print("  next job started -- handing its heaters back")
            handed_over = True
            break
        send(client, [f"M140 S{BED}", f"M104 S{NOZZLE}"], seq)
        seq += 1
        time.sleep(25.0)
        b = block()
        print(f"  holding: bed {b.get('bed_temper')}C/{b.get('bed_target_temper')} "
              f"nozzle {b.get('nozzle_temper')}C/{b.get('nozzle_target_temper')}",
              flush=True)

    if not handed_over:
        print("  hold window elapsed with no new job -- stopping")
        break

b = block()
print("\n=== final ===")
print(f"  state   : {b.get('gcode_state')}")
print(f"  layers  : {b.get('layer_num')}/{b.get('total_layer_num')}")
print(f"  bed     : {b.get('bed_temper')}C target {b.get('bed_target_temper')}")
print(f"  nozzle  : {b.get('nozzle_temper')}C target {b.get('nozzle_target_temper')}")
print(f"  error   : {b.get('print_error')}")

client.loop_stop()
client.disconnect()
if paused:
    raise SystemExit(2)
