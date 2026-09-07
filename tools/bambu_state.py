import json, os, ssl, sys, time
import paho.mqtt.client as mqtt
HOST=os.environ["BAMBU_HOST"]; SERIAL=os.environ["BAMBU_SERIAL"]; CODE=os.environ["BAMBU_CODE"]
state={}
# "RUNNING" alone cannot tell you WHICH job is running, which matters whenever
# two printers are in play or a job was started by hand. -v prints the file name
# and progress so the answer is not a guess.
VERBOSE = "-v" in sys.argv
def on_connect(c,u,f,rc,p=None):
    c.subscribe(f"device/{SERIAL}/report")
    c.publish(f"device/{SERIAL}/request", json.dumps({"pushing":{"sequence_id":"1","command":"pushall","version":1,"push_target":1}}))
def on_message(c,u,m):
    try: d=json.loads(m.payload.decode("utf-8","replace"))
    except Exception: return
    if "print" in d and "gcode_state" in d["print"]:
        state["s"]=d["print"]["gcode_state"]
        state["p"]=d["print"]
cl=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-state")
cl.username_pw_set("bblp", CODE)
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
cl.tls_set_context(ctx); cl.on_connect=on_connect; cl.on_message=on_message
cl.connect(HOST,8883,keepalive=30); cl.loop_start()
for _ in range(20):
    if "s" in state: break
    time.sleep(0.5)
cl.loop_stop(); cl.disconnect()
print(state.get("s","UNKNOWN"))
if VERBOSE:
    b = state.get("p", {})
    for key in ("subtask_name","gcode_file","mc_percent","mc_remaining_time",
                "layer_num","total_layer_num","nozzle_temper","nozzle_target_temper",
                "bed_temper","bed_target_temper","spd_lvl","print_error"):
        print(f"  {key:22s}: {b.get(key)}")
