"""Show the four keyring-lug styles in a row, framed from below.

    blender --background --python tools/review_lug_styles.py
    blender models\\review_lug.blend

Framed from underneath on purpose: the defect being fixed is on the lug's
underside, which is the one surface a normal three-quarter view hides.
"""

import os
import sys

import bpy
import mathutils

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "models"))

# (file, label, colour) -- the as-printed tab first, so the others read as edits
# to it rather than as four unrelated shapes.
STYLES = (
    ("switch_housing.stl", "1_current_tab_BAD", (0.80, 0.36, 0.32)),
    ("switch_housing_gusset.stl", "2_gusset_45deg", (0.42, 0.70, 0.45)),
    ("switch_housing_fin.stl", "3_vertical_fin", (0.40, 0.62, 0.86)),
    ("switch_housing_corner.stl", "4_corner_boss", (0.85, 0.68, 0.30)),
)

SPACING = 34.0

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

unit = bpy.context.scene.unit_settings
unit.system = "METRIC"
unit.scale_length = 0.001
unit.length_unit = "MILLIMETERS"

placed = []
for index, (filename, label, rgb) in enumerate(STYLES):
    path = os.path.join(ROOT, "models", filename)
    if not os.path.exists(path):
        print(f"MISSING {path}")
        continue
    before = set(bpy.data.objects.keys())
    bpy.ops.wm.stl_import(filepath=path, global_scale=1.0, use_scene_unit=False)
    new = [bpy.data.objects[k] for k in set(bpy.data.objects.keys()) - before]
    obj = new[0]
    obj.name = label
    obj.location = ((index - (len(STYLES) - 1) / 2.0) * SPACING, 0.0, 0.0)

    material = bpy.data.materials.new(f"{label}Mat")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    placed.append((label, [round(v, 2) for v in obj.dimensions]))

for label, dims in placed:
    print(f"  {label:22s} {dims}")

target = mathutils.Vector((0.0, 0.0, 7.0))
# Low and slightly under, so each lug's underside is the visible face.
eye = mathutils.Vector((-0.35, -1.0, -0.45))
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.shading.type = "SOLID"
        space.shading.color_type = "MATERIAL"
        space.overlay.grid_scale = 1.0
        space.clip_start = 0.05
        space.clip_end = 2000.0
        r3d = space.region_3d
        r3d.view_perspective = "PERSP"
        r3d.view_location = target
        r3d.view_distance = 165.0
        r3d.view_rotation = eye.normalized().to_track_quat("Z", "Y")

path = os.path.join(ROOT, "models", "review_lug.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
print("SAVED", path)
