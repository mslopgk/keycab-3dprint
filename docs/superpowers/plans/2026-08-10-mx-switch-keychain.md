# MX Switch Keychain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-piece 3D-printable closed-box housing that retains a real MX-compatible switch on a 1.5 mm plate cutout, with a keyring lug and a removable snap-on bottom cap, plus fit coupons to settle the two unknown tolerances first.

**Architecture:** Geometry helpers currently private to `models/keycap.py` get extracted into an importable `models/mxgeom.py`, then the housing, the cap, and the coupons are three build scripts on top of it. Everything runs inside a headless Blender through the existing socket server; there is no pytest, so "tests" are assertion scripts that run in Blender and exit non-zero on failure.

**Tech Stack:** Blender 5.2 `bpy`/`bmesh` (1 Blender unit == 1 mm), Python 3.12 on the host, the project's own `tools/blender_exec.py` socket client, OrcaSlicer 2.4.2 portable CLI, Bambu Lab A1 mini over LAN.

## Global Constraints

- Model at **1 Blender unit == 1 mm**. Export STL with `global_scale=1.0` and `use_scene_unit=False`.
- Every exported part must be **watertight** (zero non-manifold edges, zero loose vertices) with **outward normals** (`signed_volume > 0`). A part failing this still exports for inspection but the script must report `VERDICT: NOT PRINTABLE`.
- **No individual pin holes** in the pocket floor. The floor is flat and unbroken.
- Housing dimensions, verbatim from the spec: body `19.0 × 19.0 mm`; footprint incl. lug `24.5 × 19.0 mm`; height `11.0 mm`; plate thickness `1.5 mm`; plate opening `14.0 × 14.0 mm` corner `R0.5`; pocket `15.8 × 15.8 mm`; pocket depth `9.5 mm`; wall `1.6 mm`; latch relief `1.0 mm` deep on **all four** sides; lug tab `5.5 mm` protrusion × `7.0 mm` wide × `3.0 mm` thick; lug hole `4.0 mm` diameter, **vertical axis**, centre `2.0 mm` out from the body face, `1.5 mm` material around it.
- Bottom cap, verbatim from the spec: `19.0 × 19.0 × 1.2 mm` plate sitting **under** the housing (assembled height `12.2 mm`); `4` snap tongues, one per side, `0.8 mm` thick; housing inner-wall undercut `0.6 mm`, positioned `1.5 mm` above the housing's bottom face.
- Coupon 1, verbatim from the spec: one flat tile `20 × 60 × 1.6 mm`, three `20 × 20 mm` cells, plate thickness `1.4 / 1.5 / 1.6 mm`, opening fixed at `14.0 mm`, each cell embossed with its thickness.
- Print orientation: housing **plate face down**, cap **flat**, coupons **flat**. No support on any part.
- Do not delete or overwrite anything on the printer's SD card.

---

### Task 1: Give Blender-side scripts a `__file__` so they can import siblings

The addon's `execute_code` builds its namespace with `__name__` but no `__file__` (`tools/blender_mcp_ext/__init__.py:140-146`). A script sent through the socket therefore cannot locate its own directory, so `models/switch_housing.py` cannot `import mxgeom`. Fix it host-side in the client by prepending a preamble, which keeps the wire protocol unchanged and needs no addon edit or server restart.

**Files:**
- Modify: `tools/blender_exec.py` (the `main()` branch that reads a script file)
- Create: `tests/blender/test_script_context.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a guarantee that any file executed via `python tools/blender_exec.py <path>` sees `__file__` set to the script's absolute path, and that `os.path.dirname(__file__)` is on `sys.path`.

- [ ] **Step 1: Write the failing test**

Create `tests/blender/test_script_context.py`:

```python
"""Runs inside Blender. Exits non-zero if the script context is missing."""

import os
import sys

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


check("__file__ is defined", "__file__" in globals(), repr(globals().get("__file__")))

path = globals().get("__file__", "")
check("__file__ is absolute", bool(path) and os.path.isabs(path), path)
check("__file__ basename matches", os.path.basename(path) == "test_script_context.py", path)
check("__file__ exists on disk", bool(path) and os.path.exists(path), path)
check("own directory is importable", os.path.dirname(path) in sys.path, os.path.dirname(path))

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + str(failures)}")
if failures:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
powershell -File tools/blender_server.ps1 start
python tools/blender_exec.py tests/blender/test_script_context.py
```

Expected: `FAIL  __file__ is defined -- None` and the remaining four checks also FAIL, because `blender_exec.py` currently sends only the file's bytes.

- [ ] **Step 3: Write minimal implementation**

In `tools/blender_exec.py`, replace the branch that reads a script from disk:

```python
        elif args.script:
            with open(args.script, "r", encoding="utf-8") as handle:
                code = handle.read()
```

with:

```python
        elif args.script:
            with open(args.script, "r", encoding="utf-8") as handle:
                code = handle.read()
            # execute_code has no notion of a file, so the script cannot find its
            # own directory and cannot import a sibling module. Supply both.
            script_path = os.path.abspath(args.script)
            preamble = (
                "import os, sys\n"
                f"__file__ = {script_path!r}\n"
                f"_d = os.path.dirname({script_path!r})\n"
                "sys.path.insert(0, _d) if _d not in sys.path else None\n"
                "del _d\n"
            )
            code = preamble + code
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python tools/blender_exec.py tests/blender/test_script_context.py
```

Expected: five `PASS` lines then `ALL CHECKS PASSED`, exit code 0.

- [ ] **Step 5: Confirm nothing regressed for inline code and the existing suite**

```bash
python tools/blender_exec.py -c "print('inline still works')"
python tools/mcp_client_test.py
```

Expected: `inline still works`; then `ALL CHECKS PASSED` from the protocol suite. The preamble is only added on the file branch, so `-c` is untouched.

- [ ] **Step 6: Commit**

```bash
git add tools/blender_exec.py tests/blender/test_script_context.py
git commit -m "feat: give Blender-side scripts __file__ and an importable directory"
```

---

### Task 2: Extract shared geometry into `models/mxgeom.py`

`models/keycap.py` defines every helper the housing needs but keeps them file-local, and it calls `main()` at module level, so importing it would rebuild and re-export the keycap. Extract the reusable half into a module that has no side effects at import.

**Files:**
- Create: `models/mxgeom.py`
- Modify: `models/keycap.py` (delete the extracted definitions, import them instead)
- Create: `tests/blender/test_mxgeom.py`

**Interfaces:**
- Consumes: Task 1's `sys.path` injection, so `import mxgeom` resolves from `models/`.
- Produces, all in `mxgeom`, signatures unchanged from their current definitions in `keycap.py`:
  - `rounded_rect(width, depth, radius, segments) -> list[tuple[float, float]]`
  - `make_loft(name, bottom_outline, z0, top_outline, z1) -> bpy.types.Object`
  - `make_box(name, size, location) -> bpy.types.Object`
  - `make_cylinder(name, radius, depth, location, segments, axis="Z") -> bpy.types.Object`
  - `boolean(target, tool, operation, keep_tool=False) -> bpy.types.Object`
  - `duplicate(obj, name) -> bpy.types.Object`
  - `bevel_top_rim(obj, z_top, offset, segments) -> int`
  - `mesh_report(obj) -> dict`
  - `reset_scene() -> None`
  - `point_inside(obj, point) -> bool`
  - `export_stl(obj, path) -> str`
  - `verify_stl_millimetres(path) -> dict`
  - And one new helper, generalised from `keycap.cross_sections` so it no longer takes the keycap's `P` dict:
    `cross_sections(obj, half_extent, heights, step=0.5) -> dict[str, list[str]]`

- [ ] **Step 1: Write the failing test**

Create `tests/blender/test_mxgeom.py`:

```python
"""Runs inside Blender. Checks the extracted helpers behave as before."""

import mxgeom

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


mxgeom.reset_scene()

# rounded_rect: 4 corners * (segments + 1) points, all inside the half extents.
pts = mxgeom.rounded_rect(19.0, 19.0, 1.0, 8)
check("rounded_rect point count", len(pts) == 4 * 9, str(len(pts)))
check("rounded_rect stays in bounds",
      max(abs(x) for x, _ in pts) <= 9.5 + 1e-6 and max(abs(y) for _, y in pts) <= 9.5 + 1e-6)

# make_box: a 19 x 19 x 1.2 plate centred at z = 0.6 spans z 0..1.2.
box = mxgeom.make_box("T_Box", (19.0, 19.0, 1.2), (0.0, 0.0, 0.6))
check("make_box dimensions", [round(v, 4) for v in box.dimensions] == [19.0, 19.0, 1.2],
      str([round(v, 4) for v in box.dimensions]))
report = mxgeom.mesh_report(box)
check("make_box watertight", report["watertight"], str(report))
check("make_box normals outward", report["normals_outward"], str(report))
check("make_box volume", abs(report["signed_volume_mm3"] - 19.0 * 19.0 * 1.2) < 1e-3,
      str(report["signed_volume_mm3"]))

# point_inside: centre is solid, a point outside the slab is not.
check("point_inside centre", mxgeom.point_inside(box, (0.0, 0.0, 0.6)) is True)
check("point_inside above", mxgeom.point_inside(box, (0.0, 0.0, 5.0)) is False)

# boolean DIFFERENCE punches a hole that point_inside can see.
tool = mxgeom.make_cylinder("T_Cut", 2.0, 10.0, (0.0, 0.0, 0.6), 48)
mxgeom.boolean(box, tool, "DIFFERENCE")
check("boolean cut removes centre", mxgeom.point_inside(box, (0.0, 0.0, 0.6)) is False)
check("boolean cut keeps edge", mxgeom.point_inside(box, (8.0, 8.0, 0.6)) is True)
check("boolean result watertight", mxgeom.mesh_report(box)["watertight"])

# cross_sections takes a half extent now, not the keycap parameter dict.
sections = mxgeom.cross_sections(box, 10.0, heights=(0.6,), step=1.0)
rows = sections["z=0.6"]
check("cross_sections row count", len(rows) == 21, str(len(rows)))
check("cross_sections centre is air", rows[len(rows) // 2][len(rows) // 2] == ".",
      rows[len(rows) // 2])

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + str(failures)}")
if failures:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tools/blender_exec.py tests/blender/test_mxgeom.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mxgeom'`.

- [ ] **Step 3: Create `models/mxgeom.py`**

Move — do not copy — these definitions out of `models/keycap.py` into a new `models/mxgeom.py`, keeping their bodies byte-identical: `rounded_rect`, `make_loft`, `bevel_top_rim`, `make_box`, `make_cylinder`, `boolean`, `duplicate`, `mesh_report`, `reset_scene`, `point_inside`, `export_stl`, `verify_stl_millimetres`. Give the module this header and imports, and no module-level side effects:

```python
"""Shared geometry and verification helpers for the keycab-3dprint models.

Modelled at 1 Blender unit == 1 mm throughout. Import-safe: defining anything
here must never touch the scene, so build scripts can import it freely.
"""

import math
import os
import struct

import bmesh
import bpy
import mathutils
```

Then add the generalised `cross_sections`, replacing the keycap-specific one:

```python
def cross_sections(obj, half_extent, heights, step=0.5):
    """ASCII slices through the solid, '#' for material and '.' for air.

    Takes an explicit half extent rather than a parameter dict so any part can
    use it. Rows print with +Y at the top and +X to the right.
    """
    coords = []
    value = -half_extent
    while value <= half_extent + 1e-9:
        coords.append(round(value, 3))
        value += step

    sections = {}
    for z in heights:
        rows = []
        for y in reversed(coords):
            rows.append("".join(
                "#" if point_inside(obj, (x, y, z)) else "."
                for x in coords
            ))
        sections[f"z={z}"] = rows
    return sections
```

- [ ] **Step 4: Repoint `models/keycap.py` at the module**

Replace `keycap.py`'s now-deleted definitions with an import, and delete its local `cross_sections`:

```python
import mxgeom
from mxgeom import (
    bevel_top_rim, boolean, cross_sections, duplicate, export_stl, make_box,
    make_cylinder, make_loft, mesh_report, point_inside, reset_scene,
    rounded_rect, verify_stl_millimetres,
)
```

Update the one call site that passed the parameter dict. In `main()`, change:

```python
    sections = cross_sections(keycap, P, heights=(0.4, 2.0, 5.0, 7.2))
```

to:

```python
    sections = cross_sections(keycap, P["base_width"] / 2.0 + 0.25,
                              heights=(0.4, 2.0, 5.0, 7.2))
```

Leave `dish_radius`, `build_keycap`, `measure_top_thickness`, `render_views`, `main`, `P` and `REPORT` in `keycap.py` — they are keycap-specific.

- [ ] **Step 5: Run the helper test to verify it passes**

```bash
python tools/blender_exec.py tests/blender/test_mxgeom.py
```

Expected: every check `PASS`, then `ALL CHECKS PASSED`, exit code 0.

- [ ] **Step 6: Prove the keycap is byte-identical after the refactor**

The extraction must not change geometry, so re-running the keycap build must reproduce the exact same STL.

```bash
python tools/blender_exec.py models/keycap.py
md5sum models/keycap_1u_r3.stl
```

Expected: `KEYCAP_REPORT_START` … `"VERDICT": "printable"`, `non_manifold_edges: 0`, and the hash exactly `f567510240023cb5a7808314c5a7bf60` (45184 bytes). Then re-run the print-orientation export and check its hash too:

```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background models/keycap_1u_r3.blend --python models/export_printready.py
md5sum models/keycap_1u_r3_printready.stl
```

Expected: `51c9fe26924c15bf2439d854c985276d` (45184 bytes). **If either hash differs, the extraction changed behaviour — stop and diff the moved functions rather than accepting the new hash.**

- [ ] **Step 7: Commit**

```bash
git add models/mxgeom.py models/keycap.py tests/blender/test_mxgeom.py
git commit -m "refactor: extract shared geometry helpers into models/mxgeom.py"
```

---

### Task 3: Housing body — plate, opening and pocket

Build the housing's core solid: a 19 × 19 × 11 block, a 14 × 14 opening through the 1.5 mm top plate, and a 15.8 × 15.8 × 9.5 pocket open at the bottom. Lug and latch relief come in Task 4; the cap comes in Task 5.

**Files:**
- Create: `models/switch_housing.py`
- Create: `tests/blender/test_housing_body.py`

**Interfaces:**
- Consumes: `mxgeom.rounded_rect`, `make_box`, `boolean`, `mesh_report`, `reset_scene`, `point_inside`, `cross_sections`, `export_stl`, `verify_stl_millimetres`.
- Produces:
  - `models/switch_housing.py` module-level `H` dict holding every dimension by the spec's names: `body_width`, `body_depth`, `height`, `plate_thickness`, `opening`, `opening_corner_r`, `pocket`, `pocket_depth`, `wall`, `latch_relief_depth`, `lug_protrusion`, `lug_width`, `lug_thickness`, `lug_hole_diameter`, `lug_hole_offset`, `cap_thickness`, `cap_tongue_thickness`, `undercut_depth`, `undercut_z`, `corner_segments`.
  - `build_housing(h) -> bpy.types.Object` named `Switch_Housing`.
  - `housing_report(obj, h) -> dict` with keys `dimensions_mm`, `mesh`, `plate_thickness_probe`, `opening_probe`, `pocket_probe`, `VERDICT`.

- [ ] **Step 1: Write the failing test**

Create `tests/blender/test_housing_body.py`:

```python
"""Runs inside Blender. Verifies the housing's plate, opening and pocket."""

import mxgeom
import switch_housing

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


mxgeom.reset_scene()
h = dict(switch_housing.H)
# Task 3 builds the core solid only; lug and relief are Task 4.
h["lug_protrusion"] = 0.0
h["latch_relief_depth"] = 0.0
obj = switch_housing.build_housing(h)

dims = [round(v, 4) for v in obj.dimensions]
check("footprint without lug is 19 x 19", dims[0] == 19.0 and dims[1] == 19.0, str(dims))
check("height is 11.0", dims[2] == 11.0, str(dims))

report = mxgeom.mesh_report(obj)
check("watertight", report["watertight"], str(report))
check("normals outward", report["normals_outward"], str(report))

plate_top = h["height"]                      # 11.0
plate_bottom = h["height"] - h["plate_thickness"]   # 9.5

# Plate: solid at its own level away from the opening, air inside the opening.
check("plate is solid at the edge",
      mxgeom.point_inside(obj, (8.5, 8.5, plate_top - 0.5)) is True)
check("opening is air at plate level",
      mxgeom.point_inside(obj, (0.0, 0.0, plate_top - 0.5)) is False)
check("opening is 14 wide: inside at 6.8",
      mxgeom.point_inside(obj, (6.8, 0.0, plate_top - 0.5)) is False)
check("opening is 14 wide: material at 7.2",
      mxgeom.point_inside(obj, (7.2, 0.0, plate_top - 0.5)) is True)

# Pocket: air in the middle, wall material outside 15.8/2 = 7.9.
check("pocket is air", mxgeom.point_inside(obj, (0.0, 0.0, 5.0)) is False)
check("pocket is 15.8 wide: inside at 7.7",
      mxgeom.point_inside(obj, (7.7, 0.0, 5.0)) is False)
check("wall is material at 8.5", mxgeom.point_inside(obj, (8.5, 0.0, 5.0)) is True)

# body_width, pocket and wall must agree, or the wall thickness is a fiction.
bad = dict(h)
bad["pocket"] = 16.2          # would imply a 1.4 wall, not 1.6
raised = False
try:
    switch_housing.build_housing(bad)
except ValueError:
    raised = True
check("inconsistent wall raises ValueError", raised)

# Bottom face must be open, not skinned over.
check("bottom is open", mxgeom.point_inside(obj, (0.0, 0.0, 0.2)) is False)

# Ray-cast the plate thickness at a point clear of the opening.
probe = switch_housing.housing_report(obj, h)["plate_thickness_probe"]
check("plate measures 1.5 thick",
      any(abs(v - 1.5) < 0.02 for v in probe.values() if isinstance(v, float)),
      str(probe))

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + str(failures)}")
if failures:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tools/blender_exec.py tests/blender/test_housing_body.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'switch_housing'`.

- [ ] **Step 3: Write minimal implementation**

Create `models/switch_housing.py`:

```python
"""Two-piece closed-box housing that retains an MX-compatible switch.

Spec: docs/superpowers/specs/2026-08-10-keycap-keychain-design.md

Modelled at 1 Blender unit == 1 mm. The switch is held the way a keyboard holds
it -- latches gripping the underside of a 1.5 mm plate -- so click travel matches
a keyboard by construction rather than by matching absolute stem heights.
"""

import json
import os

import bmesh
import bpy
import mathutils

import mxgeom
from mxgeom import (
    boolean, cross_sections, export_stl, make_box, make_cylinder, make_loft,
    mesh_report, point_inside, reset_scene, rounded_rect, verify_stl_millimetres,
)

H = {
    "body_width": 19.0,
    "body_depth": 19.0,
    "height": 11.0,
    "plate_thickness": 1.5,
    "opening": 14.0,
    "opening_corner_r": 0.5,
    "pocket": 15.8,
    "pocket_depth": 9.5,
    "wall": 1.6,
    "latch_relief_depth": 1.0,
    "lug_protrusion": 5.5,
    "lug_width": 7.0,
    "lug_thickness": 3.0,
    "lug_hole_diameter": 4.0,
    "lug_hole_offset": 2.0,
    "cap_thickness": 1.2,
    "cap_tongue_thickness": 0.8,
    "undercut_depth": 0.6,
    "undercut_z": 1.5,
    "corner_segments": 8,
}


def build_housing(h):
    """Core solid: block, plate opening, pocket. Lug/relief handled by Task 4."""
    # body_width, pocket and wall are three numbers describing two independent
    # dimensions, so they can silently disagree. Fail loudly instead.
    derived_wall = (h["body_width"] - h["pocket"]) / 2.0
    if abs(derived_wall - h["wall"]) > 1e-6:
        raise ValueError(
            f"wall mismatch: body_width {h['body_width']} - pocket {h['pocket']} "
            f"implies a {derived_wall} wall, but wall is set to {h['wall']}"
        )

    body = make_box(
        "Switch_Housing",
        (h["body_width"], h["body_depth"], h["height"]),
        (0.0, 0.0, h["height"] / 2.0),
    )

    # Pocket, open at the bottom. Extends below z=0 so the underside is genuinely
    # open rather than skinned, the same trick the keycap cavity uses.
    pocket_top = h["height"] - h["plate_thickness"]
    pocket = make_box(
        "Pocket",
        (h["pocket"], h["pocket"], h["pocket_depth"] + 2.0),
        (0.0, 0.0, pocket_top - (h["pocket_depth"] + 2.0) / 2.0 + 1.0),
    )
    boolean(body, pocket, "DIFFERENCE")

    # Plate opening: rounded-square prism through the plate only, overshooting
    # both faces so no coplanar faces meet the plate surfaces.
    outline = rounded_rect(h["opening"], h["opening"], h["opening_corner_r"],
                           h["corner_segments"])
    opening = make_loft("Opening", outline, pocket_top - 1.0, outline, h["height"] + 1.0)
    boolean(body, opening, "DIFFERENCE")

    body.name = "Switch_Housing"
    body.data.name = "Switch_Housing"
    return body


def measure_plate_thickness(obj, h):
    """Ray-cast down through the plate at four points clear of the opening."""
    results = {}
    for label, x, y in (("front_left", -8.2, -8.2), ("front_right", 8.2, -8.2),
                        ("back_left", -8.2, 8.2), ("back_right", 8.2, 8.2)):
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


def _span(obj, z, axis):
    """Width of the air gap through the centre at height z, sampled at 0.05mm."""
    step = 0.05
    limit = 12.0
    positive = 0.0
    value = 0.0
    while value <= limit:
        point = (value, 0.0, z) if axis == "x" else (0.0, value, z)
        if point_inside(obj, point):
            break
        positive = value
        value += step
    return round(positive * 2.0, 3)


def housing_report(obj, h):
    plate_top = h["height"]
    report = {
        "dimensions_mm": [round(v, 4) for v in obj.dimensions],
        "mesh": mesh_report(obj),
        "plate_thickness_probe": measure_plate_thickness(obj, h),
        "opening_probe": {
            "x_span_mm": _span(obj, plate_top - h["plate_thickness"] / 2.0, "x"),
            "y_span_mm": _span(obj, plate_top - h["plate_thickness"] / 2.0, "y"),
        },
        "pocket_probe": {
            "x_span_mm": _span(obj, h["pocket_depth"] / 2.0, "x"),
            "y_span_mm": _span(obj, h["pocket_depth"] / 2.0, "y"),
        },
    }
    mesh = report["mesh"]
    if not mesh["watertight"]:
        report["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        report["VERDICT"] = "NOT PRINTABLE - normals point inward"
    else:
        report["VERDICT"] = "printable"
    return report


def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"

    housing = build_housing(H)
    report = housing_report(housing, H)
    report["parameters"] = H

    stl = os.path.join(project, "models", "switch_housing.stl")
    export_stl(housing, stl)
    report["stl"] = verify_stl_millimetres(stl)

    print("HOUSING_REPORT_START")
    print(json.dumps(report, indent=2))
    print("HOUSING_REPORT_END")

    sections = cross_sections(housing, H["body_width"] / 2.0 + 0.25,
                              heights=(0.5, 5.0, 10.2))
    print("\nCROSS SECTIONS  ('#' = plastic, '.' = air, 0.5mm grid, +Y up, +X right)")
    for label, rows in sections.items():
        print(f"\n--- {label} mm ---")
        for row in rows:
            print("   " + row)


if __name__ == "__blender_mcp__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python tools/blender_exec.py tests/blender/test_housing_body.py
```

Expected: every check `PASS`, then `ALL CHECKS PASSED`.

If `watertight` fails, the cause is almost certainly a coplanar face where the pocket or opening cutter lands exactly on a housing surface — the same failure mode that produced 10 non-manifold edges in the keycap. Widen the offending cutter's overshoot; do not "fix" it by ignoring the check.

- [ ] **Step 5: Run the full build and read the cross-sections**

```bash
python tools/blender_exec.py models/switch_housing.py
```

Expected: `"VERDICT": "printable"`, `non_manifold_edges: 0`, `opening_probe` spans ≈ `14.0`, `pocket_probe` spans ≈ `15.8`, `stl.size_mm` ≈ `[19.0, 19.0, 11.0]`. The `z=10.2` section shows a 14 mm square hole in a solid plate; `z=5.0` shows a 15.8 mm pocket ringed by 1.6 mm wall; `z=0.5` looks the same as `z=5.0`.

- [ ] **Step 6: Commit**

```bash
git add models/switch_housing.py tests/blender/test_housing_body.py
git commit -m "feat: housing body with 1.5mm plate, 14mm MX opening and 15.8mm pocket"
```

---

### Task 4: Latch relief on all four sides, and the keyring lug

**Files:**
- Modify: `models/switch_housing.py` (extend `build_housing`)
- Create: `tests/blender/test_housing_lug_relief.py`

**Interfaces:**
- Consumes: Task 3's `build_housing(h)`, `H`, `housing_report(obj, h)`.
- Produces: `build_housing` now honours `h["latch_relief_depth"]` and `h["lug_protrusion"]`; `housing_report` gains a `lug_hole_probe` key with `diameter_mm`.

- [ ] **Step 1: Write the failing test**

Create `tests/blender/test_housing_lug_relief.py`:

```python
"""Runs inside Blender. Verifies latch relief grooves and the keyring lug."""

import mxgeom
import switch_housing

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


mxgeom.reset_scene()
h = dict(switch_housing.H)
obj = switch_housing.build_housing(h)

dims = [round(v, 4) for v in obj.dimensions]
check("footprint with lug is 24.5 x 19", dims[0] == 24.5 and dims[1] == 19.0, str(dims))
check("height still 11.0", dims[2] == 11.0, str(dims))

report = mxgeom.mesh_report(obj)
check("watertight", report["watertight"], str(report))
check("normals outward", report["normals_outward"], str(report))

plate_bottom = h["height"] - h["plate_thickness"]     # 9.5
relief_z = plate_bottom - h["latch_relief_depth"] / 2.0   # 9.0

# Relief widens the opening below the plate on all four sides, so a point that
# is material at plate level is air one millimetre lower.
for label, x, y in (("+X", 7.2, 0.0), ("-X", -7.2, 0.0),
                    ("+Y", 0.0, 7.2), ("-Y", 0.0, -7.2)):
    check(f"relief present on {label}",
          mxgeom.point_inside(obj, (x, y, h["height"] - 0.5)) is True
          and mxgeom.point_inside(obj, (x, y, relief_z)) is False,
          f"plate={mxgeom.point_inside(obj, (x, y, h['height'] - 0.5))} "
          f"relief={mxgeom.point_inside(obj, (x, y, relief_z))}")

check("relief does not breach the wall",
      mxgeom.point_inside(obj, (8.6, 0.0, relief_z)) is True)

# Lug sits on -X, centred on the body height, hole axis vertical.
lug_x = -(h["body_width"] / 2.0 + h["lug_hole_offset"])   # -11.5
lug_z = h["height"] / 2.0                                  # 5.5
check("lug material exists", mxgeom.point_inside(obj, (lug_x, 3.0, lug_z)) is True)
check("lug hole is air at its centre",
      mxgeom.point_inside(obj, (lug_x, 0.0, lug_z)) is False)
check("lug hole is 4mm: air at 1.8 from centre",
      mxgeom.point_inside(obj, (lug_x, 1.8, lug_z)) is False)
check("lug hole is 4mm: material at 2.2 from centre",
      mxgeom.point_inside(obj, (lug_x, 2.2, lug_z)) is True)

# Vertical axis: the hole is air all the way through the tab's 3mm thickness,
# and solid above and below it.
check("hole runs vertically through the tab",
      mxgeom.point_inside(obj, (lug_x, 0.0, lug_z + 1.0)) is False
      and mxgeom.point_inside(obj, (lug_x, 0.0, lug_z - 1.0)) is False)
check("tab has material above the hole",
      mxgeom.point_inside(obj, (lug_x, 3.0, lug_z + 1.0)) is True)

probe = switch_housing.housing_report(obj, h)["lug_hole_probe"]
check("measured hole diameter is 4.0",
      abs(probe["diameter_mm"] - 4.0) < 0.15, str(probe))

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + str(failures)}")
if failures:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tools/blender_exec.py tests/blender/test_housing_lug_relief.py
```

Expected: FAIL on `footprint with lug is 24.5 x 19` (still 19.0 wide) and on the relief and lug checks, plus a `KeyError: 'lug_hole_probe'`.

- [ ] **Step 3: Add relief and lug to `build_housing`**

In `models/switch_housing.py`, insert this immediately before the `body.name = "Switch_Housing"` line in `build_housing`:

```python
    # Latch relief: widen the opening by the wall-to-opening gap for
    # latch_relief_depth below the plate, on all four sides. Doing all four
    # means the switch can be inserted at any rotation.
    if h["latch_relief_depth"] > 0.0:
        relief_span = h["pocket"]      # widen out to the pocket walls
        relief = make_box(
            "Relief",
            (relief_span, relief_span, h["latch_relief_depth"]),
            (0.0, 0.0, pocket_top - h["latch_relief_depth"] / 2.0),
        )
        boolean(body, relief, "DIFFERENCE")

    # Keyring lug on -X: a flat tab with a vertical hole. Overlaps the body by
    # 0.8mm so the union has no coincident faces.
    if h["lug_protrusion"] > 0.0:
        overlap = 0.8
        tab_len = h["lug_protrusion"] + overlap
        tab_x = -(h["body_width"] / 2.0 + h["lug_protrusion"] / 2.0 - overlap / 2.0)
        tab = make_box(
            "Lug",
            (tab_len, h["lug_width"], h["lug_thickness"]),
            (tab_x, 0.0, h["height"] / 2.0),
        )
        boolean(body, tab, "UNION")

        hole = make_cylinder(
            "LugHole",
            h["lug_hole_diameter"] / 2.0,
            h["lug_thickness"] + 2.0,
            (-(h["body_width"] / 2.0 + h["lug_hole_offset"]), 0.0, h["height"] / 2.0),
            64,
        )
        boolean(body, hole, "DIFFERENCE")
```

- [ ] **Step 4: Add the lug hole probe to `housing_report`**

In `housing_report`, add this key to the returned dict, before the verdict block:

```python
        "lug_hole_probe": {
            "diameter_mm": _span_at(
                obj,
                -(h["body_width"] / 2.0 + h["lug_hole_offset"]),
                h["height"] / 2.0,
            ),
        },
```

and add this helper next to `_span`:

```python
def _span_at(obj, x, z):
    """Air span along Y through (x, *, z), sampled at 0.05mm."""
    step = 0.05
    positive = 0.0
    value = 0.0
    while value <= 6.0:
        if point_inside(obj, (x, value, z)):
            break
        positive = value
        value += step
    return round(positive * 2.0, 3)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python tools/blender_exec.py tests/blender/test_housing_lug_relief.py
```

Expected: every check `PASS`, then `ALL CHECKS PASSED`.

- [ ] **Step 6: Run the full build and confirm the report**

```bash
python tools/blender_exec.py models/switch_housing.py
```

Expected: `"VERDICT": "printable"`, `non_manifold_edges: 0`, `dimensions_mm` `[24.5, 19.0, 11.0]`, `lug_hole_probe.diameter_mm` ≈ `4.0`, `stl.size_mm` ≈ `[24.5, 19.0, 11.0]`.

- [ ] **Step 7: Commit**

```bash
git add models/switch_housing.py tests/blender/test_housing_lug_relief.py
git commit -m "feat: four-sided latch relief and vertical-axis keyring lug"
```

---

### Task 5: Snap-on bottom cap, and the matching undercut

The cap is a separate object exported to its own STL. The housing gains the undercut its tongues engage.

**Files:**
- Modify: `models/switch_housing.py` (add `build_cap`, add the undercut to `build_housing`, export both parts)
- Create: `tests/blender/test_cap.py`

**Interfaces:**
- Consumes: Task 4's `build_housing(h)`, `H`.
- Produces:
  - `build_cap(h) -> bpy.types.Object` named `Switch_Housing_Cap`.
  - `cap_report(obj, h) -> dict` with `dimensions_mm`, `mesh`, `tongue_count`, `VERDICT`.
  - `build_housing` now cuts a `h["undercut_depth"]`-deep groove into the pocket walls at `h["undercut_z"]`.
  - `main()` exports `models/switch_housing.stl` and `models/switch_housing_cap.stl`.

- [ ] **Step 1: Write the failing test**

Create `tests/blender/test_cap.py`:

```python
"""Runs inside Blender. Verifies the snap cap and the housing undercut."""

import mxgeom
import switch_housing

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


mxgeom.reset_scene()
h = dict(switch_housing.H)

cap = switch_housing.build_cap(h)
dims = [round(v, 4) for v in cap.dimensions]
check("cap footprint is 19 x 19", dims[0] == 19.0 and dims[1] == 19.0, str(dims))
check("cap is taller than its plate (tongues rise)", dims[2] > h["cap_thickness"], str(dims))

report = mxgeom.mesh_report(cap)
check("cap watertight", report["watertight"], str(report))
check("cap normals outward", report["normals_outward"], str(report))

# Plate spans z 0..1.2 and is solid; tongues rise above it near the walls.
check("cap plate is solid", mxgeom.point_inside(cap, (0.0, 0.0, 0.6)) is True)
check("cap centre is open above the plate",
      mxgeom.point_inside(cap, (0.0, 0.0, h["cap_thickness"] + 1.0)) is False)

tongue_z = h["cap_thickness"] + h["undercut_z"]
tongues = sum(
    1 for x, y in ((7.3, 0.0), (-7.3, 0.0), (0.0, 7.3), (0.0, -7.3))
    if mxgeom.point_inside(cap, (x, y, tongue_z))
)
check("four tongues present", tongues == 4, f"found {tongues}")
check("report agrees on tongue count",
      switch_housing.cap_report(cap, h)["tongue_count"] == 4)

# Housing side: the undercut must be air where the pocket wall otherwise is.
mxgeom.reset_scene()
housing = switch_housing.build_housing(h)
check("housing still watertight with undercut",
      mxgeom.mesh_report(housing)["watertight"], str(mxgeom.mesh_report(housing)))
check("undercut is air at 8.2 from centre",
      mxgeom.point_inside(housing, (8.2, 0.0, h["undercut_z"])) is False)
check("wall above the undercut is material",
      mxgeom.point_inside(housing, (8.2, 0.0, h["undercut_z"] + 2.0)) is True)
check("outer skin is not breached",
      mxgeom.point_inside(housing, (9.4, 0.0, h["undercut_z"])) is True)

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + str(failures)}")
if failures:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tools/blender_exec.py tests/blender/test_cap.py
```

Expected: FAIL with `AttributeError: module 'switch_housing' has no attribute 'build_cap'`.

- [ ] **Step 3: Cut the undercut in `build_housing`**

Insert into `build_housing`, immediately after the pocket boolean and before the opening boolean:

```python
    # Undercut the pocket walls so the cap's tongues have something to catch.
    # Reaches 17.0mm across against a 19.0mm body, so 1.0mm of outer skin is
    # left on each side and the groove never breaks through.
    if h["undercut_depth"] > 0.0:
        span = h["pocket"] + 2.0 * h["undercut_depth"]
        groove = make_box(
            "Undercut",
            (span, span, h["cap_tongue_thickness"] + 0.4),
            (0.0, 0.0, h["undercut_z"]),
        )
        boolean(body, groove, "DIFFERENCE")
```

- [ ] **Step 4: Add `build_cap` and `cap_report`**

Add to `models/switch_housing.py`:

```python
def build_cap(h):
    """Bottom cap: a plate that sits under the housing, plus four snap tongues."""
    plate = make_box(
        "Switch_Housing_Cap",
        (h["body_width"], h["body_depth"], h["cap_thickness"]),
        (0.0, 0.0, h["cap_thickness"] / 2.0),
    )

    # Tongues rise into the pocket and bulge outward at undercut_z to catch the
    # groove. Height reaches 1.2mm past the undercut so the barb has a lead-in.
    tongue_height = h["undercut_z"] + h["cap_tongue_thickness"] + 1.2
    inner_half = h["pocket"] / 2.0
    tongue_len = 6.0
    for index, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
        centre = inner_half - h["cap_tongue_thickness"] / 2.0
        if dx:
            size = (h["cap_tongue_thickness"], tongue_len, tongue_height)
            location = (dx * centre, 0.0, h["cap_thickness"] + tongue_height / 2.0)
        else:
            size = (tongue_len, h["cap_tongue_thickness"], tongue_height)
            location = (0.0, dy * centre, h["cap_thickness"] + tongue_height / 2.0)
        tongue = make_box(f"Tongue{index}", size, location)
        boolean(plate, tongue, "UNION")

        barb_size = (
            (h["cap_tongue_thickness"] + h["undercut_depth"], tongue_len, h["cap_tongue_thickness"])
            if dx else
            (tongue_len, h["cap_tongue_thickness"] + h["undercut_depth"], h["cap_tongue_thickness"])
        )
        barb_centre = centre + h["undercut_depth"] / 2.0
        barb_location = (
            (dx * barb_centre, 0.0, h["cap_thickness"] + h["undercut_z"])
            if dx else
            (0.0, dy * barb_centre, h["cap_thickness"] + h["undercut_z"])
        )
        barb = make_box(f"Barb{index}", barb_size, barb_location)
        boolean(plate, barb, "UNION")

    plate.name = "Switch_Housing_Cap"
    plate.data.name = "Switch_Housing_Cap"
    return plate


def cap_report(obj, h):
    tongue_z = h["cap_thickness"] + h["undercut_z"]
    tongue_count = sum(
        1 for x, y in ((7.3, 0.0), (-7.3, 0.0), (0.0, 7.3), (0.0, -7.3))
        if point_inside(obj, (x, y, tongue_z))
    )
    report = {
        "dimensions_mm": [round(v, 4) for v in obj.dimensions],
        "mesh": mesh_report(obj),
        "tongue_count": tongue_count,
    }
    mesh = report["mesh"]
    if not mesh["watertight"]:
        report["VERDICT"] = "NOT PRINTABLE - mesh is not watertight"
    elif not mesh["normals_outward"]:
        report["VERDICT"] = "NOT PRINTABLE - normals point inward"
    elif tongue_count != 4:
        report["VERDICT"] = f"NOT PRINTABLE - expected 4 tongues, found {tongue_count}"
    else:
        report["VERDICT"] = "printable"
    return report
```

- [ ] **Step 5: Export both parts from `main()`**

In `main()`, replace the single-export block:

```python
    stl = os.path.join(project, "models", "switch_housing.stl")
    export_stl(housing, stl)
    report["stl"] = verify_stl_millimetres(stl)
```

with:

```python
    stl = os.path.join(project, "models", "switch_housing.stl")
    export_stl(housing, stl)
    report["stl"] = verify_stl_millimetres(stl)

    cap = build_cap(H)
    cap_stl = os.path.join(project, "models", "switch_housing_cap.stl")
    export_stl(cap, cap_stl)
    report["cap"] = cap_report(cap, H)
    report["cap"]["stl"] = verify_stl_millimetres(cap_stl)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python tools/blender_exec.py tests/blender/test_cap.py
```

Expected: every check `PASS`, then `ALL CHECKS PASSED`.

- [ ] **Step 7: Run the full build**

```bash
python tools/blender_exec.py models/switch_housing.py
```

Expected: both `"VERDICT": "printable"`, `non_manifold_edges: 0` on each, housing `stl.size_mm` ≈ `[24.5, 19.0, 11.0]`, cap `stl.size_mm` x/y ≈ `19.0`.

- [ ] **Step 8: Commit**

```bash
git add models/switch_housing.py tests/blender/test_cap.py
git commit -m "feat: snap-on bottom cap with four barbed tongues and matching undercut"
```

---

### Task 6: Fit coupons

The plate thickness and opening size cannot be settled from specification. This builds the coupon that settles them on the printer in about four minutes.

**Files:**
- Create: `models/fit_coupons.py`
- Create: `tests/blender/test_coupons.py`

**Interfaces:**
- Consumes: `mxgeom` helpers; `switch_housing.H` for the opening and corner radius defaults.
- Produces:
  - `build_thickness_coupon(thicknesses=(1.4, 1.5, 1.6), opening=14.0, cell=20.0) -> bpy.types.Object` named `Coupon_Thickness`.
  - `build_opening_coupon(openings=(13.9, 14.0, 14.1), thickness, cell=20.0) -> bpy.types.Object` named `Coupon_Opening`.
  - Exports `models/coupon_thickness.stl`; exports `models/coupon_opening.stl` only when `KEYCAB_COUPON_THICKNESS` is set in the environment.

- [ ] **Step 1: Write the failing test**

Create `tests/blender/test_coupons.py`:

```python
"""Runs inside Blender. Verifies the fit coupons."""

import fit_coupons
import mxgeom

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


mxgeom.reset_scene()
thicknesses = (1.4, 1.5, 1.6)
coupon = fit_coupons.build_thickness_coupon(thicknesses=thicknesses, opening=14.0, cell=20.0)

dims = [round(v, 4) for v in coupon.dimensions]
check("tile is 60 x 20", dims[0] == 60.0 and dims[1] == 20.0, str(dims))
check("tile is as tall as the thickest cell", dims[2] == max(thicknesses), str(dims))

report = mxgeom.mesh_report(coupon)
check("coupon watertight", report["watertight"], str(report))
check("coupon normals outward", report["normals_outward"], str(report))

# Cells are centred at x = -20, 0, +20. Each has a 14mm hole and material at its
# own thickness only.
for index, thickness in enumerate(thicknesses):
    cx = -20.0 + index * 20.0
    check(f"cell {thickness} hole is air",
          mxgeom.point_inside(coupon, (cx, 0.0, thickness / 2.0)) is False,
          f"x={cx}")
    check(f"cell {thickness} has material beside the hole",
          mxgeom.point_inside(coupon, (cx + 8.0, 0.0, thickness / 2.0)) is True,
          f"x={cx + 8.0}")
    check(f"cell {thickness} is only {thickness} thick",
          mxgeom.point_inside(coupon, (cx + 8.0, 0.0, thickness + 0.1)) is False,
          f"probed z={thickness + 0.1}")
    check(f"cell {thickness} hole is 14 wide: air at 6.8",
          mxgeom.point_inside(coupon, (cx + 6.8, 0.0, thickness / 2.0)) is False)
    check(f"cell {thickness} hole is 14 wide: material at 7.2",
          mxgeom.point_inside(coupon, (cx + 7.2, 0.0, thickness / 2.0)) is True)

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + str(failures)}")
if failures:
    raise SystemExit(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tools/blender_exec.py tests/blender/test_coupons.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'fit_coupons'`.

- [ ] **Step 3: Write minimal implementation**

Create `models/fit_coupons.py`:

```python
"""Fit coupons that settle the two tolerances the spec leaves open.

Spec: docs/superpowers/specs/2026-08-10-keycap-keychain-design.md

Coupon 1 varies the plate thickness at a fixed 14.0mm opening. Coupon 2 varies
the opening at whichever thickness coupon 1 selected, and is only needed if
every cell of coupon 1 is uniformly loose or uniformly tight.
"""

import json
import os

import bpy

import mxgeom
from mxgeom import (
    boolean, export_stl, make_box, make_loft, mesh_report, reset_scene,
    rounded_rect, verify_stl_millimetres,
)

CORNER_R = 0.5
CORNER_SEGMENTS = 8
LABEL_DEPTH = 0.4


def _cell(name, cell, thickness, opening, centre_x):
    """One coupon cell: a plate of `thickness` with a rounded-square opening."""
    tile = make_box(name, (cell, cell, thickness), (centre_x, 0.0, thickness / 2.0))
    outline = rounded_rect(opening, opening, CORNER_R, CORNER_SEGMENTS)
    shifted = [(x + centre_x, y) for x, y in outline]
    cutter = make_loft(f"{name}_Cut", shifted, -1.0, shifted, thickness + 1.0)
    boolean(tile, cutter, "DIFFERENCE")
    return tile


def _emboss_bars(target, count, thickness, centre_x, cell):
    """Mark a cell with `count` raised bars, readable without text rendering."""
    for index in range(count):
        bar = make_box(
            f"Bar_{centre_x}_{index}",
            (1.2, 4.0, LABEL_DEPTH),
            (centre_x - cell / 2.0 + 2.5 + index * 2.0,
             -cell / 2.0 + 3.0,
             thickness + LABEL_DEPTH / 2.0),
        )
        boolean(target, bar, "UNION")


def build_thickness_coupon(thicknesses=(1.4, 1.5, 1.6), opening=14.0, cell=20.0):
    """Flat tile of cells, one per candidate plate thickness."""
    tile = None
    for index, thickness in enumerate(thicknesses):
        centre_x = (index - (len(thicknesses) - 1) / 2.0) * cell
        piece = _cell(f"Cell{index}", cell, thickness, opening, centre_x)
        _emboss_bars(piece, index + 1, thickness, centre_x, cell)
        if tile is None:
            tile = piece
        else:
            boolean(tile, piece, "UNION")
    tile.name = "Coupon_Thickness"
    tile.data.name = "Coupon_Thickness"
    return tile


def build_opening_coupon(thickness, openings=(13.9, 14.0, 14.1), cell=20.0):
    """Flat tile of cells, one per candidate opening size, at one thickness."""
    tile = None
    for index, opening in enumerate(openings):
        centre_x = (index - (len(openings) - 1) / 2.0) * cell
        piece = _cell(f"OCell{index}", cell, thickness, opening, centre_x)
        _emboss_bars(piece, index + 1, thickness, centre_x, cell)
        if tile is None:
            tile = piece
        else:
            boolean(tile, piece, "UNION")
    tile.name = "Coupon_Opening"
    tile.data.name = "Coupon_Opening"
    return tile


def _verdict(report):
    if not report["mesh"]["watertight"]:
        return "NOT PRINTABLE - mesh is not watertight"
    if not report["mesh"]["normals_outward"]:
        return "NOT PRINTABLE - normals point inward"
    return "printable"


def main():
    project = os.environ.get(
        "KEYCAB_PROJECT", r"C:\Users\user\orca\projects\keycab-3dprint"
    )
    reset_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"

    out = {}

    thicknesses = (1.4, 1.5, 1.6)
    coupon = build_thickness_coupon(thicknesses=thicknesses)
    entry = {
        "cells": [{"bars": i + 1, "thickness_mm": t} for i, t in enumerate(thicknesses)],
        "dimensions_mm": [round(v, 4) for v in coupon.dimensions],
        "mesh": mesh_report(coupon),
    }
    entry["VERDICT"] = _verdict(entry)
    path = os.path.join(project, "models", "coupon_thickness.stl")
    export_stl(coupon, path)
    entry["stl"] = verify_stl_millimetres(path)
    out["coupon_thickness"] = entry

    chosen = os.environ.get("KEYCAB_COUPON_THICKNESS")
    if chosen:
        reset_scene()
        openings = (13.9, 14.0, 14.1)
        second = build_opening_coupon(float(chosen), openings=openings)
        entry2 = {
            "chosen_thickness_mm": float(chosen),
            "cells": [{"bars": i + 1, "opening_mm": o} for i, o in enumerate(openings)],
            "dimensions_mm": [round(v, 4) for v in second.dimensions],
            "mesh": mesh_report(second),
        }
        entry2["VERDICT"] = _verdict(entry2)
        path2 = os.path.join(project, "models", "coupon_opening.stl")
        export_stl(second, path2)
        entry2["stl"] = verify_stl_millimetres(path2)
        out["coupon_opening"] = entry2
    else:
        out["coupon_opening"] = "skipped - set KEYCAB_COUPON_THICKNESS to build it"

    print("COUPON_REPORT_START")
    print(json.dumps(out, indent=2))
    print("COUPON_REPORT_END")


if __name__ == "__blender_mcp__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python tools/blender_exec.py tests/blender/test_coupons.py
```

Expected: every check `PASS`, then `ALL CHECKS PASSED`.

- [ ] **Step 5: Build the coupon STL**

```bash
python tools/blender_exec.py models/fit_coupons.py
```

Expected: `coupon_thickness.VERDICT` is `printable`, `stl.size_mm` ≈ `[60.0, 20.0, 2.0]` (1.6 plate + 0.4 emboss), `coupon_opening` reported as skipped. The cell with 1 bar is 1.4 mm, 2 bars is 1.5 mm, 3 bars is 1.6 mm.

- [ ] **Step 6: Commit**

```bash
git add models/fit_coupons.py tests/blender/test_coupons.py
git commit -m "feat: plate-thickness and opening fit coupons"
```

---

### Task 7: Reusable slicing script

The working slice invocation currently exists only as an ad-hoc shell command. Capture it, including the two corrections that were needed to make it produce a fast, correctly-heated print, so the housing, cap and coupons can each be sliced repeatably.

**Files:**
- Create: `tools/slice_part.ps1`
- Modify: `README.md` (add a "Slicing and printing" section)

**Interfaces:**
- Consumes: `tools/flatten_orca_preset.py` (existing), the OrcaSlicer portable install at `C:\Users\user\AppData\Local\Programs\OrcaSlicer-portable`.
- Produces: `tools/slice_part.ps1 -Stl <path> -Out <name.gcode.3mf> [-Process <preset>] [-Filament <preset>] [-BedType <type>] [-BrimWidth <mm>]` writing into `gcode/`, and echoing layer count, wall speed, bed temperature, support flag, estimated time and grams.

- [ ] **Step 1: Write the failing test**

There is no unit-test harness for PowerShell here, so the test is the script's own self-check on a known input. Run:

```bash
powershell -File tools/slice_part.ps1 -Stl models/coupon_thickness.stl -Out coupon_thickness.gcode.3mf
```

Expected before implementation: `The term 'tools/slice_part.ps1' is not recognized`.

- [ ] **Step 2: Write the implementation**

Create `tools/slice_part.ps1`:

```powershell
<#
.SYNOPSIS
  Slice one STL for the Bambu Lab A1 mini with the vendor's real high-speed values.

.NOTES
  Two corrections are baked in because both silently ruin a print:

  1. OrcaSlicer's bundled presets are `inherits` deltas. Passing a leaf process
     JSON to --load-settings loads only the delta and falls back to built-in
     defaults -- 0.2mm layers at 60mm/s instead of the vendor's 0.28mm at
     200mm/s. tools/flatten_orca_preset.py resolves the chain first. The MACHINE
     preset must stay the un-flattened leaf; the CLI rejects a flattened one.
  2. --curr-bed-type must be passed explicitly. The default is "Cool Plate",
     which commands a 35C bed; PLA on the A1 mini's textured PEI plate needs 65C.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Stl,
  [Parameter(Mandatory = $true)][string]$Out,
  [string]$Process  = "0.28mm Extra Draft @BBL A1M",
  [string]$Filament = "Generic PLA High Speed @BBL A1M",
  [string]$Machine  = "Bambu Lab A1 mini 0.4 nozzle",
  [string]$BedType  = "Textured PEI Plate",
  [double]$BrimWidth = 3,
  [string]$OrcaDir  = "C:\Users\user\AppData\Local\Programs\OrcaSlicer-portable"
)

$ErrorActionPreference = 'Stop'

$root    = Split-Path -Parent $PSScriptRoot
$outDir  = Join-Path $root 'gcode'
$flatDir = Join-Path $outDir '_presets'
$profiles = Join-Path $OrcaDir 'resources\profiles'
$exe      = Join-Path $OrcaDir 'orca-slicer.exe'

foreach ($p in @($exe, $profiles, $Stl)) {
  if (-not (Test-Path $p)) { throw "not found: $p" }
}
foreach ($d in @($outDir, $flatDir)) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

python (Join-Path $PSScriptRoot 'flatten_orca_preset.py') $profiles 'BBL' `
  --machine $Machine --process $Process --filament $Filament --outdir $flatDir
if ($LASTEXITCODE -ne 0) { throw "preset flattening failed" }

$leafMachine = Join-Path $profiles "BBL\machine\$Machine.json"
if (-not (Test-Path $leafMachine)) { throw "machine preset not found: $leafMachine" }

$stlFull = (Resolve-Path $Stl).Path
$argStr =
  '--load-settings "' + $leafMachine + ';' + (Join-Path $flatDir 'process.json') + '"' +
  ' --load-filaments "' + (Join-Path $flatDir 'filament.json') + '"' +
  ' --curr-bed-type "' + $BedType + '"' +
  ' --slice 0 --brim-type outer_only --brim-width ' + $BrimWidth +
  ' --ensure-on-bed --export-3mf "' + $Out + '"' +
  ' --outputdir "' + $outDir + '" "' + $stlFull + '"'

$stdout = Join-Path $outDir '_slice.out.log'
$stderr = Join-Path $outDir '_slice.err.log'
Set-Content -Path $stdout -Value '' -Encoding utf8
Set-Content -Path $stderr -Value '' -Encoding utf8

$proc = Start-Process -FilePath $exe -ArgumentList $argStr `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
  -PassThru -NoNewWindow -Wait

if ($proc.ExitCode -ne 0) {
  Write-Output "SLICE FAILED (exit $($proc.ExitCode))"
  Get-Content $stdout; Get-Content $stderr
  exit 1
}

$gcode = Join-Path $outDir 'plate_1.gcode'
if (-not (Test-Path $gcode)) { throw "slicer produced no plate_1.gcode" }

Write-Output "sliced -> $(Join-Path $outDir $Out)"
Write-Output '--- verify before printing ---'
Select-String -Path $gcode -Pattern '^; (total layer number|layer_height =|outer_wall_speed|nozzle_temperature =|curr_bed_type|enable_support|brim_width|printer_model)' |
  ForEach-Object { '  ' + $_.Line }
Select-String -Path $gcode -Pattern '^(M190)' | Select-Object -First 1 |
  ForEach-Object { '  ' + $_.Line }
Select-String -Path $gcode -Pattern '(model printing time|filament used \[g\])' |
  Where-Object { $_.Line -match '^;' } | ForEach-Object { '  ' + $_.Line.Trim() }
```

- [ ] **Step 3: Run it and check the header**

```bash
powershell -File tools/blender_server.ps1 status
powershell -File tools/slice_part.ps1 -Stl models/coupon_thickness.stl -Out coupon_thickness.gcode.3mf
```

Expected in the verify block: `layer_height = 0.28`, `outer_wall_speed = 200`, `curr_bed_type = Textured PEI Plate`, `M190 S65`, `enable_support = 0`, `printer_model = Bambu Lab A1 mini`, plus a time and a gram figure. **If `layer_height` reads 0.2 or `outer_wall_speed` reads 60, the preset chain did not resolve — do not print it.**

- [ ] **Step 4: Slice the housing and the cap**

```bash
powershell -File tools/slice_part.ps1 -Stl models/switch_housing.stl -Out switch_housing.gcode.3mf
powershell -File tools/slice_part.ps1 -Stl models/switch_housing_cap.stl -Out switch_housing_cap.gcode.3mf
```

Expected: both report `enable_support = 0`. The housing STL is already plate-face-down because `build_housing` puts the plate at the top and the slicer does not flip it — confirm `stl.size_mm` z is `11.0` and that the reported time is single-digit minutes.

- [ ] **Step 5: Document it**

Add to `README.md`, after the "Everyday use" section:

```markdown
## Slicing and printing

```powershell
powershell -File tools\slice_part.ps1 -Stl models\switch_housing.stl -Out switch_housing.gcode.3mf
python tools\bambu_print.py   # needs BAMBU_HOST / BAMBU_SERIAL / BAMBU_CODE / BAMBU_FILE
```

Two settings silently ruin a print if left at their defaults, so `slice_part.ps1`
sets both and prints them back for checking:

- **Preset inheritance.** OrcaSlicer's bundled presets are `inherits` deltas.
  Handing a leaf process JSON to `--load-settings` loads the delta only and falls
  back to built-in defaults — 0.2 mm layers at 60 mm/s rather than the vendor's
  0.28 mm at 200 mm/s. `tools/flatten_orca_preset.py` resolves the chain first.
  The machine preset must stay un-flattened; the CLI rejects a flattened one.
- **Bed type.** The default is `Cool Plate`, which commands a 35 °C bed. PLA on
  the A1 mini's textured PEI plate needs 65 °C, and at 35 °C a small part with
  little contact area will let go.
```

- [ ] **Step 6: Commit**

```bash
git add tools/slice_part.ps1 README.md
git commit -m "feat: reusable slicing script with preset flattening and bed type"
```

---

## Post-implementation: settle the tolerances on the printer

Not code, but the plan is not finished without it. In order:

1. Print `coupon_thickness.gcode.3mf` (~4 min). Try the switch in all three cells.
2. Set `H["plate_thickness"]` in `models/switch_housing.py` to the cell that latches with a clean click, then rebuild and re-slice.
3. If all three cells are uniformly loose or tight, build coupon 2 with
   `KEYCAB_COUPON_THICKNESS=<best>` and repeat for the opening, then set `H["opening"]`.
4. Print the housing and cap. Expect one or two iterations on `H["undercut_depth"]`
   from its 0.6 mm starting value: a cap that falls off wants more, a tongue that
   snaps wants less.

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
| --- | --- |
| Closed box housing, all dimensions | 3, 4 |
| Two-piece retention: 1.5 mm plate + MX latches | 3 (plate/opening), 4 (relief) |
| Removable snap bottom cap, undercut 0.6 @ 1.5 | 5 |
| Keyring lug, vertical hole axis | 4 |
| No individual pin holes (flat pocket floor) | 3 — pocket is a plain box difference |
| Click travel (nothing above plate level) | 3 — asserted by `plate is solid at the edge` plus the absence of any geometry above `height` |
| Coupon 1 (thickness) and coupon 2 (opening) | 6 |
| Verification: watertight, normals, ray-cast thickness, ASCII sections, lug hole, STL bbox | 3, 4, 5, 6 |
| Print orientation, no support | 7 |
| Out of scope items | not implemented, as intended |

Gap found and closed: the spec's shared-helper reuse was implicit; Tasks 1 and 2 exist because `keycap.py`'s helpers are unimportable as-is.

**2. Placeholder scan** — no `TBD`/`TODO`/"handle edge cases"/"similar to Task N". Every code step carries real code. Coupon 2 is conditional on a stated trigger, not deferred.

**3. Type consistency** — `H` keys are spelled identically in Tasks 3, 4, 5 and the post-implementation notes. `build_housing`/`build_cap`/`housing_report`/`cap_report`/`build_thickness_coupon`/`build_opening_coupon` are used with the signatures declared in their Interfaces blocks. `cross_sections` takes `(obj, half_extent, heights, step)` everywhere after Task 2, including the updated `keycap.py` call site. `_span(obj, z, axis)` and `_span_at(obj, x, z)` are distinct helpers with distinct signatures.
