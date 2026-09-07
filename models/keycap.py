"""Parametric Cherry MX-compatible 1u keycap, built for FDM/resin printing.

Run through the headless Blender MCP server:

    powershell -File tools\\blender_server.ps1 start
    python tools\\blender_exec.py models\\keycap.py

Everything is modelled at 1 Blender unit == 1 mm, and the STL is written with
use_scene_unit=False / global_scale=1.0 so the numbers in the file are literal
millimetres -- which is what every slicer assumes.

Construction order matters for boolean robustness:
  1. shell   = outer loft, top rim bevelled, minus the dish cylinder
  2. cavity  = inner loft minus the same dish cylinder dropped by top_thickness,
               so the ceiling runs parallel to the dish and the top wall is a
               constant thickness instead of thick at the edge and thin in the middle
  3. ribs    = fins intersected with a slightly *inflated* cavity, so they end
               inside the wall rather than exactly on it (coincident faces are
               what make exact booleans produce garbage)
  4. shell  -= cavity, shell += stem + ribs, shell -= MX cross
"""

import json
import math
import os

import bmesh
import bpy
import mathutils

import mxgeom
from mxgeom import (
    bevel_top_rim, boolean, cross_sections, duplicate, export_stl, make_box,
    make_cone, make_cylinder, make_loft, make_revolve, mesh_report, point_inside,
    reset_scene, rounded_rect, verify_stl_millimetres,
)

# --------------------------------------------------------------------------- #
# Parameters (millimetres / degrees)
# --------------------------------------------------------------------------- #

P = {
    # Footprint. 1u spacing is 19.05mm; the cap itself is undersized so
    # neighbouring caps do not rub.
    "base_width": 18.0,
    "base_depth": 18.0,
    "base_corner_r": 1.0,

    # Top plateau (Cherry-like R3, no front-to-back tilt).
    "top_width": 13.6,
    "top_depth": 13.2,
    "top_corner_r": 1.8,

    "height": 8.6,          # bottom rim to the top surface before dishing
    "dish_depth": 0.9,      # sagitta of the cylindrical dish at centre

    "wall": 1.35,           # side wall thickness
    "top_thickness": 1.5,   # roof thickness, held constant under the dish

    "rim_bevel": 0.4,
    "rim_bevel_segments": 3,
    "corner_segments": 8,   # arc subdivisions per rounded corner

    # Cherry MX stem socket. Cross slot is deliberately 1.35 wide: 1.30 grips
    # hard but splits brittle filament, 1.40 goes loose.
    "stem_diameter": 5.5,
    "stem_segments": 48,
    "cross_arm_length": 4.1,
    "cross_arm_width": 1.35,
    "cross_depth": 4.0,

    # Fins bonding the stem to the side walls. They start above the switch's
    # top housing so they cannot collide when the key bottoms out.
    "rib_count": 4,
    "rib_thickness": 1.0,
    "rib_bottom_z": 3.6,
    "rib_wall_bite": 0.35,  # how far ribs push into the wall
    # Ribs must stop clear of the cavity ceiling. If a rib's trimmed top lands
    # exactly *on* that surface the two coincident faces yield 4-valence edges
    # and open boundaries -- i.e. a mesh no slicer will accept.
    "rib_ceiling_gap": 0.4,
}

REPORT = {}


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def cross_outline(arm_length, arm_width):
    """Plus-shaped outline, 12 points, counter-clockwise, centred on origin.

    Lets the cross slot be lofted between two sizes, which a pair of boxes
    cannot do -- boxes give a prismatic slot with a square mouth.
    """
    half_l, half_w = arm_length / 2.0, arm_width / 2.0
    return [
        (half_l, half_w), (half_w, half_w), (half_w, half_l),
        (-half_w, half_l), (-half_w, half_w), (-half_l, half_w),
        (-half_l, -half_w), (-half_w, -half_w), (-half_w, -half_l),
        (half_w, -half_l), (half_w, -half_w), (half_l, -half_w),
    ]


def dish_radius(chord, sagitta):
    """Radius of a circle whose chord `chord` sits `sagitta` below the arc."""
    return (chord * chord) / (8.0 * sagitta) + sagitta / 2.0


def build_keycap(p):
    height = p["height"]
    segments = p["corner_segments"]

    outer_bottom = rounded_rect(p["base_width"], p["base_depth"], p["base_corner_r"], segments)
    outer_top = rounded_rect(p["top_width"], p["top_depth"], p["top_corner_r"], segments)
    shell = make_loft("Keycap", outer_bottom, 0.0, outer_top, height)
    REPORT["rim_edges_bevelled"] = bevel_top_rim(
        shell, height, p["rim_bevel"], p["rim_bevel_segments"]
    )

    # Cylindrical dish: axis along X so the scoop runs front-to-back.
    radius = dish_radius(p["top_depth"], p["dish_depth"])
    REPORT["dish_radius_mm"] = round(radius, 3)
    dish_len = p["base_width"] * 3.0
    dish_z = height + radius - p["dish_depth"]
    dish = make_cylinder("DishCut", radius, dish_len, (0.0, 0.0, dish_z), 128, axis="X")
    boolean(shell, dish, "DIFFERENCE")

    # Cavity, ceiling parallel to the dish so the roof thickness is constant.
    wall = p["wall"]
    inner_bottom = rounded_rect(
        p["base_width"] - 2 * wall, p["base_depth"] - 2 * wall,
        max(p["base_corner_r"] - wall, 0.2), segments,
    )
    inner_top = rounded_rect(
        p["top_width"] - 2 * wall, p["top_depth"] - 2 * wall,
        max(p["top_corner_r"] - wall, 0.2), segments,
    )
    # Starts below z=0 so the underside is genuinely open, not skinned.
    cavity = make_loft("Cavity", inner_bottom, -1.0, inner_top, height + 2.0)
    if p.get("ceiling", "dish_parallel") == "flat":
        # Flat ceiling: needed when the part prints right side up, because a
        # dish-parallel ceiling faces downwards at ~6 degrees from horizontal and
        # would need support inside the cavity. Flat makes it a ~15mm bridge
        # instead. The roof is then thicker at the edge than at the centre.
        ceiling_z = height - p["top_thickness"] - p["dish_depth"]
        cap = make_box(
            "CavityCap",
            (p["base_width"] * 2.0, p["base_depth"] * 2.0, height + 4.0),
            (0.0, 0.0, ceiling_z + (height + 4.0) / 2.0),
        )
        boolean(cavity, cap, "DIFFERENCE")
        REPORT["ceiling"] = {"kind": "flat", "z": round(ceiling_z, 4)}
    else:
        dish_inner = make_cylinder(
            "DishCutInner", radius, dish_len,
            (0.0, 0.0, dish_z - p["top_thickness"]), 128, axis="X",
        )
        boolean(cavity, dish_inner, "DIFFERENCE")
        REPORT["ceiling"] = {"kind": "dish_parallel"}

    # Slightly larger cavity used only to trim the ribs, so ribs terminate
    # *inside* the wall instead of flush against it.
    bite = p["rib_wall_bite"]
    rib_limit = make_loft(
        "RibLimit",
        rounded_rect(p["base_width"] - 2 * (wall - bite), p["base_depth"] - 2 * (wall - bite),
                     max(p["base_corner_r"] - wall + bite, 0.2), segments),
        -1.0,
        rounded_rect(p["top_width"] - 2 * (wall - bite), p["top_depth"] - 2 * (wall - bite),
                     max(p["top_corner_r"] - wall + bite, 0.2), segments),
        height + 2.0,
    )
    dish_rib = make_cylinder(
        "DishCutRib", radius, dish_len,
        (0.0, 0.0, dish_z - p["top_thickness"]), 128, axis="X",
    )
    boolean(rib_limit, dish_rib, "DIFFERENCE")

    stem_top = height - p["top_thickness"]

    ribs = None
    span = p["base_width"]  # generous: trimmed by rib_limit below
    # Lowest point of the cavity ceiling is at the dish centre; stay under it.
    ceiling_min_z = height - p["top_thickness"] - p["dish_depth"]
    rib_z0 = p["rib_bottom_z"]
    rib_z1 = ceiling_min_z - p["rib_ceiling_gap"]
    REPORT["rib_top_z"] = round(rib_z1, 4)
    REPORT["cavity_ceiling_min_z"] = round(ceiling_min_z, 4)
    for index in range(p["rib_count"]):
        along_x = index % 2 == 0
        sign = 1.0 if index < 2 else -1.0
        length = span
        if along_x:
            size = (length, p["rib_thickness"], rib_z1 - rib_z0)
            location = (sign * length / 2.0, 0.0, (rib_z0 + rib_z1) / 2.0)
        else:
            size = (p["rib_thickness"], length, rib_z1 - rib_z0)
            location = (0.0, sign * length / 2.0, (rib_z0 + rib_z1) / 2.0)
        rib = make_box(f"Rib{index}", size, location)
        if ribs is None:
            ribs = rib
        else:
            boolean(ribs, rib, "UNION")
    boolean(ribs, rib_limit, "INTERSECT")

    # The socket wall wants a wide boss for strength, but the part of the boss
    # that descends into the switch has to clear its bore. Those are different
    # heights, so the boss is a stepped profile rather than one diameter:
    #
    #   stem_top  +-----+   stem_diameter -- carries the pull-off load
    #             |     |
    #   taper_z   +-\   |   flare
    #   clear_z   +--+  |   stem_tip_diameter -- inside the switch bore
    #             |  |  |
    #   lead_in   +-/   |   chamfer, so the rim cannot catch on the bore lip
    #        z=0  +--+
    #
    # clear_z must exceed key travel plus the depth the boss already sits at
    # rest, or the full diameter enters the bore at the bottom of the stroke.
    # Costs nothing: the cross socket is only cross_depth deep, so everything
    # above that is solid rod and its outer diameter does not set a wall.
    taper_z = p.get("stem_taper_z", 0.0)
    if taper_z > 0.0:
        tip_r = p["stem_tip_diameter"] / 2.0
        full_r = p["stem_diameter"] / 2.0
        clear_z = p.get("stem_clear_z", 0.0)
        lead = p.get("stem_lead_in", 0.0)

        profile = []
        if lead > 0.0:
            profile.append((p["stem_lead_in_diameter"] / 2.0, 0.0))
            profile.append((tip_r, lead))
        else:
            profile.append((tip_r, 0.0))
        if clear_z > lead:
            profile.append((tip_r, clear_z))
        profile.append((full_r, taper_z))
        profile.append((full_r, stem_top))
        stem = make_revolve("Stem", profile, p["stem_segments"])
        REPORT["stem_profile"] = [[round(r * 2.0, 3), round(z, 3)] for r, z in profile]
    else:
        stem = make_cylinder(
            "Stem", p["stem_diameter"] / 2.0, stem_top,
            (0.0, 0.0, stem_top / 2.0), p["stem_segments"],
        )

    boolean(shell, cavity, "DIFFERENCE")
    boolean(shell, stem, "UNION")
    boolean(shell, ribs, "UNION")

    # MX cross socket, cut last so it stays open through the stem.
    arm_l, arm_w, depth = p["cross_arm_length"], p["cross_arm_width"], p["cross_depth"]
    lead = p.get("cross_lead_in", 0.0)
    z0, z1 = -0.5, depth

    if lead <= 0.0:
        cross = make_box("CrossA", (arm_l, arm_w, z1 - z0), (0.0, 0.0, (z0 + z1) / 2.0))
        cross_b = make_box("CrossB", (arm_w, arm_l, z1 - z0), (0.0, 0.0, (z0 + z1) / 2.0))
        boolean(cross, cross_b, "UNION")
        boolean(shell, cross, "DIFFERENCE")
    else:
        # A square-edged slot mouth has to shave its way onto the stem, and the
        # tightest of the four arms is the one that gets gouged -- which then
        # becomes the crack that splits the socket when the cap is pulled off.
        # A chamfered mouth lets the stem centre itself instead.
        #
        # Cut as three separate DIFFERENCEs rather than unioning the cutters
        # first: stacked cutters meet on coincident faces, and that is what
        # makes an exact boolean produce garbage. Subtracting in turn cannot.
        wide = cross_outline(arm_l + 2.0 * lead, arm_w + 2.0 * lead)
        narrow = cross_outline(arm_l, arm_w)
        for name, bottom, bottom_z, top, top_z in (
            ("CrossBelow", wide, z0, wide, 0.01),
            ("CrossMouth", wide, 0.0, narrow, lead),
            ("CrossMain", narrow, lead - 0.01, narrow, z1),
        ):
            cutter = make_loft(name, bottom, bottom_z, top, top_z)
            boolean(shell, cutter, "DIFFERENCE")
        REPORT["cross_mouth"] = {
            "lead_in_mm": lead,
            "mouth_arm_width_mm": round(arm_w + 2.0 * lead, 3),
            "slot_arm_width_mm": arm_w,
            "depth_mm": depth,
        }

    shell.name = "Keycap_1u_R3"
    shell.data.name = "Keycap_1u_R3"
    return shell


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

def measure_top_thickness(obj, p):
    """Ray-cast down through the roof to confirm its thickness.

    Probe points deliberately avoid the stem (radius 2.75) and the rib bands
    (|x| < 0.5 and |y| < 0.5): a ray down the centre line passes through the
    solid stem and reports roof+stem, not the roof.
    """
    matrix_inv = obj.matrix_world.inverted()
    results = {}
    probes = (
        ("back_right", 3.5, 3.5),
        ("front_left", -4.0, -2.5),
        ("near_edge", 0.0, -p["top_depth"] / 2.0 + 1.5),
    )
    for label, x, y in probes:
        origin = matrix_inv @ mathutils.Vector((x, y, p["height"] + 5.0))
        direction = mathutils.Vector((0.0, 0.0, -1.0))
        hits = []
        cursor = origin.copy()
        for _ in range(6):
            hit, location, _normal, _index = obj.ray_cast(cursor, direction)
            if not hit:
                break
            hits.append(round(location.z, 4))
            cursor = location + direction * 1e-4
        results[label] = hits
        if len(hits) >= 2:
            results[f"{label}_thickness_mm"] = round(hits[0] - hits[1], 4)
    return results


def render_views(obj, out_dir, size=760):
    """Render fixed iso / front / bottom views so the shape can be eyeballed."""
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("KeycapPreviewWorld")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.22, 0.23, 0.26, 1.0)
        background.inputs[1].default_value = 1.0
    scene.world = world

    sun_data = bpy.data.lights.new("KeycapSun", type="SUN")
    sun_data.energy = 4.5
    sun = bpy.data.objects.new("KeycapSun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = mathutils.Euler((math.radians(52.0), 0.0, math.radians(40.0)), "XYZ")

    fill_data = bpy.data.lights.new("KeycapFill", type="AREA")
    fill_data.energy = 900.0
    fill_data.size = 60.0
    fill = bpy.data.objects.new("KeycapFill", fill_data)
    scene.collection.objects.link(fill)
    fill.location = (-40.0, -50.0, 25.0)
    fill.rotation_euler = (mathutils.Vector((0, 0, 4)) - fill.location).to_track_quat("-Z", "Y").to_euler()

    material = bpy.data.materials.new("KeycapMat")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.82, 0.83, 0.85, 1.0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.45
    obj.data.materials.clear()
    obj.data.materials.append(material)

    cam_data = bpy.data.cameras.new("KeycapCam")
    cam_data.lens = 85.0
    cam_data.clip_start = 0.5
    cam_data.clip_end = 500.0
    cam = bpy.data.objects.new("KeycapCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    render = scene.render
    render.engine = "BLENDER_EEVEE"
    render.resolution_x = size
    render.resolution_y = size
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"

    # The cavity is a deep pocket that the sun and fill lights cannot reach, so
    # the underside renders pure black. Light it from below for those views only.
    under_data = bpy.data.lights.new("KeycapUnder", type="POINT")
    under_data.energy = 3000.0
    under_data.shadow_soft_size = 8.0
    under = bpy.data.objects.new("KeycapUnder", under_data)
    scene.collection.objects.link(under)
    under.location = (0.0, 0.0, -14.0)
    under.hide_render = True

    target = mathutils.Vector((0.0, 0.0, 4.3))
    views = {
        "iso": (mathutils.Vector((1.0, -1.15, 0.72)), False),
        "front": (mathutils.Vector((0.0, -1.0, 0.10)), False),
        "bottom": (mathutils.Vector((0.55, -0.75, -0.95)), True),
        "underside": (mathutils.Vector((0.05, -0.12, -1.0)), True),
    }
    written = {}
    for name, (direction, light_cavity) in views.items():
        under.hide_render = not light_cavity
        cam.location = target + direction.normalized() * 62.0
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(out_dir, f"keycap_{name}.png")
        render.filepath = path
        bpy.ops.render.render(write_still=True)
        written[name] = path
    return written


# --------------------------------------------------------------------------- #

def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()
    keycap = build_keycap(P)

    REPORT["parameters"] = P
    REPORT["dimensions_mm"] = [round(v, 4) for v in keycap.dimensions]
    REPORT["mesh"] = mesh_report(keycap)
    REPORT["roof_probe"] = measure_top_thickness(keycap, P)

    # Export anyway so the bad mesh can be inspected, but never report success.
    if not REPORT["mesh"]["watertight"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not REPORT["mesh"]["normals_outward"]:
        REPORT["VERDICT"] = "NOT PRINTABLE - normals point inward"
    else:
        REPORT["VERDICT"] = "printable"

    stl_path = os.path.join(project, "models", "keycap_1u_r3.stl")
    export_stl(keycap, stl_path)
    REPORT["stl"] = verify_stl_millimetres(stl_path)
    REPORT["stl_path"] = stl_path

    blend_path = os.path.join(project, "models", "keycap_1u_r3.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    REPORT["blend_path"] = blend_path

    sections = cross_sections(keycap, P["base_width"] / 2.0 + 0.25,
                              heights=(0.4, 2.0, 5.0, 7.2))

    REPORT["renders"] = render_views(keycap, os.path.join(project, "renders"))

    print("KEYCAP_REPORT_START")
    print(json.dumps(REPORT, indent=2))
    print("KEYCAP_REPORT_END")

    print("\nCROSS SECTIONS  ('#' = plastic, '.' = air, 0.5mm grid, +Y up, +X right)")
    for label, rows in sections.items():
        print(f"\n--- {label} mm ---")
        for row in rows:
            print("   " + row)


# Guarded so models/keycap_logo.py can import build_keycap and P without this
# script rebuilding and re-exporting the plain keycap as a side effect. Run
# through tools/blender_exec.py, __name__ is "__blender_mcp__".
if __name__ == "__blender_mcp__":
    main()
