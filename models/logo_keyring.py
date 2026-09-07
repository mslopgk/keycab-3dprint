"""Standalone logo keyring: the logo itself is the part, no keycap involved.

    blender --background --python models\\logo_keyring.py

Design notes:

* 35mm across, 3mm thick. At that size the logo's own strokes are already wider
  than the nozzle, so nothing has to be thickened for printability -- but the
  approved look came from dilating by 0.30mm at 12mm, so the dilation is scaled
  by the same factor to keep the weight looking the same rather than suddenly
  spindly.
* The wave stays filled (fill_regions), as approved for the keycap.
* The logo is one connected piece, so it can be the whole part with its interior
  openings as through-holes. The filled wave supplies most of the mass.
* The ring stroke is far too narrow to take a 4mm hole, so the keyring hangs from
  a lug that overlaps the circle, the same pattern the switch housing uses.
"""

import json
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import logo
from mxgeom import (
    boolean, export_stl, make_box, make_cylinder, mesh_report, reset_scene,
    verify_stl_millimetres,
)

SVG = r"C:\Users\user\Documents\카카오톡 받은 파일\church-wave-logo-03-minimal-line.svg"

REFERENCE_DIAMETER = 12.0      # what the approved dilation was chosen at
REFERENCE_DILATE = 0.30

K = {
    "svg": SVG,
    "diameter_mm": 35.0,
    "thickness_mm": 3.0,
    "fill_regions": (1,),
    # Built at the 12mm reference size and then scaled up. Dilation scales with
    # the mesh, so this is identical to dilating 0.875mm at 35mm -- but the raster
    # stays at the 12mm cell count. Rasterising 35mm directly ran past 10 minutes
    # because the filled wave covers ~620mm2, which is ~100k cells at 0.08mm.
    "pixel_mm": 0.04,
    "lug_protrusion": 7.0,       # beyond the circle's outer edge
    "lug_width": 9.0,
    "lug_hole_diameter": 4.0,
    "lug_hole_surround": 2.0,
}

REPORT = {}


def build(k):
    factor = k["diameter_mm"] / REFERENCE_DIAMETER
    prism, stats = logo.build_logo_prism(
        k["svg"], REFERENCE_DIAMETER, REFERENCE_DILATE, k["pixel_mm"],
        z0=0.0, z1=k["thickness_mm"] / factor, fill_regions=k["fill_regions"],
    )
    REPORT["logo"] = stats
    REPORT["logo"]["built_at_mm"] = REFERENCE_DIAMETER
    REPORT["logo"]["scaled_by"] = round(factor, 4)
    REPORT["logo"]["effective_dilate_mm"] = round(REFERENCE_DILATE * factor, 4)

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = prism
    prism.select_set(True)
    prism.scale = (factor, factor, factor)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    outer_r = k["diameter_mm"] / 2.0 + REFERENCE_DILATE * factor
    hole_r = k["lug_hole_diameter"] / 2.0
    # Hole centre sits far enough out that the surround clears the tip, and the
    # tab overlaps the circle so the union has no coincident faces.
    tip_y = outer_r + k["lug_protrusion"]
    hole_y = tip_y - k["lug_hole_surround"] - hole_r
    overlap = 2.0
    tab_len = tip_y - (outer_r - overlap)

    tab = make_box(
        "Lug",
        (k["lug_width"], tab_len, k["thickness_mm"]),
        (0.0, (tip_y + outer_r - overlap) / 2.0, k["thickness_mm"] / 2.0),
    )
    boolean(prism, tab, "UNION")

    hole = make_cylinder(
        "LugHole", hole_r, k["thickness_mm"] + 2.0,
        (0.0, hole_y, k["thickness_mm"] / 2.0), 64,
    )
    boolean(prism, hole, "DIFFERENCE")

    prism.name = "Logo_Keyring"
    prism.data.name = "Logo_Keyring"
    REPORT["lug"] = {
        "outer_radius_mm": round(outer_r, 3),
        "tip_y_mm": round(tip_y, 3),
        "hole_centre_y_mm": round(hole_y, 3),
        "tip_margin_mm": round(tip_y - hole_y - hole_r, 3),
    }
    return prism


def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()

    part = build(K)
    REPORT["parameters"] = K
    REPORT["dimensions_mm"] = [round(v, 4) for v in part.dimensions]
    REPORT["mesh"] = mesh_report(part)

    mesh = REPORT["mesh"]
    thin = REPORT["logo"]["dilated"]
    if not mesh["watertight"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - normals point inward"
    elif REPORT["lug"]["tip_margin_mm"] < 1.0:
        REPORT["VERDICT"] = "NOT PRINTABLE - too little material past the lug hole"
    else:
        REPORT["VERDICT"] = "printable"

    stl = os.path.join(project, "models", "logo_keyring.stl")
    export_stl(part, stl)
    REPORT["stl"] = verify_stl_millimetres(stl)

    blend = os.path.join(project, "models", "logo_keyring.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    print("KEYRING_REPORT_START")
    print(json.dumps(REPORT, indent=2, ensure_ascii=False))
    print("KEYRING_REPORT_END")


if __name__ in ("__blender_mcp__", "__main__"):
    main()
