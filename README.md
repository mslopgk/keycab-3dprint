# keycab-3dprint

Parametric keycap modelling in Blender 5.2, driven programmatically.

## Layout

| Path | What it is |
| --- | --- |
| `tools/blender_mcp_ext/` | Blender extension exposing the `blender-mcp` socket protocol on `127.0.0.1:9876` |
| `tools/install_extension.py` | Copies the extension into Blender's user extension repo and enables it |
| `tools/serve_headless.py` | Runs the command server inside `blender --background` (no GUI, no manual Connect) |
| `tools/blender_server.ps1` | start / stop / restart / status / log for that headless server |
| `tools/blender_exec.py` | Send Python (or ask for scene info / a render) to the running Blender |
| `tools/mcp_client_test.py` | Protocol conformance + regression tests |
| `models/keycap.py` | Parametric Cherry MX 1u keycap: build, verify, export |
| `models/keycap_1u_r3.stl` | Printable output, literal millimetres |
| `renders/` | iso / front / bottom / underside previews |

## Setup, once

```powershell
python -m pip install uv                                    # provides uvx
blender --background --python tools\install_extension.py     # install the extension
claude mcp add blender -s user -e BLENDER_MCP_DISABLE_TELEMETRY=true `
  -e BLENDER_HOST=127.0.0.1 -e BLENDER_PORT=9876 -- uvx blender-mcp
```

`BLENDER_MCP_DISABLE_TELEMETRY=true` matters: upstream `blender-mcp` otherwise
uploads your prompt text and viewport screenshots to a remote endpoint
(`blender_mcp/telemetry.py`).

## Everyday use

```powershell
powershell -File tools\blender_server.ps1 start
python tools\blender_exec.py models\keycap.py     # rebuild, verify, export, render
python tools\blender_exec.py --scene-info
python tools\blender_exec.py --screenshot out.png --max-size 900
powershell -File tools\blender_server.ps1 stop
```

Restart the server after editing `tools/blender_mcp_ext/__init__.py` — the
headless entry point imports that module once at startup.

## Notes for this Blender build

Things that are specific to 5.2 here and cost real debugging time:

- **Legacy add-ons do not load.** `addon_utils.paths()` returns only
  `addons_core`; the user `scripts/addons` directory is no longer scanned. An
  add-on must ship as an extension with a `blender_manifest.toml`.
- **Only `BLENDER_EEVEE` is available** as a render engine — no Workbench, no
  Cycles. So there is no lighting-independent engine to fall back on, and
  previews have to bring their own lights.
- **`bpy.app.timers` never fire under `--background`.** Anything that relies on
  a timer to service work from another thread must pump on the main thread
  instead; that is what `serve_headless.py` does.
- **The default 0.1 m `clip_start` swallows millimetre-scale parts.** A camera
  framing an 18 mm keycap sits ~50 mm away, so the whole subject falls inside
  the near plane and renders as an empty background. The extension scales
  clipping to the subject.

## Keycap geometry

Modelled at 1 Blender unit = 1 mm, exported with `use_scene_unit=False` and
`global_scale=1.0`, so the STL carries literal millimetres.

Current parameters (all in `P` at the top of `models/keycap.py`):

| Parameter | Value | Note |
| --- | --- | --- |
| base | 18.0 × 18.0 mm | 1u spacing is 19.05 mm; the cap is undersized so neighbours don't rub |
| top plateau | 13.6 × 13.2 mm | Cherry-like R3, no front-to-back tilt |
| height | 8.6 mm | 8.55 mm after the dish |
| dish | 0.9 mm deep, R 24.65 mm | cylindrical, axis along X, so it scoops front-to-back |
| side wall | 1.35 mm | |
| roof | 1.5 mm | held constant under the dish, measured at three points |
| stem | ⌀5.5 mm | |
| MX cross | 4.1 × 1.35 mm, 4.0 mm deep | 1.30 grips hard but splits brittle filament; 1.40 goes loose |
| ribs | 4 × 1.0 mm, z 3.6 → 5.8 | start above the switch's top housing so they can't collide |

### Verification the build script performs

- watertight (no non-manifold edges, no loose verts) and normals outward
- roof thickness by ray-cast at three points clear of the stem and ribs
- ASCII cross-sections at z = 0.4 / 2.0 / 5.0 / 7.2 mm, which is the only way to
  confirm the cross socket and ribs — the cavity is unlit and invisible in a render
- the exported STL is re-read and its bounding box reported, to catch unit slips

A run that is not watertight still writes the STL for inspection but reports
`VERDICT: NOT PRINTABLE`.

### Not yet decided

Print orientation, tolerance for your specific printer/filament, row profile
(everything here is R3-ish and untilted), legends, and multi-unit sizes
(2u, shift, spacebar).
