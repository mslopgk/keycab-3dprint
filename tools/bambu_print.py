"""Upload a sliced .gcode.3mf to a Bambu printer over LAN and start the print.

    BAMBU_HOST, BAMBU_SERIAL, BAMBU_CODE   printer + LAN access code
    BAMBU_FILE                             local .gcode.3mf to send
    BAMBU_REMOTE                           name to store it as (default: basename)
    BAMBU_SPEED                            1 silent, 2 standard, 3 sport, 4 ludicrous
    BAMBU_BED                              bed_type, default textured_plate

The printer takes jobs in two steps: FTPS the 3mf onto its storage, then send an
MQTT `project_file` command naming the gcode inside that archive. Speed level is
applied only once the job is actually running -- the command is rejected while
the printer is still heating or calibrating.
"""

import ftplib
import hashlib
import json
import os
import ssl
import sys
import time

import paho.mqtt.client as mqtt

HOST = os.environ["BAMBU_HOST"]
SERIAL = os.environ["BAMBU_SERIAL"]
CODE = os.environ["BAMBU_CODE"]
LOCAL = os.environ["BAMBU_FILE"]
REMOTE = os.environ.get("BAMBU_REMOTE") or os.path.basename(LOCAL)
SPEED = os.environ.get("BAMBU_SPEED", "2")
BED = os.environ.get("BAMBU_BED", "textured_plate")

REPORT = f"device/{SERIAL}/report"
REQUEST = f"device/{SERIAL}/request"


class ImplicitFTPTLS(ftplib.FTP_TLS):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=None)
        self._sock = value


def upload():
    size = os.path.getsize(LOCAL)
    with open(LOCAL, "rb") as handle:
        digest = hashlib.md5(handle.read()).hexdigest()
    print(f"local: {LOCAL}  {size} bytes  md5={digest}")

    skip = os.environ.get("BAMBU_SKIP_UPLOAD", "").lower() in ("1", "true", "yes")

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        context.set_ciphers("DEFAULT@SECLEVEL=0")
    except ssl.SSLError:
        pass

    def connect():
        ftp = ImplicitFTPTLS(context=context)
        ftp.encoding = "utf-8"
        ftp.connect(host=HOST, port=990, timeout=30)
        ftp.login("bblp", CODE)
        ftp.prot_p()
        ftp.set_pasv(True)
        return ftp

    if skip:
        # Staged earlier. Still verify the remote size below -- "I uploaded it
        # once" is not evidence the bytes are still intact on the card.
        print("BAMBU_SKIP_UPLOAD set: reusing the file already on the printer")
        check = connect()
        try:
            remote_size = check.size(f"/{REMOTE}")
        finally:
            try:
                check.close()
            except Exception:
                pass
        print(f"remote /{REMOTE}: {remote_size} bytes")
        if remote_size != size:
            sys.exit(f"SIZE MISMATCH: local {size} vs remote {remote_size} -- not starting")
        return digest

    ftp = connect()
    try:
        with open(LOCAL, "rb") as handle:
            ftp.storbinary(f"STOR /{REMOTE}", handle, blocksize=32768)
        print("STOR completed cleanly")
    except (TimeoutError, ssl.SSLError, OSError) as exc:
        # The printer's FTP server does not close the data connection's TLS
        # session properly, so ftplib hangs in conn.unwrap() after the bytes are
        # already across. Treat it as unproven rather than failed, and verify.
        print(f"STOR raised {type(exc).__name__}: {exc}")
        print("(known Bambu FTPS quirk -- verifying with a fresh connection)")
    finally:
        try:
            ftp.close()
        except Exception:
            pass

    check = connect()
    try:
        remote_size = check.size(f"/{REMOTE}")
    finally:
        try:
            check.close()
        except Exception:
            pass

    print(f"uploaded -> /{REMOTE}  remote size={remote_size}")
    if remote_size != size:
        sys.exit(f"SIZE MISMATCH: local {size} vs remote {remote_size} -- not starting")
    return digest


def deep_merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            deep_merge(dst[key], value)
        else:
            dst[key] = value


def main():
    digest = upload()

    merged = {}
    acks = []

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"mqtt connect: {reason_code}", flush=True)
        client.subscribe(REPORT, qos=0)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return
        deep_merge(merged, payload)
        block = payload.get("print", {})
        if block.get("command") in ("project_file", "print_speed"):
            acks.append(block)
            print(f"  ACK {block.get('command')}: result={block.get('result')} "
                  f"reason={block.get('reason')} seq={block.get('sequence_id')}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-print")
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
    pre = merged.get("print", {}).get("gcode_state")
    print(f"state before start: {pre}")
    if pre not in (None, "IDLE", "FINISH", "FAILED"):
        client.loop_stop()
        sys.exit(f"REFUSING TO START: printer is {pre}, not idle")

    command = {
        "print": {
            "sequence_id": "10",
            "command": "project_file",
            "param": "Metadata/plate_1.gcode",
            "url": f"ftp:///{REMOTE}",
            "subtask_name": os.path.splitext(os.path.basename(REMOTE))[0],
            "md5": digest,
            "project_id": "0",
            "profile_id": "0",
            "task_id": "0",
            "subtask_id": "0",
            "timelapse": False,
            "bed_type": BED,
            "bed_leveling": True,
            "flow_cali": False,
            "vibration_cali": False,
            "layer_inspect": False,
            "use_ams": False,
            "ams_mapping": [],
        }
    }
    print(f"\nsending project_file (bed_type={BED}) ...")
    client.publish(REQUEST, json.dumps(command), qos=0)

    speed_sent = False
    started = False
    deadline = time.time() + 150
    last = None
    while time.time() < deadline:
        block = merged.get("print", {})
        snapshot = (block.get("gcode_state"), block.get("mc_print_stage"),
                    block.get("layer_num"), block.get("mc_percent"),
                    block.get("print_error"), block.get("spd_lvl"))
        if snapshot != last:
            print(f"  state={snapshot[0]} stage={snapshot[1]} layer={snapshot[2]} "
                  f"pct={snapshot[3]} err={snapshot[4]} spd_lvl={snapshot[5]}", flush=True)
            last = snapshot
        hms = block.get("hms")
        if hms:
            print(f"  !! HMS alerts: {hms}", flush=True)
        if block.get("print_error"):
            print(f"  !! print_error={block['print_error']}", flush=True)

        if not speed_sent and block.get("gcode_state") == "RUNNING" and SPEED != "2":
            client.publish(REQUEST, json.dumps({
                "print": {"sequence_id": "11", "command": "print_speed", "param": SPEED}
            }), qos=0)
            print(f"  -> print_speed {SPEED} sent", flush=True)
            speed_sent = True

        # Only believe FAILED once the job has actually begun. The printer keeps
        # reporting the *previous* job's terminal state until the new one starts,
        # so checking it immediately aborts the watch on the first iteration and
        # the speed command never gets sent.
        if started and block.get("gcode_state") == "FAILED":
            print("  !! job reports FAILED", flush=True)
            break
        if block.get("gcode_state") in ("PREPARE", "RUNNING"):
            started = True
        if speed_sent and (block.get("layer_num") or 0) >= 1:
            break
        time.sleep(1.0)

    block = merged.get("print", {})
    print("\n=== final ===")
    for key in ("gcode_state", "subtask_name", "gcode_file", "mc_percent",
                "mc_remaining_time", "layer_num", "total_layer_num", "spd_lvl",
                "nozzle_temper", "nozzle_target_temper", "bed_temper",
                "bed_target_temper", "print_error", "hms"):
        if key in block:
            print(f"  {key}: {block[key]}")

    client.loop_stop()
    client.disconnect()


main()
