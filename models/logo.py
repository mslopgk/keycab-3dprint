"""Turn an SVG logo into a printable 2D region, then into a prism.

Spec: docs/superpowers/specs/2026-08-10-keycap-logo-relief-design.md

Two methods were tried and rejected before this one:

  * `Curve.offset` to thicken the strokes. It offsets a simple convex fill
    correctly (a radius-5 circle went 10.0 -> 10.5 at offset 0.25) but on the
    real cutters the offset curve self-intersects where the local radius of
    curvature is smaller than the offset: one cutter's Y extent *grew* from
    0.236 to 0.280, and small paths blew up 8-14x.
  * Minkowski-style dilation by unioning 8 translated copies of the composed
    solid. Blender died with EXCEPTION_ACCESS_VIOLATION.

So the dilation happens on a raster in numpy, where a union of pixels is a valid
region by construction and nothing can self-intersect, and the mesh is then built
straight from that mask. Faceting is at `pixel_mm`, far below the 0.4mm a nozzle
can resolve, so it is invisible in the print.
"""

import bmesh
import bpy
import mathutils
import numpy as np

from mxgeom import boolean

# Path classification thresholds. Selection is by rule, never by object name --
# the importer names paths in file order, which is not a contract.
NOZZLE_MM = 0.4


def _luma(obj):
    if obj.data.materials and obj.data.materials[0]:
        c = obj.data.materials[0].diffuse_color
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    return 1.0


def classify_paths(svg_path, target_mm, fill_regions=()):
    """Import the SVG and sort its paths into figure, cutters and rejects.

    `fill_regions` holds area-rank indices of cutters to NOT subtract, so the
    region they would have carved stays solid. Rank 0 is the largest cutter.
    Ranking by area rather than by object name on purpose: the importer names
    paths in file order, which is not a contract.

    Returns (figure, cutters, rejected, scale, disc_span, table) where `table`
    records the decision for every path so the caller can print it.
    """
    before = set(bpy.data.objects.keys())
    bpy.ops.import_curve.svg(filepath=svg_path)
    imported = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    curves = [o for o in imported if o.type == "CURVE"]
    if not curves:
        raise RuntimeError(f"no curves imported from {svg_path!r}")

    table = []

    # The background rect is the path whose X extent covers the whole canvas.
    widest = max(o.dimensions[0] for o in curves)
    background = [o for o in curves if o.dimensions[0] >= widest - 1e-6]
    rest = [o for o in curves if o not in background]
    for obj in background:
        table.append((obj.name, "background", None, None))

    figure = min(rest, key=_luma)
    disc_span = max(figure.dimensions[0], figure.dimensions[1])
    scale = target_mm / disc_span
    table.append((figure.name, "figure", round(disc_span * scale, 4), None))

    candidates, rejected = [], []
    for obj in rest:
        if obj is figure:
            continue
        dx, dy = obj.dimensions[0], obj.dimensions[1]
        min_mm = min(dx, dy) * scale
        max_mm = max(dx, dy) * scale
        # Reject on the MINIMUM dimension. A max-dimension rule lets long thin
        # anti-aliasing slivers through -- six of them, 0.02-0.05mm wide.
        if min_mm >= NOZZLE_MM:
            candidates.append((dx * dy, obj, min_mm, max_mm))
        else:
            rejected.append(obj)
            table.append((obj.name, "sliver-rejected", round(min_mm, 4), round(max_mm, 4)))

    candidates.sort(key=lambda t: t[0], reverse=True)
    cutters = []
    for rank, (_area, obj, min_mm, max_mm) in enumerate(candidates):
        if rank in fill_regions:
            table.append((obj.name, f"filled (rank {rank}, not subtracted)",
                          round(min_mm, 4), round(max_mm, 4)))
        else:
            cutters.append(obj)
            table.append((obj.name, f"cutter (rank {rank})",
                          round(min_mm, 4), round(max_mm, 4)))

    # Keep the unused paths in the scene. Removing objects invalidates the
    # Python references to the ones that remain, which is a real crash source.
    keep = {figure.name} | {c.name for c in cutters}
    for obj in imported:
        if obj.type != "CURVE" and obj.name not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)

    return figure, cutters, rejected, scale, disc_span, table


def compose_region(svg_path, target_mm, extrude_mm=0.6, fill_regions=()):
    """figure minus cutters, as a flat solid scaled so the figure is target_mm."""
    figure, cutters, _rejected, scale, _span, table = classify_paths(
        svg_path, target_mm, fill_regions
    )

    solids = []
    for obj in [figure] + cutters:
        obj.data.dimensions = "2D"
        obj.data.fill_mode = "BOTH"
        obj.data.extrude = extrude_mm / scale
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.convert(target="MESH")
        solids.append(bpy.context.view_layer.objects.active)

    # Address by name: boolean() deletes each tool it applies, and removing an
    # object invalidates the Python references held to the others.
    base_name = solids[0].name
    for tool_name in [s.name for s in solids[1:]]:
        boolean(bpy.data.objects[base_name], bpy.data.objects[tool_name], "DIFFERENCE")
    base = bpy.data.objects[base_name]

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = base
    base.select_set(True)
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    base.location = (0.0, 0.0, 0.0)
    base.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    base.name = "Logo_Composed"
    base.data.name = "Logo_Composed"
    return base, table


def rasterise(obj, half_extent, pixel_mm):
    """Boolean mask of the flat solid. One downward ray per sample suffices."""
    steps = int(round(2 * half_extent / pixel_mm)) + 1
    top = obj.dimensions[2] + 5.0
    down = mathutils.Vector((0.0, 0.0, -1.0))
    mask = np.zeros((steps, steps), dtype=bool)
    for iy in range(steps):
        y = -half_extent + iy * pixel_mm
        for ix in range(steps):
            x = -half_extent + ix * pixel_mm
            hit, _l, _n, _i = obj.ray_cast(mathutils.Vector((x, y, top)), down)
            mask[iy, ix] = hit
    return mask


def dilate(mask, amount_mm, pixel_mm):
    """Grow the region. A union of pixels cannot self-intersect."""
    steps = int(round(amount_mm / pixel_mm))
    out = mask
    for _ in range(steps):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def erode(mask, amount_mm, pixel_mm):
    steps = int(round(amount_mm / pixel_mm))
    out = mask
    for _ in range(steps):
        shrunk = out.copy()
        shrunk[1:, :] &= out[:-1, :]
        shrunk[:-1, :] &= out[1:, :]
        shrunk[:, 1:] &= out[:, :-1]
        shrunk[:, :-1] &= out[:, 1:]
        shrunk[0, :] = shrunk[-1, :] = False
        shrunk[:, 0] = shrunk[:, -1] = False
        out = shrunk
    return out


def min_width_stats(mask, pixel_mm, nozzle_mm=NOZZLE_MM):
    """Local thickness by iterative erosion; how much is too thin to print."""
    thickness = np.zeros(mask.shape, dtype=float)
    work = mask.copy()
    step = 0
    while work.any() and step < 200:
        step += 1
        work = erode(work, pixel_mm, pixel_mm)
        thickness[work] = step * 2 * pixel_mm
    solid = thickness[mask]
    if solid.size == 0:
        return {"area_mm2": 0.0, "min_width_mm": 0.0, "below_nozzle_pct": 100.0}
    return {
        "area_mm2": round(float(mask.sum()) * pixel_mm * pixel_mm, 3),
        "max_thickness_mm": round(float(solid.max()), 3),
        "below_nozzle_pct": round(100.0 * float((solid < nozzle_mm).sum()) / solid.size, 2),
        "p05_thickness_mm": round(float(np.percentile(solid, 5)), 3),
    }


def mask_to_prism(mask, half_extent, pixel_mm, z0, z1, name="Logo_Prism"):
    """Build a closed prism whose footprint is the mask.

    Marching squares rather than one quad per pixel: a pixel-quad boundary steps
    at 90 degrees and reads as visible jaggedness, while cutting through edge
    midpoints puts the boundary at 45 degrees.

    Each cell is filled by walking its boundary counter-clockwise through eight
    positions -- corner, edge midpoint, corner, ... -- and keeping a corner when
    it is inside, and a midpoint when *either* of its corners is inside. Keeping
    midpoints on fully-interior edges too is what avoids T-junctions: a solid
    cell and a boundary cell then split their shared edge identically. A
    16-entry case table that used bare corners for solid cells produced exactly
    those T-junctions, and the mesh came out non-manifold.

    Vertices are shared through a dict keyed in half-pixel units so midpoints
    land on integers. No booleans are involved, so none of the boolean fragility
    that killed the earlier dilation attempts applies here.
    """
    bm = bmesh.new()
    verts = {}

    def vert(gx, gy):
        key = (gx, gy)
        got = verts.get(key)
        if got is None:
            got = bm.verts.new((
                -half_extent + gx * 0.5 * pixel_mm,
                -half_extent + gy * 0.5 * pixel_mm,
                z0,
            ))
            verts[key] = got
        return got

    height, width = mask.shape
    for iy in range(height - 1):
        for ix in range(width - 1):
            sw = bool(mask[iy, ix])
            se = bool(mask[iy, ix + 1])
            ne = bool(mask[iy + 1, ix + 1])
            nw = bool(mask[iy + 1, ix])
            if not (sw or se or ne or nw):
                continue

            gx, gy = ix * 2, iy * 2
            # CCW: SW corner, S mid, SE corner, E mid, NE corner, N mid, NW, W mid
            ring = (
                (sw, (gx, gy)),
                (sw or se, (gx + 1, gy)),
                (se, (gx + 2, gy)),
                (se or ne, (gx + 2, gy + 1)),
                (ne, (gx + 2, gy + 2)),
                (ne or nw, (gx + 1, gy + 2)),
                (nw, (gx, gy + 2)),
                (nw or sw, (gx, gy + 1)),
            )
            corners = [vert(*pos) for keep, pos in ring if keep]
            if len(corners) < 3:
                continue
            try:
                bm.faces.new(corners)
            except ValueError:
                pass        # face already exists; harmless

    if not bm.faces:
        bm.free()
        raise RuntimeError("mask produced no faces")

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    # Collapse the interior into large faces; the boundary keeps its pixel steps,
    # which are pixel_mm and therefore invisible at print resolution.
    bmesh.ops.dissolve_limit(
        bm, angle_limit=0.0017, verts=bm.verts[:], edges=bm.edges[:],
        delimit={"NORMAL"},
    )
    result = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
    moved = [e for e in result["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0.0, 0.0, z1 - z0), verts=moved)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_logo_prism(svg_path, target_mm, dilate_mm, pixel_mm, z0, z1,
                     fill_regions=()):
    """End to end: SVG -> classified paths -> composed region -> dilated prism."""
    composed, table = compose_region(svg_path, target_mm, fill_regions=fill_regions)
    half = target_mm / 2.0 + dilate_mm + 4 * pixel_mm
    mask = rasterise(composed, half, pixel_mm)
    before = min_width_stats(mask, pixel_mm)
    grown = dilate(mask, dilate_mm, pixel_mm)
    after = min_width_stats(grown, pixel_mm)

    data = composed.data
    bpy.data.objects.remove(composed, do_unlink=True)
    bpy.data.meshes.remove(data)

    prism = mask_to_prism(grown, half, pixel_mm, z0, z1)
    return prism, {
        "paths": [
            {"name": n, "role": r, "min_mm": a, "max_mm": b} for n, r, a, b in table
        ],
        "pixel_mm": pixel_mm,
        "as_drawn": before,
        "dilated": after,
        "prism_dimensions_mm": [round(v, 4) for v in prism.dimensions],
    }
