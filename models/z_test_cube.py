"""A 20 x 20 x 10.00 mm block for checking that the printer builds to height.

    blender --background --python models\\z_test_cube.py

A 25-cap plate came out roughly half its modelled height while the printer
reported all 99 layers done, and the file on the printer's SD was verified
byte-identical to the sliced one. So the cause is on the machine, and this
separates "the Z axis is wrong" from "something only goes wrong on a long job":
print this, measure it, and 10 mm versus 5 mm answers it in eight minutes.

Steps are cut into one side at 2/4/6/8 mm so the height can be read off against
a ruler, or against a keycap, without callipers.
"""

import json
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mxgeom import (
    boolean, export_stl, make_box, mesh_report, reset_scene, verify_stl_millimetres,
)

# ZCUBE_HEIGHT overrides the height. A 10 mm block only proves the first
# centimetre; after a calibration you want the test to be at least as tall as
# the job that failed, so the Z error has room to accumulate where you can see
# it. Notches are spaced to keep about eight of them however tall it gets.
_HEIGHT = float(os.environ.get("ZCUBE_HEIGHT", 10.0))
_SPACING = 2.0 if _HEIGHT <= 12.0 else 5.0

C = {
    "footprint": 20.0,
    "height": _HEIGHT,
    "step_marks": tuple(
        round(_SPACING * i, 3)
        for i in range(1, int(_HEIGHT / _SPACING) + 1)
        if _SPACING * i < _HEIGHT - 0.5
    ),
    "notch_depth": 0.8,
    "notch_height": 0.4,
}

REPORT = {}


def build(c):
    block = make_box(
        "Z_Test_Cube",
        (c["footprint"], c["footprint"], c["height"]),
        (0.0, 0.0, c["height"] / 2.0),
    )

    # Notches on the +X face at known heights. A notch, not a rib, so nothing
    # protrudes to be knocked off and nothing needs support.
    for z in c["step_marks"]:
        notch = make_box(
            f"Notch{int(z)}",
            (c["notch_depth"] * 2.0, c["footprint"] * 0.6, c["notch_height"]),
            (c["footprint"] / 2.0, 0.0, z),
        )
        boolean(block, notch, "DIFFERENCE")

    block.name = "Z_Test_Cube"
    block.data.name = "Z_Test_Cube"
    return block


def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()
    block = build(C)

    REPORT["parameters"] = C
    REPORT["dimensions_mm"] = [round(v, 4) for v in block.dimensions]
    REPORT["mesh"] = mesh_report(block)
    REPORT["expected"] = {
        "height_mm": C["height"],
        "notches_at_mm": list(C["step_marks"]),
        "layers_at_0p28": round(C["height"] / 0.28, 1),
    }

    mesh = REPORT["mesh"]
    if not mesh["watertight"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - normals point inward"
    elif abs(block.dimensions[2] - C["height"]) > 1e-4:
        REPORT["VERDICT"] = f"WRONG HEIGHT - modelled {block.dimensions[2]}"
    else:
        REPORT["VERDICT"] = "printable"

    suffix = "" if abs(C["height"] - 10.0) < 1e-6 else f"_{C['height']:g}mm"
    stl = os.path.join(project, "models", f"z_test_cube{suffix}.stl")
    export_stl(block, stl)
    REPORT["stl"] = verify_stl_millimetres(stl)

    print("ZCUBE_REPORT_START")
    print(json.dumps(REPORT, indent=2))
    print("ZCUBE_REPORT_END")


if __name__ in ("__blender_mcp__", "__main__"):
    main()
