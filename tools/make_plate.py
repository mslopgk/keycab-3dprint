"""Lay copies of one STL out on a grid with an exact gap, as a single STL.

    PLATE_STL   source STL
    PLATE_OUT   destination STL
    PLATE_COLS  columns along X   (default 4)
    PLATE_ROWS  rows along Y      (default 4)
    PLATE_GAP   clear space between neighbours, mm (default 8)

    blender --background --python tools/make_plate.py

OrcaSlicer's --arrange decides the layout itself and gives no way to set the
spacing: 16 housings came out as 3x5+1 packed 2.5mm apart, close enough that
printing one part disturbed its neighbour. Baking the layout into one STL takes
the decision back -- the slicer sees a single object and arranges nothing.

Prints the resulting footprint so it can be checked against the 180x180 bed
before a three-hour job commits to it.
"""

import os
import sys

import bpy

SRC = os.environ.get(
    "PLATE_STL",
    r"C:\Users\user\orca\projects\keycab-3dprint\models\switch_housing_fin_FINAL.stl",
)
OUT = os.environ.get(
    "PLATE_OUT",
    r"C:\Users\user\orca\projects\keycab-3dprint\models\housing_plate_4x4.stl",
)
COLS = int(os.environ.get("PLATE_COLS", 4))
ROWS = int(os.environ.get("PLATE_ROWS", 4))
GAP = float(os.environ.get("PLATE_GAP", 8.0))
BED = float(os.environ.get("PLATE_BED", 180.0))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

unit = bpy.context.scene.unit_settings
unit.system = "METRIC"
unit.scale_length = 0.001
unit.length_unit = "MILLIMETERS"

before = set(bpy.data.objects.keys())
bpy.ops.wm.stl_import(filepath=SRC, global_scale=1.0, use_scene_unit=False)
new = [bpy.data.objects[k] for k in set(bpy.data.objects.keys()) - before]
if len(new) != 1:
    raise SystemExit(f"expected one object from {SRC}, got {len(new)}")
base = new[0]

size_x, size_y, size_z = (round(v, 4) for v in base.dimensions)
pitch_x = size_x + GAP
pitch_y = size_y + GAP
span_x = COLS * size_x + (COLS - 1) * GAP
span_y = ROWS * size_y + (ROWS - 1) * GAP

print(f"part            : {size_x} x {size_y} x {size_z} mm")
print(f"grid            : {COLS} x {ROWS} = {COLS * ROWS} copies, gap {GAP} mm")
print(f"pitch           : {pitch_x} x {pitch_y} mm")
print(f"footprint       : {span_x:.2f} x {span_y:.2f} mm")
print(f"bed             : {BED} x {BED} mm")
print(f"margin per side : {(BED - span_x) / 2.0:.2f} (X)  {(BED - span_y) / 2.0:.2f} (Y)")
if span_x > BED or span_y > BED:
    raise SystemExit("footprint does not fit the bed -- reduce the grid or the gap")

copies = []
for row in range(ROWS):
    for col in range(COLS):
        if row == 0 and col == 0:
            obj = base
        else:
            obj = base.copy()
            obj.data = base.data.copy()
            bpy.context.scene.collection.objects.link(obj)
        obj.location = (
            (col - (COLS - 1) / 2.0) * pitch_x,
            (row - (ROWS - 1) / 2.0) * pitch_y,
            0.0,
        )
        copies.append(obj)

bpy.ops.object.select_all(action="DESELECT")
for obj in copies:
    obj.select_set(True)
bpy.context.view_layer.objects.active = copies[0]
bpy.ops.object.join()
joined = bpy.context.view_layer.objects.active
joined.name = "HousingPlate"

got = [round(v, 3) for v in joined.dimensions]
print(f"joined mesh     : {got[0]} x {got[1]} x {got[2]} mm, "
      f"{len(joined.data.polygons)} faces")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.wm.stl_export(
    filepath=OUT, check_existing=False, export_selected_objects=True,
    apply_modifiers=True, ascii_format=False,
    global_scale=1.0, use_scene_unit=False, forward_axis="Y", up_axis="Z",
)
print("WROTE", OUT)
