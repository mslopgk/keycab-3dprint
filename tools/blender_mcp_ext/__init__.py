"""Blender-side server for the `blender-mcp` MCP server (PyPI blender-mcp 1.8.0).

Speaks the same loopback JSON-over-TCP protocol as the upstream addon.py:

    request   {"type": "<command>", "params": {...}}
    success   {"status": "success", "result": {...}}
    failure   {"status": "error", "message": "..."}

Written from scratch against blender_mcp/server.py rather than vendored, because
Blender 5.x no longer scans the legacy user `scripts/addons` directory, so the
upstream single-file addon cannot be loaded here at all. This ships as an
extension (blender_manifest.toml) instead.

bpy is not thread-safe, so socket threads never touch it: they push jobs onto a
queue and block on an Event. The main thread drains that queue -- via
bpy.app.timers in the GUI, or via the explicit pump loop in serve_headless.py
when Blender runs with --background (where timers never fire).
"""

import contextlib
import io
import json
import math
import os
import queue
import socket
import sys
import threading
import traceback

import bpy
import mathutils

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876

# Client-side timeout in blender_mcp/server.py is 180s; expire jobs just under
# that so a stuck command reports a real error instead of desyncing the stream.
JOB_TIMEOUT = 175.0

_server = None


def log(msg):
    print(f"[blender-mcp] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #

def _vec(v):
    return [round(float(c), 6) for c in v]


def cmd_get_scene_info(params):
    scene = bpy.context.scene
    unit = scene.unit_settings
    objects = []
    for obj in scene.objects:
        objects.append({
            "name": obj.name,
            "type": obj.type,
            "location": _vec(obj.location),
            "dimensions": _vec(obj.dimensions),
            "visible": obj.visible_get() if obj.name in bpy.context.view_layer.objects else None,
        })
    return {
        "name": scene.name,
        "blender_version": bpy.app.version_string,
        "object_count": len(objects),
        "objects": objects,
        "materials_count": len(bpy.data.materials),
        "collections": [c.name for c in bpy.data.collections],
        "frame_current": scene.frame_current,
        # Unit setup decides whether "1.0" means a metre or a millimetre, which
        # is the single most common source of mis-scaled 3D prints.
        "unit_settings": {
            "system": unit.system,
            "scale_length": unit.scale_length,
            "length_unit": unit.length_unit,
        },
        "selected_objects": [o.name for o in bpy.context.selected_objects],
        "active_object": bpy.context.view_layer.objects.active.name
        if bpy.context.view_layer.objects.active else None,
    }


def cmd_get_object_info(params):
    name = params.get("name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name!r}")

    info = {
        "name": obj.name,
        "type": obj.type,
        "location": _vec(obj.location),
        "rotation_euler": _vec(obj.rotation_euler),
        "scale": _vec(obj.scale),
        "dimensions": _vec(obj.dimensions),
        "parent": obj.parent.name if obj.parent else None,
        "materials": [m.name for m in obj.data.materials] if getattr(obj.data, "materials", None) else [],
        "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
    }

    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    if corners:
        info["world_bounding_box"] = {
            "min": _vec([min(c[i] for c in corners) for i in range(3)]),
            "max": _vec([max(c[i] for c in corners) for i in range(3)]),
        }

    if obj.type == "MESH":
        mesh = obj.data
        info["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "triangles": len(mesh.loop_triangles) or None,
        }
        # Non-manifold geometry is what makes a slicer reject a model, so report
        # the cheap proxy for it: edges not shared by exactly two faces.
        edge_face_count = {}
        for poly in mesh.polygons:
            for key in poly.edge_keys:
                edge_face_count[key] = edge_face_count.get(key, 0) + 1
        info["mesh"]["non_manifold_edges"] = sum(
            1 for n in edge_face_count.values() if n != 2
        )

    return info


def cmd_execute_code(params):
    code = params.get("code")
    if not code:
        raise ValueError("No code provided")

    namespace = {
        "__name__": "__blender_mcp__",
        "bpy": bpy,
        "mathutils": mathutils,
        "math": math,
        "os": os,
    }
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            exec(code, namespace)
    except Exception:
        # Hand back the captured output too -- prints before the exception are
        # usually what identify which step failed.
        raise RuntimeError(
            f"{traceback.format_exc()}\n--- stdout before error ---\n{stdout.getvalue()}"
        )
    return {"executed": True, "result": stdout.getvalue()}


def _pick_render_engine():
    prop = bpy.types.RenderSettings.bl_rna.properties["engine"]
    available = {item.identifier for item in prop.enum_items}
    # Workbench first: fast, and needs no lights in the scene to show a shape.
    for candidate in ("BLENDER_WORKBENCH", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        if candidate in available:
            yield candidate


def _ensure_camera(scene):
    """Return (camera, created) with the camera framing all visible geometry."""
    if scene.camera is not None:
        return scene.camera, False

    targets = [o for o in scene.objects if o.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}]
    corners = []
    for obj in targets:
        corners.extend(obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box)

    if corners:
        lo = mathutils.Vector([min(c[i] for c in corners) for i in range(3)])
        hi = mathutils.Vector([max(c[i] for c in corners) for i in range(3)])
        center = (lo + hi) / 2.0
        radius = max((hi - lo).length / 2.0, 1e-4)
    else:
        center = mathutils.Vector((0.0, 0.0, 0.0))
        radius = 1.0

    cam_data = bpy.data.cameras.new("MCP_TempCamera")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("MCP_TempCamera", cam_data)
    scene.collection.objects.link(cam)

    direction = mathutils.Vector((1.0, -1.2, 0.8)).normalized()
    distance = radius * 3.2
    cam.location = center + direction * distance
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

    # Scale the clipping range to the subject. The 0.1m default clip_start sits
    # *behind* a millimetre-scale part -- an 18mm keycap framed at ~50mm lands
    # entirely inside the near plane and renders as an empty background.
    cam_data.clip_start = max(radius * 0.01, 1e-6)
    cam_data.clip_end = distance + radius * 20.0

    scene.camera = cam
    return cam, True


def _ensure_preview_lighting(scene):
    """Light an unlit scene for the duration of a render; returns a restore fn.

    This build exposes only BLENDER_EEVEE (no Workbench, no Cycles), so there is
    no engine that ignores lighting. Without this, a scene whose lights were
    never set up renders as a near-black silhouette that says nothing about the
    surface shape -- useless for judging a model.
    """
    if any(obj.type == "LIGHT" for obj in scene.objects):
        return lambda: None

    previous_world = scene.world
    world = bpy.data.worlds.new("MCP_PreviewWorld")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.30, 0.31, 0.34, 1.0)
        background.inputs[1].default_value = 1.0
    scene.world = world

    sun_data = bpy.data.lights.new("MCP_PreviewSun", type="SUN")
    sun_data.energy = 4.0
    sun = bpy.data.objects.new("MCP_PreviewSun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = mathutils.Euler((math.radians(55.0), 0.0, math.radians(35.0)), "XYZ")

    def restore():
        scene.world = previous_world
        bpy.data.objects.remove(sun, do_unlink=True)
        bpy.data.lights.remove(sun_data)
        bpy.data.worlds.remove(world)

    return restore


def _nearest_geometry_distance(scene, cam):
    """Distance from cam to the closest renderable bound-box corner, or None."""
    origin = cam.matrix_world.translation
    best = None
    for obj in scene.objects:
        if obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            continue
        for corner in obj.bound_box:
            d = ((obj.matrix_world @ mathutils.Vector(corner)) - origin).length
            if best is None or d < best:
                best = d
    return best


def _downscale(filepath, max_size):
    """Shrink an on-disk PNG in place so the largest side is <= max_size."""
    img = bpy.data.images.load(filepath, check_existing=False)
    try:
        w, h = img.size
        if max(w, h) > max_size and max(w, h) > 0:
            factor = max_size / float(max(w, h))
            img.scale(max(1, int(w * factor)), max(1, int(h * factor)))
            img.filepath_raw = filepath
            img.file_format = "PNG"
            img.save()
            w, h = img.size
        return w, h
    finally:
        bpy.data.images.remove(img)


def _screenshot_from_viewport(filepath):
    """GUI path: grab the actual 3D viewport pixels. False if unavailable."""
    if bpy.app.background:
        return False
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=filepath)
                if os.path.exists(filepath):
                    return True
            except Exception as exc:
                log(f"viewport screenshot failed, falling back to render: {exc}")
    return False


def _screenshot_from_render(filepath, max_size):
    """Headless path: render the scene instead of grabbing a viewport."""
    scene = bpy.context.scene
    render = scene.render
    saved = (
        render.engine, render.filepath, render.resolution_x, render.resolution_y,
        render.resolution_percentage, render.image_settings.file_format, render.film_transparent,
    )
    cam, created_cam = _ensure_camera(scene)

    # A pre-existing camera can have the stock 0.1m clip_start, which silently
    # clips away millimetre-scale parts. Pull it in for the render, then restore.
    saved_clip = None
    if not created_cam and getattr(cam.data, "clip_start", None) is not None:
        near = _nearest_geometry_distance(scene, cam)
        if near is not None and near < cam.data.clip_start:
            saved_clip = cam.data.clip_start
            cam.data.clip_start = max(near * 0.5, 1e-6)

    restore_lighting = _ensure_preview_lighting(scene)

    ratio = (render.resolution_y / render.resolution_x) if render.resolution_x else 0.75
    try:
        render.filepath = filepath
        render.image_settings.file_format = "PNG"
        render.resolution_percentage = 100
        render.resolution_x = max_size
        render.resolution_y = max(1, int(max_size * ratio))
        render.film_transparent = False

        errors = []
        for engine in _pick_render_engine():
            try:
                render.engine = engine
                if engine == "CYCLES":
                    scene.cycles.samples = 16
                bpy.ops.render.render(write_still=True)
                if os.path.exists(filepath):
                    return engine
            except Exception as exc:
                errors.append(f"{engine}: {exc}")
        raise RuntimeError("All render engines failed -> " + "; ".join(errors))
    finally:
        (render.engine, render.filepath, render.resolution_x, render.resolution_y,
         render.resolution_percentage, render.image_settings.file_format,
         render.film_transparent) = saved
        restore_lighting()
        if saved_clip is not None:
            cam.data.clip_start = saved_clip
        if created_cam:
            scene.camera = None
            cam_data = cam.data
            bpy.data.objects.remove(cam, do_unlink=True)
            bpy.data.cameras.remove(cam_data)


def cmd_get_viewport_screenshot(params):
    filepath = params.get("filepath")
    if not filepath:
        raise ValueError("No filepath provided")
    max_size = int(params.get("max_size") or 1000)

    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if os.path.exists(filepath):
        os.remove(filepath)

    source = "viewport"
    if not _screenshot_from_viewport(filepath):
        source = f"render:{_screenshot_from_render(filepath, max_size)}"

    if not os.path.exists(filepath):
        raise RuntimeError("Screenshot file was not created")

    width, height = _downscale(filepath, max_size)
    return {"success": True, "filepath": filepath, "width": width, "height": height, "source": source}


def _disabled_integration(name, hint):
    def handler(params):
        return {"enabled": False, "message": f"{name} is disabled. {hint}"}
    return handler


_UNSUPPORTED = (
    "search_polyhaven_assets", "download_polyhaven_asset", "set_texture",
    "get_polyhaven_categories", "search_sketchfab_models",
    "get_sketchfab_model_preview", "download_sketchfab_model",
    "create_rodin_job", "poll_rodin_job_status", "import_generated_asset",
    "create_hunyuan_job", "poll_hunyuan_job_status", "import_generated_asset_hunyuan",
)


def _unsupported(name):
    def handler(params):
        raise RuntimeError(
            f"'{name}' is not implemented by this addon. External asset providers "
            "(PolyHaven / Sketchfab / Hyper3D / Hunyuan3D) need API keys and outbound "
            "network access. Model geometry with execute_code instead."
        )
    return handler


HANDLERS = {
    "get_scene_info": cmd_get_scene_info,
    "get_object_info": cmd_get_object_info,
    "execute_code": cmd_execute_code,
    "get_viewport_screenshot": cmd_get_viewport_screenshot,
    "get_polyhaven_status": _disabled_integration("PolyHaven", "No API access configured."),
    "get_sketchfab_status": _disabled_integration("Sketchfab", "No API access configured."),
    "get_hyper3d_status": _disabled_integration("Hyper3D Rodin", "No API key configured."),
    "get_hunyuan3d_status": _disabled_integration("Hunyuan3D", "No API key configured."),
}
HANDLERS.update({name: _unsupported(name) for name in _UNSUPPORTED})


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #

class _Job:
    __slots__ = ("command", "params", "response", "done")

    def __init__(self, command, params):
        self.command = command
        self.params = params
        self.response = None
        self.done = threading.Event()


class BlenderMCPServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self.running = False
        self._listener = None
        self._accept_thread = None
        self._jobs = queue.Queue()

    # -- lifecycle -------------------------------------------------------- #

    def start(self):
        if self.running:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Deliberately no SO_REUSEADDR: on Windows it lets a second process
        # silently steal a live port instead of reporting "already in use".
        listener.bind((self.host, self.port))
        listener.listen(5)
        listener.settimeout(0.5)  # so the accept loop can observe self.running
        self._listener = listener
        self.running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="blender-mcp-accept", daemon=True
        )
        self._accept_thread.start()
        if not bpy.app.background:
            bpy.app.timers.register(self._timer_tick, persistent=True)
        log(f"listening on {self.host}:{self.port} (background={bpy.app.background})")

    def stop(self):
        self.running = False
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None
        if not bpy.app.background and bpy.app.timers.is_registered(self._timer_tick):
            bpy.app.timers.unregister(self._timer_tick)
        # Release anything still blocked so client threads don't hang on exit.
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            job.response = {"status": "error", "message": "Server stopped"}
            job.done.set()
        log("stopped")

    # -- main-thread execution -------------------------------------------- #

    def pump(self, max_jobs=8):
        """Run queued commands. MUST be called from Blender's main thread."""
        for _ in range(max_jobs):
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            handler = HANDLERS.get(job.command)
            try:
                if handler is None:
                    raise RuntimeError(f"Unknown command type: {job.command!r}")
                job.response = {"status": "success", "result": handler(job.params)}
            except Exception as exc:
                job.response = {"status": "error", "message": str(exc)}
            finally:
                job.done.set()

    def _timer_tick(self):
        if not self.running:
            return None
        self.pump()
        return 0.02

    # -- socket threads --------------------------------------------------- #

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._client_loop, args=(conn, addr),
                name="blender-mcp-client", daemon=True,
            ).start()

    def _client_loop(self, conn, addr):
        log(f"client connected: {addr}")
        decoder = json.JSONDecoder()
        buffer = ""
        try:
            conn.settimeout(1.0)
            while self.running:
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                # The client sends one command then waits, but decode
                # incrementally anyway so a coalesced pair can't wedge us.
                while buffer.strip():
                    try:
                        command, index = decoder.raw_decode(buffer.lstrip())
                    except json.JSONDecodeError:
                        break  # incomplete; wait for more bytes
                    consumed = len(buffer) - len(buffer.lstrip()) + index
                    buffer = buffer[consumed:]
                    conn.sendall(json.dumps(self._dispatch(command)).encode("utf-8"))
        finally:
            with contextlib.suppress(Exception):
                conn.close()
            log(f"client disconnected: {addr}")

    def _dispatch(self, command):
        if not isinstance(command, dict):
            return {"status": "error", "message": "Command must be a JSON object"}
        job = _Job(command.get("type"), command.get("params") or {})
        self._jobs.put(job)
        if not job.done.wait(JOB_TIMEOUT):
            return {
                "status": "error",
                "message": f"Command {job.command!r} timed out after {JOB_TIMEOUT}s waiting "
                           "for Blender's main thread",
            }
        return job.response


def get_server():
    global _server
    if _server is None:
        _server = BlenderMCPServer()
    return _server


# --------------------------------------------------------------------------- #
# Blender UI
# --------------------------------------------------------------------------- #

class BLENDERMCP_OT_start(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to MCP"
    bl_description = "Start the local MCP command server"

    def execute(self, context):
        try:
            get_server().start()
        except OSError as exc:
            self.report({"ERROR"}, f"Could not bind port {DEFAULT_PORT}: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"BlenderMCP listening on port {DEFAULT_PORT}")
        return {"FINISHED"}


class BLENDERMCP_OT_stop(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Disconnect"
    bl_description = "Stop the local MCP command server"

    def execute(self, context):
        get_server().stop()
        return {"FINISHED"}


class BLENDERMCP_PT_panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "BLENDERMCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlenderMCP"

    def draw(self, context):
        layout = self.layout
        server = get_server()
        if server.running:
            layout.label(text=f"Listening on {server.host}:{server.port}", icon="CHECKMARK")
            layout.operator(BLENDERMCP_OT_stop.bl_idname, icon="CANCEL")
        else:
            layout.label(text="Not connected", icon="UNLINKED")
            layout.operator(BLENDERMCP_OT_start.bl_idname, icon="PLAY")


_CLASSES = (
    BLENDERMCP_OT_start,
    BLENDERMCP_OT_stop,
    BLENDERMCP_PT_panel,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global _server
    if _server is not None:
        _server.stop()
        _server = None
    for cls in reversed(_CLASSES):
        with contextlib.suppress(Exception):
            bpy.utils.unregister_class(cls)
