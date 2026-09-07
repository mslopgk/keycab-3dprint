"""Keycap variant with the church-wave logo raised on its top.

Spec: docs/superpowers/specs/2026-08-10-keycap-logo-relief-design.md

    powershell -File tools\\blender_server.ps1 start
    python tools\\blender_exec.py models\\keycap_logo.py

Separate from models/keycap.py on purpose: the plain keycap's STL hashes are the
refactor regression gate in the keychain plan, so its outputs must not move.

Relief is cut from between two copies of the dish cylinder rather than extruded
to a fixed height. That makes it uniform: the keycap's top surface *is* the dish
cylinder's lower boundary, so a second copy raised by relief_mm gives a top
surface parallel to it. A flat-topped logo would instead stand 0.852mm proud at
the centre and only 0.111mm at y=+/-6 -- below one layer -- because the dish
curves in Y only.
"""

import json
import os
import sys

import bpy

# Make sibling modules importable. tools/blender_exec.py injects this when the
# script arrives over the socket, but a direct `blender --background --python`
# run gets Blender's own sys.path, which does not include this directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import keycap
import logo
import mxgeom
from mxgeom import (
    boolean, cross_sections, export_stl, make_box, make_cylinder, mesh_report,
    reset_scene, verify_stl_millimetres,
)

SVG = r"C:\Users\user\Documents\카카오톡 받은 파일\church-wave-logo-03-minimal-line.svg"

L = {
    "svg": SVG,
    "diameter_mm": 12.0,
    # 0.15 printed with breaks in the strokes, so back up to 0.30. Filling the
    # wave (below) is what makes that affordable: the narrow gaps that merged at
    # 0.25 were inside the wave, and a solid wave has none.
    "dilate_mm": 0.30,
    # Area-rank 1 cutter is the wave; not subtracting it leaves the wave as one
    # solid mass instead of thin outline strokes. Rank 0 carves the cross and the
    # ring, so it must stay a cutter -- filling it instead loses the cross.
    "fill_regions": (1,),
    # The logo top is a single flat plane this far above the keycap rim, so the
    # relief height varies with the dish and the logo reads flat from the side.
    "top_above_rim_mm": 1.0,
    # The XY boundary is limited by the 0.4mm nozzle, not by the raster, so
    # 0.02mm only cost build time. 0.04mm keeps facets at a tenth of the nozzle.
    "pixel_mm": 0.04,
}

# Keycap overrides for this variant. Kept here rather than in keycap.py so the
# plain keycap's STL hashes stay valid as the refactor regression gate.
KEYCAP_OVERRIDES = {
    "ceiling": "flat",      # right-side-up printing needs a bridgeable roof
    "height": 11.0,         # taller body; the 13.6 x 13.2 plateau is unchanged
    # The printed socket walls broke when the cap was pulled off the switch.
    # At the 5.5mm stem the material left beyond a cross arm tip was
    # (5.5 - 4.1)/2 = 0.70mm, which is under the ~0.84mm two 0.4mm perimeters
    # need, so the slicer filled it with a single wall plus gap fill -- weak in
    # every direction. A moulded keycap survives 0.70mm because the material is
    # isotropic; an FDM one does not. 6.6mm leaves 1.25mm, enough for three
    # perimeters. Raising it further risks fouling the switch's top housing.
    "stem_diameter": 6.6,
    # 6.6 stopped the walls breaking but fouled the switch's top housing, so the
    # keycap no longer sprang back. Only the bottom few millimetres of the boss
    # actually enter the switch, so the boss tapers: 6.6 where the wall has to
    # carry load, narrowing to 5.8 at the tip where it has to clear.
    #
    # 5.8 is the safe tip: a gauge of 5.8/6.0/6.2/6.4/6.6 was printed and exactly
    # one diameter seated, and 5.8 is the smallest of the five -- whichever one it
    # was, 5.8 clears at least as well.
    "stem_tip_diameter": 5.8,
    # v2 tapered to full diameter by z=3.0 and still caught on about one press
    # in five. The arithmetic says why. Key travel is 4.0mm, and the boss is not
    # level with the bore at rest either: the MX stem stands ~3.6mm proud while
    # cross_depth is 4.0, so the boss already sits ~0.4mm inside the bore before
    # the key is touched. Bottomed out, 4.4mm of boss is in the bore -- and
    # 3.0-4.4 was at the full 6.6. The interference is slight, which is why it
    # only caught sometimes and why rocking the cap freed it.
    #
    # Free to fix: the cross socket is cross_depth = 4.0 deep, so the boss above
    # z=4.0 is a solid rod. Holding 5.8 up to 5.0 lengthens no thin wall -- the
    # 0.85mm wall still spans only z=0..4.0, exactly as in v2, which did stop the
    # breaking.
    # 5.0mm of boss is in the bore at full press once cross_depth is 4.6 (a
    # deeper slot lets the cap seat lower, so the boss goes further in), plus
    # 0.6mm margin. Raising cross_depth without raising this would have put the
    # full 6.6 diameter back inside the bore and undone the v3 fix.
    "stem_clear_z": 5.6,
    "stem_taper_z": 6.5,        # flare 5.8 -> 6.6 over 1.5mm
    # A square rim at the bottom of the boss is what a bore lip catches on.
    "stem_lead_in": 0.4,
    "stem_lead_in_diameter": 5.2,
    # Ribs bond the boss to the side walls, but anything below the full-press
    # line can foul the switch's top housing. 3.6 sat under 4.4; 4.8 clears it
    # and still leaves 3.4mm of rib height (up to the 8.2 ceiling limit).
    "rib_bottom_z": 4.8,

    # --- v4: the cross slot itself, which v3 never touched ---------------- #
    # v3 fixed the boss's OUTER diameter, and the cap stopped catching on the
    # switch bore. Three symptoms remained, and they share one cause.
    #
    # The switch is a KTT MX clone (15 x 15 x 18mm, ABS). The slot was 1.35mm --
    # the nominal thickness of an MX stem's cross, so nominal clearance is zero.
    # FDM prints inner features 0.1-0.2mm undersized, so the real slot was
    # ~1.15-1.25mm being forced onto a 1.35mm stem. That gives, in order:
    #   - it goes on very hard
    #   - the tightest of the four arms gets shaved, leaving a gouge
    #   - that gouge is where the socket splits when the cap is pulled off
    #   - and friction stops it before it seats, so the switch sits proud
    # Commercial keycaps use 1.40-1.50; 1.45 lands mid-range with FDM shrink
    # accounted for. The wall at an arm tip is set by cross_arm_length, not by
    # the slot width, so this does not thin the 0.85mm wall.
    "cross_arm_width": 1.45,
    # "쪼금 덜 꽂힘": the stem may also be bottoming out. 4.6 gives 0.6mm of
    # spare depth. Free on strength -- z=4.0..4.6 is still inside the Ø5.8
    # section, so no thin wall gets longer than the taper already made it.
    "cross_depth": 4.6,
    # Chamfered slot mouth so the stem centres instead of shaving a wall.
    "cross_lead_in": 0.3,
}

# Minimum material beyond a cross arm tip, at the boss's full diameter. Two
# 0.4mm perimeters need ~0.84mm; the tapered tip is thinner by design.
MIN_SOCKET_WALL_MM = 1.0

# Cherry MX facts the boss geometry has to satisfy, not free parameters.
MX_TRAVEL_MM = 4.0        # full stroke, rest to bottom-out
MX_STEM_PROUD_MM = 3.6    # how far the switch's cross stands above its housing

REPORT = {}


def add_logo(cap, p, l, rim_z):
    """Union a flat-topped logo onto the keycap's dished top.

    The bottom of the logo follows the dish, because it is cut by the same
    cylinder the dish was cut with. The top is a single horizontal plane, so the
    wall height varies -- tall where the dish is deep at the centre, short near
    the front and back where the dish rises. That is what makes the logo read as
    flat from the side while the hand-contact surface stays curved.
    """
    height = p["height"]
    radius = keycap.dish_radius(p["top_depth"], p["dish_depth"])
    dish_z = height + radius - p["dish_depth"]
    dish_len = p["base_width"] * 3.0
    top_z = rim_z + l["top_above_rim_mm"]

    prism, stats = logo.build_logo_prism(
        l["svg"], l["diameter_mm"], l["dilate_mm"], l["pixel_mm"],
        z0=height - p["dish_depth"] - 2.0,      # well below the dish surface
        z1=top_z + 2.0,                          # well above the flat top
        fill_regions=l["fill_regions"],
    )
    REPORT["logo"] = stats
    REPORT["logo"]["flat_top_z"] = round(top_z, 4)

    # Keep only the part of the prism above the keycap's top surface ...
    lower = make_cylinder("DishLower", radius, dish_len, (0.0, 0.0, dish_z), 256, axis="X")
    boolean(prism, lower, "INTERSECT")
    # ... and cap it with one horizontal plane.
    span = p["base_width"] * 3.0
    lid = make_box("LogoLid", (span, span, span), (0.0, 0.0, top_z + span / 2.0))
    boolean(prism, lid, "DIFFERENCE")

    REPORT["logo"]["trimmed_dimensions_mm"] = [round(v, 4) for v in prism.dimensions]
    REPORT["logo"]["trimmed_mesh"] = mesh_report(prism)

    boolean(cap, prism, "UNION")
    return cap


def measure_relief(cap, p, l):
    """Ray-cast around the logo. The top must be PLANAR and the wall tall enough.

    Uniform relief is no longer the goal -- the top is deliberately one plane and
    the wall height varies with the dish. So the checks flip: every sample that
    lands on logo material must report the same top_z, and the thinnest wall must
    still clear the layer height comfortably.
    """
    import mathutils

    height = p["height"]
    radius = keycap.dish_radius(p["top_depth"], p["dish_depth"])
    dish_z = height + radius - p["dish_depth"]

    def dish_surface_z(y):
        return dish_z - (radius ** 2 - y * y) ** 0.5

    down = mathutils.Vector((0.0, 0.0, -1.0))
    results = {}
    ring = l["diameter_mm"] / 2.0 - 0.35      # just inside the outer ring stroke
    probes = []
    for label, x, y in (
        ("ring_+x", ring, 0.0), ("ring_-x", -ring, 0.0),
        ("ring_+y", 0.0, ring), ("ring_-y", 0.0, -ring),
        ("ring_+x+y", ring * 0.707, ring * 0.707),
        ("ring_-x-y", -ring * 0.707, -ring * 0.707),
        ("cross_stem", 0.30, 1.5), ("centre", 0.0, 0.0),
    ):
        probes.append((label, x, y))

    for label, x, y in probes:
        hit, location, _n, _i = cap.ray_cast(
            mathutils.Vector((x, y, height + 8.0)), down
        )
        if not hit:
            results[label] = None
            continue
        top = location.z
        expected_surface = dish_surface_z(y)
        results[label] = {
            "top_z": round(top, 4),
            "dish_surface_z": round(expected_surface, 4),
            "relief_mm": round(top - expected_surface, 4),
        }
    return results


def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()

    p = dict(keycap.P)
    p.update(KEYCAP_OVERRIDES)

    socket_wall = (p["stem_diameter"] - p["cross_arm_length"]) / 2.0
    tip_wall = (p.get("stem_tip_diameter", p["stem_diameter"])
                - p["cross_arm_length"]) / 2.0
    REPORT["socket_wall_mm"] = round(socket_wall, 4)
    REPORT["socket_wall_at_tip_mm"] = round(tip_wall, 4)
    REPORT["stem_taper_z"] = p.get("stem_taper_z", 0.0)
    if socket_wall < MIN_SOCKET_WALL_MM:
        raise ValueError(
            f"socket wall {socket_wall:.2f}mm is below {MIN_SOCKET_WALL_MM}mm: "
            f"stem_diameter {p['stem_diameter']} minus cross_arm_length "
            f"{p['cross_arm_length']} leaves too little for two perimeters, and "
            "the walls break when the cap is pulled off the switch"
        )

    # The v2 keycap passed every mesh check and still bound on the switch,
    # because nothing checked the boss against the key's travel. This does.
    engaged = MX_TRAVEL_MM + (p["cross_depth"] - MX_STEM_PROUD_MM)
    REPORT["boss_in_bore_at_full_press_mm"] = round(engaged, 4)
    clear_z = p.get("stem_clear_z", 0.0)
    if p.get("stem_taper_z", 0.0) > 0.0 and clear_z < engaged:
        raise ValueError(
            f"stem_clear_z {clear_z}mm is under {engaged:.2f}mm of boss inside "
            f"the switch bore at full press ({MX_TRAVEL_MM}mm travel plus "
            f"{p['cross_depth'] - MX_STEM_PROUD_MM:.2f}mm already engaged at "
            "rest), so the full diameter enters the bore and the cap sticks"
        )

    cap = keycap.build_keycap(p)
    rim_z = max(v.co.z for v in cap.data.vertices)
    REPORT["keycap_before_logo"] = {
        "dimensions_mm": [round(v, 4) for v in cap.dimensions],
        "rim_z": round(rim_z, 4),
        "mesh": mesh_report(cap),
    }

    add_logo(cap, p, L, rim_z)
    cap.name = "Keycap_1u_R3_Logo"
    cap.data.name = "Keycap_1u_R3_Logo"

    REPORT["parameters"] = {"keycap": p, "logo": L}
    REPORT["dimensions_mm"] = [round(v, 4) for v in cap.dimensions]
    REPORT["mesh"] = mesh_report(cap)
    REPORT["relief_probe"] = measure_relief(cap, p, L)

    on_logo = [
        v for v in REPORT["relief_probe"].values()
        if isinstance(v, dict) and v["relief_mm"] > 0.15
    ]
    expected_top = rim_z + L["top_above_rim_mm"]
    if on_logo:
        tops = [v["top_z"] for v in on_logo]
        reliefs = [v["relief_mm"] for v in on_logo]
        REPORT["relief_summary"] = {
            "samples_on_logo": len(on_logo),
            "expected_flat_top_z": round(expected_top, 4),
            "top_z_min": round(min(tops), 4),
            "top_z_max": round(max(tops), 4),
            "top_planarity_mm": round(max(tops) - min(tops), 4),
            "wall_min_mm": round(min(reliefs), 4),
            "wall_max_mm": round(max(reliefs), 4),
        }

    mesh = REPORT["mesh"]
    summary = REPORT.get("relief_summary", {})
    planar = summary.get("top_planarity_mm", 9.9) <= 0.02
    on_plane = abs(summary.get("top_z_max", 0.0) - expected_top) <= 0.02
    # Thinnest wall must be several layers tall. 0.5mm clears 0.12mm layers 4x.
    tall_enough = summary.get("wall_min_mm", 0.0) >= 0.5

    if not mesh["watertight"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - normals point inward"
    elif not (planar and on_plane):
        REPORT["VERDICT"] = "NOT PRINTABLE - logo top is not one flat plane"
    elif not tall_enough:
        REPORT["VERDICT"] = "NOT PRINTABLE - thinnest logo wall under 0.5mm"
    else:
        REPORT["VERDICT"] = "printable"

    stl = os.path.join(project, "models", "keycap_1u_r3_logo.stl")
    export_stl(cap, stl)
    REPORT["stl"] = verify_stl_millimetres(stl)

    blend = os.path.join(project, "models", "keycap_1u_r3_logo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    REPORT["blend"] = blend

    print("LOGO_KEYCAP_REPORT_START")
    print(json.dumps(REPORT, indent=2, ensure_ascii=False))
    print("LOGO_KEYCAP_REPORT_END")

    # Slice through the cross socket so the wall left beyond each arm tip can be
    # counted, not just computed. This is the section that broke in the hand.
    socket = cross_sections(cap, 5.0, heights=(2.0,), step=0.1)
    print("\nCROSS SOCKET AT z = 2.0 mm ('#' = plastic, 0.1mm grid, +X right)")
    for label, rows in socket.items():
        print(f"\n--- {label} mm ---")
        for row in rows:
            print("   " + row)

    sections = cross_sections(cap, L["diameter_mm"] / 2.0 + 1.0,
                              heights=(p["height"] + 0.25,), step=0.25)
    print("\nLOGO AT z = height + 0.25 ('#' = plastic)")
    for label, rows in sections.items():
        print(f"\n--- {label} mm ---")
        for row in rows:
            print("   " + row)


# "__blender_mcp__" is the socket server's exec namespace; "__main__" is a direct
# `blender --background --python` run, which this script needs because a 0.02mm
# raster takes longer than the server's 175s per-command timeout.
if __name__ in ("__blender_mcp__", "__main__"):
    main()
