"""Exercise the Blender MCP socket protocol without going through an MCP client.

    python tools/mcp_client_test.py

Mirrors blender_mcp/server.py's framing exactly: send one JSON command on a
persistent socket, then read until the accumulated bytes parse as JSON.
"""

import json
import os
import socket
import sys
import tempfile

HOST = os.environ.get("BLENDER_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLENDER_PORT", 9876))


def send(sock, command_type, params=None):
    sock.sendall(json.dumps({"type": command_type, "params": params or {}}).encode("utf-8"))
    chunks = []
    while True:
        chunk = sock.recv(8192)
        if not chunk:
            raise RuntimeError("connection closed before a complete response")
        chunks.append(chunk)
        data = b"".join(chunks)
        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            continue


def main():
    failures = []

    def check(label, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(180.0)
    sock.connect((HOST, PORT))
    print(f"connected to {HOST}:{PORT}\n")

    r = send(sock, "get_scene_info")
    check("get_scene_info status", r.get("status") == "success", json.dumps(r)[:200])
    scene = r.get("result", {})
    check("get_scene_info has unit_settings", "unit_settings" in scene)
    print(f"      scene={scene.get('name')} objects={scene.get('object_count')} "
          f"blender={scene.get('blender_version')}")

    # Two commands on the same socket: proves the stream stays in sync.
    r = send(sock, "execute_code", {"code": "print('hello', 6 * 7)"})
    check("execute_code status", r.get("status") == "success", json.dumps(r)[:300])
    check("execute_code captures stdout",
          "hello 42" in r.get("result", {}).get("result", ""),
          repr(r.get("result", {}).get("result")))

    r = send(sock, "execute_code", {"code": (
        "import bpy\n"
        "bpy.ops.object.select_all(action='SELECT')\n"
        "bpy.ops.object.delete()\n"
        "bpy.ops.mesh.primitive_cube_add(size=0.018, location=(0,0,0.009))\n"
        "bpy.context.active_object.name = 'ProtocolProbe'\n"
        "print('created', bpy.context.active_object.name)\n"
    )})
    check("execute_code creates geometry", r.get("status") == "success", json.dumps(r)[:400])

    r = send(sock, "get_object_info", {"name": "ProtocolProbe"})
    check("get_object_info status", r.get("status") == "success", json.dumps(r)[:200])
    obj = r.get("result", {})
    check("get_object_info reports mesh stats", obj.get("mesh", {}).get("vertices") == 8,
          str(obj.get("mesh")))
    check("get_object_info reports manifold mesh",
          obj.get("mesh", {}).get("non_manifold_edges") == 0, str(obj.get("mesh")))
    print(f"      dimensions={obj.get('dimensions')} bbox={obj.get('world_bounding_box')}")

    r = send(sock, "get_object_info", {"name": "NoSuchObject"})
    check("missing object returns error", r.get("status") == "error", json.dumps(r)[:200])

    r = send(sock, "bogus_command_name")
    check("unknown command returns error", r.get("status") == "error", json.dumps(r)[:200])

    r = send(sock, "execute_code", {"code": "raise ValueError('intentional')"})
    check("failing code returns error", r.get("status") == "error"
          and "intentional" in r.get("message", ""), json.dumps(r)[:200])

    r = send(sock, "get_polyhaven_status")
    check("polyhaven status reports disabled",
          r.get("status") == "success" and r["result"].get("enabled") is False,
          json.dumps(r)[:200])

    shot = os.path.join(tempfile.gettempdir(), "blender_mcp_protocol_test.png")
    r = send(sock, "get_viewport_screenshot",
             {"max_size": 400, "filepath": shot, "format": "png"})
    if r.get("status") == "success":
        res = r["result"]
        check("screenshot file created", os.path.exists(shot), str(res))
        check("screenshot respects max_size", max(res.get("width", 0), res.get("height", 0)) <= 400,
              f"{res.get('width')}x{res.get('height')} via {res.get('source')}")
        print(f"      source={res.get('source')} path={shot}")

        # A file existing proves nothing: near-plane clipping produces a
        # perfectly valid PNG of pure background. Measure actual pixel spread.
        r2 = send(sock, "execute_code", {"code": (
            "import bpy\n"
            f"img = bpy.data.images.load(r'{shot}', check_existing=False)\n"
            "px = list(img.pixels)\n"
            "rgb = [px[i] for i in range(len(px)) if i % 4 != 3]\n"
            "print('spread', round(max(rgb) - min(rgb), 5))\n"
            "bpy.data.images.remove(img)\n"
        )})
        spread = None
        if r2.get("status") == "success":
            out = r2["result"].get("result", "")
            if out.startswith("spread "):
                spread = float(out.split()[1])
        check("screenshot is not a blank frame", spread is not None and spread > 0.02,
              f"pixel spread={spread} (0 means the subject was clipped or absent)")
    else:
        check("screenshot", False, json.dumps(r)[:400])

    sock.close()

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
