"""Assemble the keychain parts into one .blend for visual review.

    blender --background --python tools/review_scene.py

Loads keycap_1u_r3_logo.stl, switch_housing.stl and switch_housing_cap.stl,
places them as they assemble, frames the viewport from the side (where the
logo's flat top is the thing to judge), and saves review.blend.
"""

import os
import sys

import bpy
import mathutils

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "models"))

PARTS = (
    ("Keycap", "keycap_1u_r3_logo.stl"),
    ("Housing", "switch_housing.stl"),
    ("Cap", "switch_housing_cap.stl"),
)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

unit = bpy.context.scene.unit_settings
unit.system = "METRIC"
unit.scale_length = 0.001
unit.length_unit = "MILLIMETERS"

loaded = {}
for name, filename in PARTS:
    path = os.path.join(ROOT, "models", filename)
    if not os.path.exists(path):
        print(f"MISSING {path}")
        continue
    before = set(bpy.data.objects.keys())
    bpy.ops.wm.stl_import(filepath=path, global_scale=1.0, use_scene_unit=False)
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    obj = new[0]
    obj.name = name
    obj.data.name = name
    loaded[name] = obj
    print(f"loaded {name}: {[round(v, 4) for v in obj.dimensions]}")

# Assembly. The housing's plate top is its own z = height; the switch sits in it
# and the keycap sits on the switch, so the keycap floats above the plate by the
# amount of switch that protrudes. 6.2mm is the MX top housing above the plate.
SWITCH_ABOVE_PLATE = 6.2
if "Housing" in loaded:
    housing = loaded["Housing"]
    plate_top = max((housing.matrix_world @ v.co).z for v in housing.data.vertices)
else:
    plate_top = 11.0

if "Cap" in loaded:
    cap = loaded["Cap"]
    cap_h = cap.dimensions[2]
    # Cap seats under the housing, tongues pointing up into the pocket.
    cap.rotation_euler = (0.0, 0.0, 0.0)
    cap.location = (0.0, 0.0, -cap.dimensions[2] + (cap_h - 1.2))

if "Keycap" in loaded:
    keycap_obj = loaded["Keycap"]
    keycap_obj.location = (0.0, 0.0, plate_top + SWITCH_ABOVE_PLATE)

# Frame the side view, which is where the logo's flat top reads.
target = mathutils.Vector((0.0, 0.0, plate_top * 0.6))
eye = mathutils.Vector((0.35, -1.0, 0.18))
framed = 0
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.show_region_ui = True
        space.shading.type = "SOLID"
        space.shading.light = "STUDIO"
        space.shading.color_type = "OBJECT"
        space.clip_start = 0.05
        space.clip_end = 2000.0
        r3d = space.region_3d
        r3d.view_perspective = "PERSP"
        r3d.view_location = target
        r3d.view_distance = 70.0
        r3d.view_rotation = eye.normalized().to_track_quat("Z", "Y")
        framed += 1

colours = {
    "Keycap": (0.85, 0.86, 0.90, 1.0),
    "Housing": (0.45, 0.60, 0.80, 1.0),
    "Cap": (0.80, 0.60, 0.40, 1.0),
}
for name, obj in loaded.items():
    obj.color = colours.get(name, (0.8, 0.8, 0.8, 1.0))

out = os.path.join(ROOT, "models", "review.blend")
bpy.ops.wm.save_as_mainfile(filepath=out)
print(f"view3d areas framed: {framed}")
print(f"REVIEW_BLEND {out}")
