"""Shared geometry and verification helpers for the keycab-3dprint models.

Modelled at 1 Blender unit == 1 mm throughout. Import-safe: defining anything
here must never touch the scene, so build scripts can import it freely.

Extracted from models/keycap.py, which kept these file-local and called main()
at import, making it unusable as a module.
"""

import math
import os
import struct

import bmesh
import bpy
import mathutils


# --------------------------------------------------------------------------- #
# Mesh construction
# --------------------------------------------------------------------------- #

def rounded_rect(width, depth, radius, segments):
    """Outline of a rounded rectangle, counter-clockwise, centred on origin."""
    hw, hd = width / 2.0, depth / 2.0
    radius = max(0.0, min(radius, hw, hd))
    if radius == 0.0:
        return [(hw, hd), (-hw, hd), (-hw, -hd), (hw, -hd)]

    corners = (
        (hw - radius, hd - radius, 0.0),
        (-(hw - radius), hd - radius, math.pi / 2.0),
        (-(hw - radius), -(hd - radius), math.pi),
        (hw - radius, -(hd - radius), 3.0 * math.pi / 2.0),
    )
    points = []
    for cx, cy, start in corners:
        for i in range(segments + 1):
            angle = start + (math.pi / 2.0) * (i / segments)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def make_loft(name, bottom_outline, z0, top_outline, z1):
    """Closed solid lofted between two equal-length outlines."""
    assert len(bottom_outline) == len(top_outline)
    bm = bmesh.new()
    lower = [bm.verts.new((x, y, z0)) for x, y in bottom_outline]
    upper = [bm.verts.new((x, y, z1)) for x, y in top_outline]

    count = len(lower)
    for i in range(count):
        j = (i + 1) % count
        bm.faces.new((lower[i], lower[j], upper[j], upper[i]))
    bm.faces.new(lower)
    bm.faces.new(upper)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def bevel_top_rim(obj, z_top, offset, segments):
    """Bevel only the edge loop sitting at the top plateau boundary."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    tol = 1e-4
    edges = [
        e for e in bm.edges
        if abs(e.verts[0].co.z - z_top) < tol and abs(e.verts[1].co.z - z_top) < tol
    ]
    if edges:
        verts = {v for e in edges for v in e.verts}
        bmesh.ops.bevel(
            bm, geom=list(verts) + edges, offset=offset, offset_type="OFFSET",
            segments=segments, profile=0.5, affect="EDGES", clamp_overlap=True,
        )
    bm.to_mesh(obj.data)
    bm.free()
    return len(edges)


def make_box(name, size, location):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(size[0], size[1], size[2]), verts=bm.verts[:])
    bmesh.ops.translate(bm, vec=location, verts=bm.verts[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_cylinder(name, radius, depth, location, segments, axis="Z"):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius, radius2=radius, depth=depth,
    )
    # Rotate the mesh, then translate. Rotating the *object* after placing the
    # mesh would swing it around the world origin instead of its own centre,
    # which silently moved a lug hole clean off the part once.
    if axis == "X":
        bmesh.ops.rotate(
            bm, verts=bm.verts[:], cent=(0, 0, 0),
            matrix=mathutils.Matrix.Rotation(math.radians(90.0), 3, "Y"),
        )
    elif axis == "Y":
        bmesh.ops.rotate(
            bm, verts=bm.verts[:], cent=(0, 0, 0),
            matrix=mathutils.Matrix.Rotation(math.radians(90.0), 3, "X"),
        )
    bmesh.ops.translate(bm, vec=location, verts=bm.verts[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_cone(name, radius_bottom, radius_top, depth, location, segments):
    """Truncated cone along Z. Used where a part must be thick for strength in
    one place and thin for clearance in another."""
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius_bottom, radius2=radius_top, depth=depth,
    )
    bmesh.ops.translate(bm, vec=location, verts=bm.verts[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_prism_y(name, points_xz, y0, y1):
    """Extrude a closed XZ polygon along Y. Wound so normals come out outward.

    The natural shape for a print-in-place gusset is a triangle, and a triangle
    is what neither make_box nor make_cylinder can give you.
    """
    assert len(points_xz) >= 3
    bm = bmesh.new()
    near = [bm.verts.new((x, y0, z)) for x, z in points_xz]
    far = [bm.verts.new((x, y1, z)) for x, z in points_xz]

    count = len(near)
    for i in range(count):
        j = (i + 1) % count
        bm.faces.new((near[i], near[j], far[j], far[i]))
    bm.faces.new(near)
    bm.faces.new(far)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_revolve(name, profile, segments):
    """Solid of revolution about Z from a (radius, z) profile, bottom to top.

    Preferred over stacking cylinders and cones with UNION: every joint between
    two stacked solids is a pair of coincident faces, which is exactly what
    makes an exact boolean emit 4-valence edges. Revolving one profile has no
    joints at all, so a multi-step stem comes out watertight by construction.
    """
    assert len(profile) >= 2
    bm = bmesh.new()

    rings = []
    for radius, z in profile:
        ring = [
            bm.verts.new((
                radius * math.cos(2.0 * math.pi * i / segments),
                radius * math.sin(2.0 * math.pi * i / segments),
                z,
            ))
            for i in range(segments)
        ]
        rings.append(ring)

    for lower, upper in zip(rings, rings[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            # Skip the degenerate quad a zero-height step would produce.
            if (lower[i].co - upper[i].co).length < 1e-9 and \
               (lower[j].co - upper[j].co).length < 1e-9:
                continue
            bm.faces.new((lower[i], lower[j], upper[j], upper[i]))

    bm.faces.new(rings[0])
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def boolean(target, tool, operation, keep_tool=False):
    """Apply an exact boolean, then discard the tool object."""
    modifier = target.modifiers.new(name=f"bool_{operation.lower()}", type="BOOLEAN")
    modifier.operation = operation
    modifier.object = tool
    modifier.solver = "EXACT"

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    if not keep_tool:
        mesh = tool.data
        bpy.data.objects.remove(tool, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    return target


def duplicate(obj, name):
    copy = obj.copy()
    copy.data = obj.data.copy()
    copy.name = name
    bpy.context.scene.collection.objects.link(copy)
    return copy


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

def mesh_report(obj):
    """Watertightness and volume, measured rather than assumed."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.normal_update()
    non_manifold = [e for e in bm.edges if len(e.link_faces) != 2]
    loose_verts = [v for v in bm.verts if not v.link_edges]
    volume = bm.calc_volume(signed=True)
    stats = {
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "non_manifold_edges": len(non_manifold),
        "loose_vertices": len(loose_verts),
        "signed_volume_mm3": round(volume, 4),
        "watertight": len(non_manifold) == 0 and len(loose_verts) == 0,
        # Negative signed volume means inverted normals -- slicers may read the
        # solid as the hole and vice versa.
        "normals_outward": volume > 0,
    }
    bm.free()
    return stats


def point_inside(obj, point):
    """Inside/outside by ray-crossing parity. Requires a watertight mesh."""
    direction = mathutils.Vector((0.0, 0.0, 1.0))
    cursor = mathutils.Vector(point)
    crossings = 0
    for _ in range(64):
        hit, location, _normal, _index = obj.ray_cast(cursor, direction)
        if not hit:
            break
        crossings += 1
        cursor = location + direction * 1e-5
    return crossings % 2 == 1


def cross_sections(obj, half_extent, heights, step=0.5):
    """ASCII slices through the solid, '#' for material and '.' for air.

    Takes an explicit half extent rather than a parameter dict so any part can
    use it. Rows print with +Y at the top and +X to the right. This is the only
    honest way to confirm interior features -- a hollow part's cavity is unlit
    and invisible in a render.
    """
    coords = []
    value = -half_extent
    while value <= half_extent + 1e-9:
        coords.append(round(value, 3))
        value += step

    sections = {}
    for z in heights:
        rows = []
        for y in reversed(coords):          # +Y at the top of the printout
            rows.append("".join(
                "#" if point_inside(obj, (x, y, z)) else "."
                for x in coords
            ))
        sections[f"z={z}"] = rows
    return sections


# --------------------------------------------------------------------------- #
# Scene and export
# --------------------------------------------------------------------------- #

def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for collection in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights):
        for item in list(collection):
            if item.users == 0:
                collection.remove(item)

    unit = bpy.context.scene.unit_settings
    unit.system = "METRIC"
    unit.scale_length = 0.001          # 1 Blender unit == 1 mm
    unit.length_unit = "MILLIMETERS"


def export_stl(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.wm.stl_export(
        filepath=path,
        check_existing=False,
        export_selected_objects=True,
        apply_modifiers=True,
        ascii_format=False,
        # Blender units are already millimetres here; letting the exporter apply
        # the 0.001 scene unit scale would emit a 0.018mm-tall keycap.
        global_scale=1.0,
        use_scene_unit=False,
        forward_axis="Y",
        up_axis="Z",
    )
    return path


def verify_stl_millimetres(path):
    """Re-read the binary STL and report its real bounding box."""
    with open(path, "rb") as handle:
        handle.read(80)
        (count,) = struct.unpack("<I", handle.read(4))
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for _ in range(count):
            values = struct.unpack("<12fH", handle.read(50))
            for corner in range(3):
                for axis in range(3):
                    v = values[3 + corner * 3 + axis]
                    lo[axis] = min(lo[axis], v)
                    hi[axis] = max(hi[axis], v)
    return {
        "triangles": count,
        "bytes": os.path.getsize(path),
        "min": [round(v, 4) for v in lo],
        "max": [round(v, 4) for v in hi],
        "size": [round(hi[i] - lo[i], 4) for i in range(3)],
    }
