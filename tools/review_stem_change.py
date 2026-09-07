"""Put the old and new stem profiles side by side, both cut open.

    blender --background --python tools/review_stem_change.py
    blender models\\review_stem.blend

The change that matters is inside the cap, so a render of the outside shows
nothing. Both versions are halved on the XZ plane and placed next to a marker
at the height the switch bore reaches when the key is bottomed out -- the one
line that decides whether the cap springs back.

The logo is skipped deliberately: it costs minutes to raster and sits at the
other end of the part from the change.
"""

import os
import sys

import bpy
import mathutils

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "models"))

import keycap
import keycap_logo
from mxgeom import boolean, make_box, mesh_report, reset_scene

ENGAGED = keycap_logo.MX_TRAVEL_MM + (
    keycap.P["cross_depth"] - keycap_logo.MX_STEM_PROUD_MM
)

# What v2 was, restated here so the comparison does not depend on git history.
V2 = {
    "stem_taper_z": 3.0,
    "stem_clear_z": 0.0,
    "stem_lead_in": 0.0,
    "rib_bottom_z": 3.6,
}

SPACING = 12.0


def halved(name, overrides, x_offset):
    p = dict(keycap.P)
    p.update(keycap_logo.KEYCAP_OVERRIDES)
    p.update(overrides)
    cap = keycap.build_keycap(p)
    cap.name = name
    cap.data.name = name

    span = p["base_width"] * 3.0
    cutter = make_box("HalfCut", (span, span, span),
                      (0.0, span / 2.0, p["height"] / 2.0))
    boolean(cap, cutter, "DIFFERENCE")
    cap.location = (x_offset, 0.0, 0.0)
    return cap, mesh_report(cap)


def coloured(obj, rgb):
    material = bpy.data.materials.new(f"{obj.name}Mat")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    obj.data.materials.clear()
    obj.data.materials.append(material)


reset_scene()

old, old_stats = halved("v2_taper_to_3mm", V2, -SPACING)
new, new_stats = halved("v3_clear_to_5mm", {}, SPACING)
coloured(old, (0.80, 0.42, 0.36))
coloured(new, (0.42, 0.66, 0.85))

# The full-press line. Anything of the boss below this sits inside the switch
# bore at the bottom of the stroke and must stay at the tip diameter.
marker = make_box("FullPressLine", (SPACING * 2.0 + 26.0, 0.6, 0.12),
                  (0.0, -6.0, ENGAGED))
coloured(marker, (0.95, 0.78, 0.20))

print(f"full-press line at z = {ENGAGED:.2f} mm")
for label, stats in (("v2", old_stats), ("v3", new_stats)):
    print(f"  {label}: watertight={stats['watertight']} "
          f"non_manifold={stats['non_manifold_edges']}")

target = mathutils.Vector((0.0, 0.0, 5.0))
eye = mathutils.Vector((0.12, -1.0, 0.16))
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
        r3d.view_distance = 62.0
        r3d.view_rotation = eye.normalized().to_track_quat("Z", "Y")

path = os.path.join(ROOT, "models", "review_stem.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
print("SAVED", path)
