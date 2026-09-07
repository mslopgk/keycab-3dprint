"""One-piece closed-box housing that retains an MX-compatible switch.

Spec: docs/superpowers/specs/2026-08-10-keycap-keychain-design.md

    blender --background --python models\\switch_housing.py

Modelled at 1 Blender unit == 1 mm. The switch is held the way a keyboard holds
it -- latches gripping the underside of a 1.5 mm plate -- so click travel matches
a keyboard by construction rather than by matching absolute stem heights.

The switch drops in from above into a bezel well: its 15.6 mm top housing rests
on the ring of plate between the 14 mm opening and the 19 mm bezel, its narrower
section passes through the opening, and the latches spring out under the plate.
Latch clearance needs no dedicated groove -- the 15.8 mm pocket runs to the plate
underside, leaving 0.9 mm per side against the opening.

The floor is solid and printed with the body. The earlier snap-on cap is gone: a
0.8 mm x 6 mm PLA tongue barely flexes, so it printed either unclosable or loose,
and it cost a second print and a second tolerance. The trade is that the switch
cannot be released afterwards -- nothing reaches its latches from below.
"""

import json
import os
import sys

import bmesh
import bpy
import mathutils

# Make sibling modules importable. tools/blender_exec.py injects this when the
# script arrives over the socket, but a direct `blender --background --python`
# run gets Blender's own sys.path, which does not include this directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import math

import mxgeom
from mxgeom import (
    boolean, cross_sections, export_stl, make_box, make_cylinder, make_loft,
    make_prism_y, mesh_report, point_inside, reset_scene, rounded_rect,
    verify_stl_millimetres,
)

KEYCAP_WIDTH = 18.0

H = {
    # A bezel rises above the plate to shroud the switch, so the body has to be
    # wider than the keycap: the keycap travels 4mm down *inside* the bezel.
    # 0.5mm of clearance per side is what a real keyboard leaves (18mm caps on a
    # 19.05mm pitch). 0.3mm per side was rejected -- printed inner dimensions come
    # out 0.1-0.2mm tight, which would leave the cap rubbing the wall.
    "keycap_width": KEYCAP_WIDTH,
    "bezel_clearance": 0.5,
    "bezel_wall": 1.6,
    "bezel_height": 4.0,          # above the plate's top face

    "plate_thickness": 1.5,
    "opening": 14.0,
    "opening_corner_r": 0.5,
    "pocket": 15.8,
    "pocket_depth": 9.5,
    "lug_protrusion": 5.5,
    "lug_width": 7.0,
    "lug_thickness": 3.0,
    "lug_hole_diameter": 4.0,
    "lug_hole_offset": 2.0,
    # One piece: the floor is printed as part of the body instead of a separate
    # snap-on cap. The cap was replaced because it was the weakest and fiddliest
    # part of the assembly -- a 0.8mm x 6mm PLA tongue barely flexes, so it was
    # either unclosable or loose, and it added a second print and a second
    # tolerance to chase. The cost is that the switch can no longer be released:
    # its latches sit under the plate with no access from below.
    "floor_thickness": 1.2,
    "corner_segments": 8,
    # "tab" (as printed), "gusset", "fin" or "corner" -- see add_lug().
    "lug_style": os.environ.get("HOUSING_LUG_STYLE", "tab"),
    "corner_boss_wall": 1.4,
}


def derive(h):
    """Fill in the dimensions that follow from the others."""
    h = dict(h)
    h["bezel_inner"] = h["keycap_width"] + 2.0 * h["bezel_clearance"]
    h["body_width"] = h["bezel_inner"] + 2.0 * h["bezel_wall"]
    h["body_depth"] = h["body_width"]
    h["wall"] = (h["body_width"] - h["pocket"]) / 2.0
    h["pocket_bottom"] = h["floor_thickness"]
    h["plate_bottom"] = h["pocket_bottom"] + h["pocket_depth"]
    h["plate_top"] = h["plate_bottom"] + h["plate_thickness"]
    h["height"] = h["plate_top"] + h["bezel_height"]
    return h


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def add_lug(body, h):
    """Attach the keyring feature in the style h['lug_style'] asks for.

    All three styles exist because the printed tab came out ragged: it hung
    3mm thick at mid-height with 6.6mm of air under it, so its first layer was
    extruded into nothing and the 4mm hole started in that mess. They differ in
    which direction the hanging load crosses the layer lines, which is the only
    thing that decides how hard the lug can be yanked:

      tab     the original. Flat cantilever, unsupported. Kept for comparison.
      gusset  same tab, 45-degree web beneath. Load still bends a horizontal
              cantilever, so it still peels layers apart at the root -- but the
              root is now much deeper.
      fin     vertical plate, hole bored sideways. The load runs along the layer
              planes instead of across them, which is the strong direction.
      corner  no protrusion; a lobe grown on one body corner, hole vertical.
              Overhang-free and the tidiest, but the lobe bulges diagonally.
    """
    style = h.get("lug_style", "tab")
    overlap = 0.8                    # union overlap; avoids coincident faces
    edge_x = h["body_width"] / 2.0

    if style == "corner":
        # Lobe on the -X/-Y corner. The hole cannot fit *inside* the existing
        # 22.2mm footprint: only 2.26mm of material separates the bezel cavity
        # corner from the body corner along the diagonal, and the hole needs
        # 4.0 plus a wall. So the lobe grows outward on the diagonal instead.
        boss_r = h["lug_hole_diameter"] / 2.0 + h["corner_boss_wall"]
        centre = (-(edge_x - boss_r * 0.35), -(edge_x - boss_r * 0.35))
        boss = make_cylinder(
            "CornerBoss", boss_r, h["height"], (centre[0], centre[1], h["height"] / 2.0),
            64,
        )
        boolean(body, boss, "UNION")
        hole = make_cylinder(
            "LugHole", h["lug_hole_diameter"] / 2.0, h["height"] + 2.0,
            (centre[0], centre[1], h["height"] / 2.0), 64,
        )
        boolean(body, hole, "DIFFERENCE")
        return

    if style == "fin":
        fin_len = h["lug_protrusion"] + overlap
        fin = make_box(
            "Lug",
            (fin_len, h["lug_thickness"], h["height"]),
            (-(edge_x + h["lug_protrusion"] / 2.0 - overlap / 2.0), 0.0,
             h["height"] / 2.0),
        )
        boolean(body, fin, "UNION")
        # Hole bored along Y through the fin's thickness. Centred in height so
        # the material around it is as thick as the fin allows.
        hole = make_cylinder(
            "LugHole", h["lug_hole_diameter"] / 2.0, h["lug_thickness"] + 2.0,
            (-(edge_x + h["lug_hole_offset"]), 0.0, h["height"] / 2.0), 64,
            axis="Y",
        )
        boolean(body, hole, "DIFFERENCE")
        return

    tab_len = h["lug_protrusion"] + overlap
    tab_z = h["height"] / 2.0
    tab = make_box(
        "Lug",
        (tab_len, h["lug_width"], h["lug_thickness"]),
        (-(edge_x + h["lug_protrusion"] / 2.0 - overlap / 2.0), 0.0, tab_z),
    )
    boolean(body, tab, "UNION")

    if style == "gusset":
        # The web runs all the way down to z=0 rather than dropping by
        # lug_protrusion. Two reasons, and the first one bites:
        #
        # The horizontal run is not lug_protrusion. The web spans from the tab's
        # outer tip to inside the body wall, which is protrusion + overlap =
        # 6.3mm, so dropping only 5.5mm gives atan(6.3/5.5) = 48.9 degrees from
        # vertical -- past the 45 degree self-supporting limit, and it sags.
        # Landing on z=0 makes the drop 6.6mm: atan(6.3/6.6) = 43.7 degrees.
        #
        # It also puts the web's lowest vertex at x=-10.3, inside the body's
        # -11.1 edge, so the web emerges from solid material instead of starting
        # as a knife edge hanging in air.
        under_z = tab_z - h["lug_thickness"] / 2.0
        inner_x = -edge_x + overlap
        outer_x = -(edge_x + h["lug_protrusion"])
        web = make_prism_y(
            "LugGusset",
            [(inner_x, under_z), (outer_x, under_z), (inner_x, 0.0)],
            -h["lug_width"] / 2.0, h["lug_width"] / 2.0,
        )
        boolean(body, web, "UNION")
        h["_gusset_overhang_deg"] = round(
            math.degrees(math.atan2(abs(outer_x - inner_x), under_z)), 2
        )

    hole = make_cylinder(
        "LugHole", h["lug_hole_diameter"] / 2.0, h["lug_thickness"] + 2.0,
        (-(edge_x + h["lug_hole_offset"]), 0.0, tab_z), 64,
    )
    boolean(body, hole, "DIFFERENCE")


def build_housing(h):
    if h["bezel_inner"] <= h["keycap_width"]:
        raise ValueError(
            f"bezel_inner {h['bezel_inner']} must exceed the keycap width "
            f"{h['keycap_width']} or the cap cannot travel inside it"
        )
    if h["pocket"] >= h["bezel_inner"]:
        raise ValueError(
            f"pocket {h['pocket']} must be narrower than bezel_inner "
            f"{h['bezel_inner']}, otherwise the plate has no ledge for the switch"
        )

    body = make_box(
        "Switch_Housing",
        (h["body_width"], h["body_depth"], h["height"]),
        (0.0, 0.0, h["height"] / 2.0),
    )

    pocket_top = h["plate_bottom"]
    pocket_bottom = h["pocket_bottom"]

    # Pocket, closed underneath by floor_thickness of solid. State the span and
    # derive the centre rather than nudging the centre and hoping -- getting this
    # wrong silently ate 1mm out of the plate once already.
    pocket = make_box(
        "Pocket",
        (h["pocket"], h["pocket"], pocket_top - pocket_bottom),
        (0.0, 0.0, (pocket_top + pocket_bottom) / 2.0),
    )
    boolean(body, pocket, "DIFFERENCE")

    # Plate opening: rounded-square prism through the plate only. It stops at the
    # plate's top face -- above that the cavity widens into the bezel, and the
    # ring of plate left between the two is what the switch's flange rests on.
    outline = rounded_rect(h["opening"], h["opening"], h["opening_corner_r"],
                          h["corner_segments"])
    opening = make_loft("Opening", outline, pocket_top - 1.0, outline,
                        h["plate_top"] + 0.001)
    boolean(body, opening, "DIFFERENCE")

    # Bezel cavity: the well the switch sits in and the keycap descends into.
    bezel = make_box(
        "BezelCavity",
        (h["bezel_inner"], h["bezel_inner"], h["bezel_height"] + 2.0),
        (0.0, 0.0, h["plate_top"] + (h["bezel_height"] + 2.0) / 2.0),
    )
    boolean(body, bezel, "DIFFERENCE")

    add_lug(body, h)

    body.name = "Switch_Housing"
    body.data.name = "Switch_Housing"
    return body


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

def measure_plate_thickness(obj, h):
    """Ray-cast down through the plate where it actually spans the pocket.

    The plate is only 1.5mm thick in the annulus between the opening (half-width
    7.0) and the pocket (half-width 7.9); outside that it is solid wall all the
    way down, so probing the corners measures the wall, not the plate.
    """
    probe = (h["opening"] / 2.0 + h["pocket"] / 2.0) / 2.0      # 7.45
    results = {"probe_offset_mm": round(probe, 3)}
    for label, x, y in (("minus_x", -probe, 0.0), ("plus_x", probe, 0.0),
                        ("minus_y", 0.0, -probe), ("plus_y", 0.0, probe)):
        # Start above the bezel; the first hit down this line is the plate.
        origin = mathutils.Vector((x, y, h["height"] + 5.0))
        direction = mathutils.Vector((0.0, 0.0, -1.0))
        hits = []
        cursor = origin.copy()
        for _ in range(6):
            hit, location, _n, _i = obj.ray_cast(cursor, direction)
            if not hit:
                break
            hits.append(round(location.z, 4))
            cursor = location + direction * 1e-4
        results[f"{label}_hits"] = hits
        if len(hits) >= 2:
            results[label] = round(hits[0] - hits[1], 4)
    return results


def _span(obj, z, axis, limit=12.0, step=0.05):
    """Width of the air gap through the centre at height z."""
    reach = 0.0
    value = 0.0
    while value <= limit:
        point = (value, 0.0, z) if axis == "x" else (0.0, value, z)
        if point_inside(obj, point):
            break
        reach = value
        value += step
    return round(reach * 2.0, 3)


def _span_at(obj, x, z, limit=6.0, step=0.05):
    """Air span along Y through (x, *, z)."""
    reach = 0.0
    value = 0.0
    while value <= limit:
        if point_inside(obj, (x, value, z)):
            break
        reach = value
        value += step
    return round(reach * 2.0, 3)


def _span_through(obj, point, axis, limit=6.0, step=0.05):
    """Air span through `point` along `axis`, measured both ways from it.

    The lug hole's axis moves with lug_style, so a probe hard-coded to Y from
    the origin measures the hole in one style and thin air in another -- and
    reports a number either way.
    """
    index = {"x": 0, "y": 1, "z": 2}[axis]
    total = 0.0
    for sign in (1.0, -1.0):
        value = 0.0
        while value <= limit:
            probe = list(point)
            probe[index] += sign * value
            if point_inside(obj, tuple(probe)):
                break
            total = total + step if value > 0.0 else total
            value += step
    return round(total, 3)


def lug_hole_probe(obj, h):
    """Measure the keyring hole across its own axis, whatever style built it."""
    style = h.get("lug_style", "tab")
    edge_x = h["body_width"] / 2.0
    if style == "corner":
        boss_r = h["lug_hole_diameter"] / 2.0 + h["corner_boss_wall"]
        offset = edge_x - boss_r * 0.35
        return {"axis": "Z (vertical)", "measured_across": "x",
                "diameter_mm": _span_through(obj, (-offset, -offset, h["height"] / 2.0), "x")}
    point = (-(edge_x + h["lug_hole_offset"]), 0.0, h["height"] / 2.0)
    if style == "fin":
        return {"axis": "Y (horizontal)", "measured_across": "z",
                "diameter_mm": _span_through(obj, point, "z")}
    return {"axis": "Z (vertical)", "measured_across": "y",
            "diameter_mm": _span_through(obj, point, "y")}


def housing_report(obj, h):
    mid_plate = h["plate_top"] - h["plate_thickness"] / 2.0
    report = {
        "dimensions_mm": [round(v, 4) for v in obj.dimensions],
        "mesh": mesh_report(obj),
        "plate_thickness_probe": measure_plate_thickness(obj, h),
        "opening_probe": {
            "x_span_mm": _span(obj, mid_plate, "x"),
            "y_span_mm": _span(obj, mid_plate, "y"),
        },
        "pocket_probe": {
            "x_span_mm": _span(obj, h["pocket_depth"] / 2.0, "x"),
            "y_span_mm": _span(obj, h["pocket_depth"] / 2.0, "y"),
        },
        "latch_clearance_mm": round((h["pocket"] - h["opening"]) / 2.0, 3),
        # The floor replaced a separate cap, so prove it is really solid rather
        # than assuming the boolean stopped where it was told.
        "floor_probe": {
            "solid_at_centre": point_inside(obj, (0.0, 0.0, h["floor_thickness"] / 2.0)),
            "solid_off_centre": point_inside(obj, (5.0, 5.0, h["floor_thickness"] / 2.0)),
            "open_above_floor": not point_inside(
                obj, (0.0, 0.0, h["pocket_bottom"] + 2.0)),
            "thickness_mm": h["floor_thickness"],
        },
        "bezel_probe": {
            "inner_span_mm": _span(obj, h["plate_top"] + h["bezel_height"] / 2.0, "x"),
            "keycap_clearance_per_side_mm": round(
                (h["bezel_inner"] - h["keycap_width"]) / 2.0, 3),
            "plate_ledge_width_mm": round((h["bezel_inner"] - h["opening"]) / 2.0, 3),
            "bezel_height_mm": h["bezel_height"],
        },
        "lug_style": h.get("lug_style", "tab"),
        # Measured from vertical. Above ~45 degrees a slope stops being
        # self-supporting and sags, so this is the number that decides whether
        # the fix actually fixes anything.
        "gusset_overhang_deg": h.get("_gusset_overhang_deg"),
        "lug_hole_probe": lug_hole_probe(obj, h),
    }
    mesh = report["mesh"]
    floor = report["floor_probe"]
    if not mesh["watertight"]:
        report["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        report["VERDICT"] = "NOT PRINTABLE - normals point inward"
    elif not (floor["solid_at_centre"] and floor["solid_off_centre"]):
        report["VERDICT"] = "NOT PRINTABLE - floor is not solid"
    elif not floor["open_above_floor"]:
        report["VERDICT"] = "NOT PRINTABLE - pocket is filled, the switch cannot enter"
    else:
        report["VERDICT"] = "printable"
    return report


# --------------------------------------------------------------------------- #

def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()

    h = derive(H)
    housing = build_housing(h)
    report = {"parameters": h, "housing": housing_report(housing, h)}

    # The as-printed "tab" keeps the plain name so the sliced plate and the
    # review tools that point at it keep working; variants get a suffix.
    suffix = "" if h["lug_style"] == "tab" else f"_{h['lug_style']}"
    stl = os.path.join(project, "models", f"switch_housing{suffix}.stl")
    export_stl(housing, stl)
    report["housing"]["stl"] = verify_stl_millimetres(stl)

    sections = cross_sections(
        housing, h["body_width"] / 2.0 + 0.25,
        heights=(h["floor_thickness"] / 2.0, h["pocket_bottom"] + 2.0,
                 h["plate_bottom"] + h["plate_thickness"] / 2.0,
                 h["plate_top"] + h["bezel_height"] / 2.0),
    )

    print("HOUSING_REPORT_START")
    print(json.dumps(report, indent=2))
    print("HOUSING_REPORT_END")

    print("\nCROSS SECTIONS  ('#' = plastic, '.' = air, 0.5mm grid, +Y up, +X right)")
    for label, rows in sections.items():
        print(f"\n--- {label} mm ---")
        for row in rows:
            print("   " + row)


main()
