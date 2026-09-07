"""Frame the saved keycap file so it opens ready to look at in the GUI.

    blender --background models\\keycap_1u_r3.blend --python tools\\prepare_gui_view.py

Opened as-is, the default viewport is framed for a 2 m cube, so an 18 mm keycap
is a speck at the origin. The viewport camera lives in the .blend, so it can be
positioned here instead of needing a startup script in the GUI session.
"""

import math
import os

import bpy
import mathutils

TARGET = mathutils.Vector((0.0, 0.0, 4.3))
EYE_DIRECTION = mathutils.Vector((1.0, -1.15, 0.72))
VIEW_DISTANCE = 52.0

keycap = bpy.data.objects.get("Keycap_1u_R3")
if keycap is None:
    raise SystemExit(f"Keycap_1u_R3 not in {bpy.data.filepath!r}: "
                     f"{[o.name for o in bpy.data.objects]}")

print("objects in file:", [(o.name, o.type) for o in bpy.data.objects])
print("keycap dimensions (mm):", [round(v, 4) for v in keycap.dimensions])
print("polygons:", len(keycap.data.polygons))

bpy.ops.object.select_all(action="DESELECT")
keycap.select_set(True)
bpy.context.view_layer.objects.active = keycap

framed = 0
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.show_region_ui = True          # sidebar, where the BlenderMCP panel lives
        space.shading.type = "SOLID"
        space.shading.light = "STUDIO"
        space.shading.color_type = "SINGLE"
        space.overlay.show_floor = True
        space.overlay.show_axis_x = True
        space.overlay.show_axis_y = True
        # Millimetre-scale work: pull the grid down so it reads as a 1 mm grid
        # rather than one square per metre.
        space.overlay.grid_scale = 1.0
        space.clip_start = 0.05
        space.clip_end = 2000.0

        r3d = space.region_3d
        r3d.view_perspective = "PERSP"
        r3d.view_location = TARGET
        r3d.view_distance = VIEW_DISTANCE
        # The view looks down its own -Z, so +Z of the rotation points at the eye.
        r3d.view_rotation = EYE_DIRECTION.normalized().to_track_quat("Z", "Y")
        framed += 1

print("view3d areas framed:", framed)

bpy.ops.wm.save_mainfile()
print("PREPARED", bpy.data.filepath)
