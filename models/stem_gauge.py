"""Gauge that finds the largest keycap stem boss a switch will accept.

    blender --background --python models\\stem_gauge.py

The socket wall is (stem_diameter - cross_arm_length) / 2, and the cross arm
length is fixed by the switch, so the only way to thicken the wall is to widen
the boss. 5.5mm printed too thin and the walls broke when the cap was pulled off;
6.6mm was thick enough but fouls the switch's top housing, so the switch no
longer springs back cleanly.

Rather than reprint a whole keycap per guess, this prints five bosses that differ
only in diameter, each with the real MX cross socket and a grip tab marked with
1-5 ribs. Push each onto a switch and actuate it: the largest one that still
returns freely is the answer, and its wall thickness is printed in the report.
"""

import json
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mxgeom import (
    boolean, export_stl, make_box, make_cylinder, mesh_report, reset_scene,
    verify_stl_millimetres,
)

G = {
    "diameters": (5.8, 6.0, 6.2, 6.4, 6.6),
    "boss_height": 7.0,
    "cross_arm_length": 4.1,     # must match the keycap, and the switch
    "cross_arm_width": 1.35,
    "cross_depth": 4.0,
    "grip_size": (12.0, 7.0, 2.0),
    "pitch": 20.0,
    "segments": 64,
    "mark_size": (1.2, 3.0, 0.6),
}

REPORT = {}


def build(g):
    parts = []
    count = len(g["diameters"])
    for index, diameter in enumerate(g["diameters"]):
        x = (index - (count - 1) / 2.0) * g["pitch"]

        boss = make_cylinder(
            f"Boss{index}", diameter / 2.0, g["boss_height"],
            (x, 0.0, g["boss_height"] / 2.0), g["segments"],
        )

        # Grip tab on top so it can be pushed on and pulled off by hand without
        # loading the socket walls the way a whole keycap would.
        grip = make_box(
            f"Grip{index}", g["grip_size"],
            (x, 0.0, g["boss_height"] + g["grip_size"][2] / 2.0),
        )
        boolean(boss, grip, "UNION")

        # Ribs on the tab: index + 1 of them, so the winner is identifiable
        # after it has been pushed onto a switch a few times.
        for rib in range(index + 1):
            mark = make_box(
                f"Mark{index}_{rib}",
                g["mark_size"],
                (x - g["grip_size"][0] / 2.0 + 2.0 + rib * 2.0,
                 -g["grip_size"][1] / 2.0 + 2.0,
                 g["boss_height"] + g["grip_size"][2] + g["mark_size"][2] / 2.0),
            )
            boolean(boss, mark, "UNION")

        # MX cross socket, cut from the bottom.
        arm_l, arm_w = g["cross_arm_length"], g["cross_arm_width"]
        z0, z1 = -0.5, g["cross_depth"]
        cross_a = make_box(f"CrossA{index}", (arm_l, arm_w, z1 - z0),
                           (x, 0.0, (z0 + z1) / 2.0))
        cross_b = make_box(f"CrossB{index}", (arm_w, arm_l, z1 - z0),
                           (x, 0.0, (z0 + z1) / 2.0))
        boolean(cross_a, cross_b, "UNION")
        boolean(boss, cross_a, "DIFFERENCE")

        boss.name = f"Stem_{str(diameter).replace('.', 'p')}"
        boss.data.name = boss.name
        parts.append(boss)

    base_name = parts[0].name
    for other in [p.name for p in parts[1:]]:
        boolean(bpy.data.objects[base_name], bpy.data.objects[other], "UNION")
    part = bpy.data.objects[base_name]
    part.name = "Stem_Gauge"
    part.data.name = "Stem_Gauge"
    return part


def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()
    part = build(G)

    REPORT["parameters"] = G
    REPORT["cells"] = [
        {
            "ribs": index + 1,
            "diameter_mm": diameter,
            "socket_wall_mm": round((diameter - G["cross_arm_length"]) / 2.0, 3),
        }
        for index, diameter in enumerate(G["diameters"])
    ]
    REPORT["dimensions_mm"] = [round(v, 4) for v in part.dimensions]
    REPORT["mesh"] = mesh_report(part)

    mesh = REPORT["mesh"]
    if not mesh["watertight"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - normals point inward"
    else:
        REPORT["VERDICT"] = "printable"

    stl = os.path.join(project, "models", "stem_gauge.stl")
    export_stl(part, stl)
    REPORT["stl"] = verify_stl_millimetres(stl)

    print("GAUGE_REPORT_START")
    print(json.dumps(REPORT, indent=2))
    print("GAUGE_REPORT_END")


if __name__ in ("__blender_mcp__", "__main__"):
    main()
