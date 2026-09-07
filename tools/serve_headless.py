"""Run the Blender MCP command server inside a headless Blender.

    blender --background [file.blend] --python tools/serve_headless.py

Why this exists: `bpy.app.timers` never fire in --background mode, so the
extension's normal GUI timer would leave every queued command unexecuted (this
is exactly the "commands never execute, run Blender with a GUI" failure the
upstream MCP server warns about). Here the main thread owns the pump loop
instead, so no GUI and no manual "Connect" click is needed.

Environment:
    BLENDER_HOST  bind address (default 127.0.0.1)
    BLENDER_PORT  bind port    (default 9876) -- must match the MCP server
"""

import importlib.util
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "blender_mcp_ext", "__init__.py")

# Load the extension source directly rather than through `bl_ext.*` so the
# headless server works whether or not the extension is enabled in preferences.
spec = importlib.util.spec_from_file_location("blender_mcp_headless", MODULE_PATH)
mcp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mcp
spec.loader.exec_module(mcp)

host = os.environ.get("BLENDER_HOST", mcp.DEFAULT_HOST)
port = int(os.environ.get("BLENDER_PORT", mcp.DEFAULT_PORT))

server = mcp.BlenderMCPServer(host, port)
server.start()
print(f"BLENDER_MCP_READY {host}:{port}", flush=True)

try:
    while True:
        server.pump()
        time.sleep(0.02)
except KeyboardInterrupt:
    pass
finally:
    server.stop()
