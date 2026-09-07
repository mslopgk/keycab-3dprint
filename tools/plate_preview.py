"""Rebuild a sliced plate's real layout in Blender so it can be looked at.

    blender --background --python tools/plate_preview.py -- <gcode> <stl> [bed]

The arrangement is the slicer's, so the positions are read back out of the
sliced gcode rather than guessed: every object is bracketed by
"; start printing object, unique label id: N" / "; stop printing object", and
the extruding moves in between give that instance's footprint.

Draws the bed as a plane with a raised border so anything hanging off the edge is
obvious, places one linked copy of the STL per instance, frames it top-down, and
saves models/plate_preview.blend.
"""

import os
import re
import sys

import bmesh
import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
GCODE = argv[0] if argv else r"C:\Users\user\orca\projects\keycab-3dprint\gcode\plate_1.gcode"
STL = argv[1] if len(argv) > 1 else \
    r"C:\Users\user\orca\projects\keycab-3dprint\models\keycap_1u_r3_logo.stl"
BED = float(argv[2]) if len(argv) > 2 else 180.0
LINE_BUDGET = 600_000

# Values are written without a leading zero ("E.8", "X.25"), so a pattern that
# demands a digit before the point silently matches nothing.
NUM = r"(-?(?:\d+\.?\d*|\.\d+))"
start_re = re.compile(r"^; start printing object, unique label id:\s*(\d+)")
stop_re = re.compile(r"^; stop printing object")
move_re = re.compile(r"^G[01]\s")
x_re = re.compile("X" + NUM)
y_re = re.compile("Y" + NUM)
e_re = re.compile("E" + NUM)

boxes = {}
current = None
x = y = None
with open(GCODE, "r", encoding="utf-8", errors="replace") as handle:
    for index, line in enumerate(handle):
        if index > LINE_BUDGET:
            break
        started = start_re.match(line)
        if started:
            current = int(started.group(1))
            continue
        if stop_re.match(line):
            current = None
            continue
        if current is None or not move_re.match(line):
            continue
        mx, my, me = x_re.search(line), y_re.search(line), e_re.search(line)
        if mx:
            x = float(mx.group(1))
        if my:
            y = float(my.group(1))
        if not (me and float(me.group(1)) > 0):
            continue
        if x is None or y is None or y < 0.0:
            continue
        box = boxes.get(current)
        if box is None:
            boxes[current] = [x, y, x, y]
        else:
            box[0] = min(box[0], x)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x)
            box[3] = max(box[3], y)

print(f"instances found: {len(boxes)}")
if not boxes:
    raise SystemExit("no object output parsed from the gcode")

centres = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) for b in boxes.values()]
xs = [c[0] for c in centres]
ys = [c[1] for c in centres]
print(f"centres span   : X {min(xs):.2f}..{max(xs):.2f}  Y {min(ys):.2f}..{max(ys):.2f}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

unit = bpy.context.scene.unit_settings
unit.system = "METRIC"
unit.scale_length = 0.001
unit.length_unit = "MILLIMETERS"

# Bed: a plate plus a thin raised border, so an overhanging part is unmistakable.
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=BED / 2.0)
mesh = bpy.data.meshes.new("Bed")
bm.to_mesh(mesh)
bm.free()
bed = bpy.data.objects.new("Bed", mesh)
bpy.context.scene.collection.objects.link(bed)
bed.location = (BED / 2.0, BED / 2.0, -0.2)
bed.color = (0.12, 0.12, 0.14, 1.0)

for name, sx, sy, px, py in (
    ("BedEdgeS", BED, 1.0, BED / 2.0, 0.0),
    ("BedEdgeN", BED, 1.0, BED / 2.0, BED),
    ("BedEdgeW", 1.0, BED, 0.0, BED / 2.0),
    ("BedEdgeE", 1.0, BED, BED, BED / 2.0),
):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, 1.0), verts=bm.verts[:])
    m = bpy.data.meshes.new(name)
    bm.to_mesh(m)
    bm.free()
    edge = bpy.data.objects.new(name, m)
    bpy.context.scene.collection.objects.link(edge)
    edge.location = (px, py, 0.0)
    edge.color = (0.55, 0.20, 0.20, 1.0)

before = set(bpy.data.objects.keys())
bpy.ops.wm.stl_import(filepath=STL, global_scale=1.0, use_scene_unit=False)
source = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before][0]
source.name = "Keycap_master"
print(f"master dims    : {[round(v, 3) for v in source.dimensions]}")

# The STL is modelled centred on the origin, so shifting by the centre is enough.
for index, (cx, cy) in enumerate(sorted(centres, key=lambda c: (c[1], c[0]))):
    copy = source.copy()          # linked: one mesh, 25 objects
    bpy.context.scene.collection.objects.link(copy)
    copy.name = f"Keycap_{index:02d}"
    copy.location = (cx, cy, 0.0)
    copy.color = (0.85, 0.86, 0.90, 1.0)

bpy.data.objects.remove(source, do_unlink=True)

framed = 0
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.show_region_ui = True
        space.shading.type = "SOLID"
        space.shading.color_type = "OBJECT"
        space.overlay.show_floor = False
        space.clip_start = 0.1
        space.clip_end = 4000.0
        r3d = space.region_3d
        r3d.view_perspective = "PERSP"
        r3d.view_location = mathutils.Vector((BED / 2.0, BED / 2.0, 6.0))
        r3d.view_distance = 330.0
        # Slightly off straight-down so the caps read as solids, not squares.
        r3d.view_rotation = mathutils.Vector((0.12, -0.30, 1.0)).normalized() \
            .to_track_quat("Z", "Y")
        framed += 1
print(f"view3d framed  : {framed}")

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "models", "plate_preview.blend")
bpy.ops.wm.save_as_mainfile(filepath=out)
print(f"PLATE_PREVIEW {out}")
