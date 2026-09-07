"""Watch a running job to completion, then force the printer to cool fast.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE
    COOL_NOZZLE_C   stop once the nozzle is below this (default 40)
    COOL_BED_C      stop once the bed is below this (default 35)
    WATCH_MINUTES   give up waiting for the job after this (default 60)

The printer's own end gcode already zeroes both heaters, so the value added here
is running the part-cooling fan at full while they drop, and confirming the
targets really did reach zero rather than assuming it.
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
COOL_NOZZLE = float(os.environ.get("COOL_NOZZLE_C", 40))
COOL_BED = float(os.environ.get("COOL_BED_C", 35))
WATCH_MINUTES = float(os.environ.get("WATCH_MINUTES", 60))

REPORT = f"device/{SERIAL}/report"
REQUEST = f"device/{SERIAL}/request"

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
    if block.get("command") in ("gcode_line", "print_speed"):
        acks.append(block)
        print(f"  ACK {block.get('command')}: result={block.get('result')} "
              f"reason={block.get('reason')}", flush=True)


def p():
    return merged.get("print", {})


def send_gcode(client, lines, seq):
    client.publish(REQUEST, json.dumps({
        "print": {"sequence_id": str(seq), "command": "gcode_line",
                  "param": "\n".join(lines) + "\n"}
    }), qos=0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-watch")
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

print(f"watching {p().get('subtask_name')!r}  state={p().get('gcode_state')}", flush=True)

# Wait for the job. Only trust a terminal state after RUNNING/PREPARE has been
# seen: until the new job starts, the printer still reports the previous one's.
started = p().get("gcode_state") in ("RUNNING", "PREPARE")
deadline = time.time() + WATCH_MINUTES * 60
last = None
outcome = "timeout"

while time.time() < deadline:
    block = p()
    state = block.get("gcode_state")
    if state in ("RUNNING", "PREPARE"):
        started = True

    snapshot = (state, block.get("layer_num"), block.get("total_layer_num"),
                block.get("mc_percent"), block.get("mc_remaining_time"))
    if snapshot != last:
        print(f"  {state} layer={snapshot[1]}/{snapshot[2]} pct={snapshot[3]}% "
              f"remain={snapshot[4]}min "
              f"nozzle={block.get('nozzle_temper')} bed={block.get('bed_temper')}",
              flush=True)
        last = snapshot

    if block.get("print_error"):
        print(f"  !! print_error={block['print_error']}", flush=True)
    if block.get("hms"):
        print(f"  !! HMS {block['hms']}", flush=True)

    if started and state in ("FINISH", "FAILED"):
        outcome = state
        break
    time.sleep(5.0)

print(f"\njob outcome: {outcome}", flush=True)

# Cool down regardless of outcome -- a failed job leaves the heaters hot too.
print("forcing cooldown: heaters to 0, part fan to 100%", flush=True)
send_gcode(client, ["M104 S0", "M140 S0", "M106 S255"], 70)
time.sleep(3.0)
# Some firmware exposes the aux fan as P2; harmless if it is rejected.
send_gcode(client, ["M106 P2 S255"], 71)

cool_deadline = time.time() + 15 * 60
reported = None
while time.time() < cool_deadline:
    block = p()
    nozzle = block.get("nozzle_temper")
    bed = block.get("bed_temper")
    if nozzle is None or bed is None:
        time.sleep(5.0)
        continue
    tag = (round(nozzle / 5) * 5, round(bed / 5) * 5)
    if tag != reported:
        print(f"  cooling: nozzle={nozzle:.1f}C (target {block.get('nozzle_target_temper')}) "
              f"bed={bed:.1f}C (target {block.get('bed_target_temper')})", flush=True)
        reported = tag
    if nozzle <= COOL_NOZZLE and bed <= COOL_BED:
        break
    time.sleep(5.0)

block = p()
print("\nturning the fans off", flush=True)
send_gcode(client, ["M106 S0", "M106 P2 S0"], 72)
time.sleep(2.0)

print("\n=== FINAL ===", flush=True)
print(f"  outcome        : {outcome}")
print(f"  task           : {block.get('subtask_name')}")
print(f"  layers         : {block.get('layer_num')}/{block.get('total_layer_num')}")
print(f"  nozzle         : {block.get('nozzle_temper')}C  target {block.get('nozzle_target_temper')}")
print(f"  bed            : {block.get('bed_temper')}C  target {block.get('bed_target_temper')}")
print(f"  print_error    : {block.get('print_error')}")
print(f"  hms            : {block.get('hms')}")
print(f"  gcode_line ACKs: {[a.get('result') for a in acks if a.get('command') == 'gcode_line']}")

client.loop_stop()
client.disconnect()
sys.exit(0 if outcome == "FINISH" else 1)
