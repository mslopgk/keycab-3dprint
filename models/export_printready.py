"""Export the keycap in its print orientation: top face down on the plate.

    blender --background models\\keycap_1u_r3.blend --python models\\export_printready.py

Why upside down. Right side up (bottom rim on the plate) puts the cavity ceiling
-- which runs parallel to the dish -- facing downwards at only ~17.7 degrees from
horizontal. At a 0.2 mm layer height that steps roughly 1.8 mm sideways per
layer, so it needs support *inside* the keycap, which is miserable to remove.
Flipped, that same surface faces up and the part needs no support at all.

The cost is contact area: the dish is concave, so the part lands on two lines
along the front and back edges of the top plateau, 13.2 mm apart. That is stable
against tipping but wants a brim, which is set in the slicing step.
"""

import json
import math
import os

import bmesh
import bpy
import mathutils

NAME = "Keycap_1u_R3"
OUT = os.path.join(os.path.dirname(os.path.abspath(bpy.data.filepath)),
                   "keycap_1u_r3_printready.stl")

obj = bpy.data.objects.get(NAME)
if obj is None:
    raise SystemExit(f"{NAME} missing from {bpy.data.filepath}")

report = {"before_dimensions": [round(v, 4) for v in obj.dimensions]}

# Bake the flip into the mesh rather than relying on the exporter to apply the
# object transform, so what the STL contains is unambiguous.
flip = mathutils.Matrix.Rotation(math.radians(180.0), 4, "X")
obj.data.transform(flip)
obj.matrix_world = mathutils.Matrix.Identity(4)

# Drop it onto z = 0.
lo_z = min((obj.matrix_world @ v.co).z for v in obj.data.vertices)
obj.data.transform(mathutils.Matrix.Translation((0.0, 0.0, -lo_z)))
obj.data.update()

verts = [v.co for v in obj.data.vertices]
report["bbox_min"] = [round(min(v[i] for v in verts), 4) for i in range(3)]
report["bbox_max"] = [round(max(v[i] for v in verts), 4) for i in range(3)]

bm = bmesh.new()
bm.from_mesh(obj.data)
bm.normal_update()
non_manifold = [e for e in bm.edges if len(e.link_faces) != 2]
volume = bm.calc_volume(signed=True)
report["non_manifold_edges"] = len(non_manifold)
report["signed_volume_mm3"] = round(volume, 4)
report["normals_outward"] = volume > 0
bm.free()

# What sits on the plate: the lowest ring of geometry. Report its extent so the
# brim decision is based on a measurement, not a guess.
tol = 0.05
low = [v for v in verts if v.z < tol]
if low:
    report["plate_contact"] = {
        "vertex_count": len(low),
        "x_range": [round(min(v.x for v in low), 3), round(max(v.x for v in low), 3)],
        "y_range": [round(min(v.y for v in low), 3), round(max(v.y for v in low), 3)],
    }

bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.wm.stl_export(
    filepath=OUT, check_existing=False, export_selected_objects=True,
    apply_modifiers=True, ascii_format=False,
    global_scale=1.0, use_scene_unit=False, forward_axis="Y", up_axis="Z",
)

import struct
with open(OUT, "rb") as handle:
    handle.read(80)
    (count,) = struct.unpack("<I", handle.read(4))
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for _ in range(count):
        values = struct.unpack("<12fH", handle.read(50))
        for corner in range(3):
            for axis in range(3):
                value = values[3 + corner * 3 + axis]
                lo[axis] = min(lo[axis], value)
                hi[axis] = max(hi[axis], value)
report["stl"] = {
    "path": OUT,
    "triangles": count,
    "min": [round(v, 4) for v in lo],
    "max": [round(v, 4) for v in hi],
    "size_mm": [round(hi[i] - lo[i], 4) for i in range(3)],
}

print("PRINTREADY_REPORT_START")
print(json.dumps(report, indent=2))
print("PRINTREADY_REPORT_END")
