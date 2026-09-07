"""Send Python to the running Blender MCP server and print what it printed.

    python tools/blender_exec.py script.py
    python tools/blender_exec.py -c "import bpy; print(bpy.app.version_string)"
    echo "print(1)" | python tools/blender_exec.py -

Uses the same command protocol as the MCP server, so it is a direct way to
drive or debug the Blender side without an MCP client in the loop.
"""

import argparse
import json
import os
import socket
import sys

HOST = os.environ.get("BLENDER_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLENDER_PORT", 9876))


def send(command_type, params=None, timeout=180.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((HOST, PORT))
    try:
        sock.sendall(json.dumps({"type": command_type, "params": params or {}}).encode("utf-8"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                raise RuntimeError("connection closed before a complete response")
            chunks.append(chunk)
            try:
                return json.loads(b"".join(chunks).decode("utf-8"))
            except json.JSONDecodeError:
                continue
    finally:
        sock.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", help="path to a .py file, or - for stdin")
    ap.add_argument("-c", "--code", help="inline code to run")
    ap.add_argument("--scene-info", action="store_true", help="print get_scene_info instead")
    ap.add_argument("--object", help="print get_object_info for this object name")
    ap.add_argument("--screenshot", help="render to this png path")
    ap.add_argument("--max-size", type=int, default=1000)
    args = ap.parse_args()

    if args.scene_info:
        response = send("get_scene_info")
    elif args.object:
        response = send("get_object_info", {"name": args.object})
    elif args.screenshot:
        response = send("get_viewport_screenshot", {
            "filepath": os.path.abspath(args.screenshot),
            "max_size": args.max_size, "format": "png",
        })
    else:
        if args.code is not None:
            code = args.code
        elif args.script == "-":
            code = sys.stdin.read()
        elif args.script:
            with open(args.script, "r", encoding="utf-8") as handle:
                code = handle.read()
            # execute_code has no notion of a file, so a script cannot find its
            # own directory and cannot import a sibling module. Supply both.
            script_path = os.path.abspath(args.script)
            code = (
                "import os, sys\n"
                f"__file__ = {script_path!r}\n"
                f"_d = os.path.dirname({script_path!r})\n"
                "if _d not in sys.path: sys.path.insert(0, _d)\n"
                "del _d\n"
            ) + code
        else:
            ap.error("give a script path, -c CODE, or one of --scene-info/--object/--screenshot")
        response = send("execute_code", {"code": code})

    if response.get("status") != "success":
        print(response.get("message", json.dumps(response)), file=sys.stderr)
        return 1

    result = response.get("result", {})
    if isinstance(result, dict) and "executed" in result:
        sys.stdout.write(result.get("result", ""))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
