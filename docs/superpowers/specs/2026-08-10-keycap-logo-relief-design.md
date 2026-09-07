# Raised church-wave logo on the keycap top — design

Date: 2026-08-10
Status: approved, ready for implementation planning

## Goal

Emboss the church-wave logo on the keycap top as a real raised relief, uniform
0.5 mm proud of the dished surface, printable with the existing 0.4 mm nozzle and
no support.

Source art: `C:\Users\user\Documents\카카오톡 받은 파일\church-wave-logo-03-minimal-line.svg`
(2048 × 2048 viewBox; its metadata records it as Recraft AI output).

## What the source file actually contains

The filename says "minimal-line" but the paths are **filled**, not stroked. The
navy disc is overlaid by large white shapes that carve the mark out of it, so the
region that would be embossed — navy minus white — is a set of thin strokes.
Ten paths import:

| Path role | Identified by | Action |
| --- | --- | --- |
| Background rect | its X extent equals the widest of all paths | discard |
| Navy disc, `rgb(25,8,76)` | darkest remaining path by luma | the figure |
| 2 white shapes | max dimension ≥ 2 % of the disc span | subtract from the disc |
| 3 pale slivers, `rgb(122,115,143)` / `rgb(193,190,201)` | max dimension < 2 % of the disc span; measured 0.0006–0.0061 Blender units | discard |

The slivers are anti-aliasing residue from the generator. At keycap scale they are
a few microns across and would only inject degenerate geometry into the booleans.

**Selection is by rule, never by object name.** The importer names paths
`Curve`, `Curve.001` … in file order, which is not a contract.

## Why the logo cannot be used as drawn

Measured at 12 mm diameter, sampled at 0.05 mm and eroded by the nozzle radius:

| | as drawn | +0.15 mm | +0.25 mm |
| --- | --- | --- | --- |
| ideal area | 19.45 mm² | 37.65 mm² | 49.55 mm² |
| stroke area lost to the nozzle | 8.55 mm² (44 %) | 1.62 mm² | **0.00 mm²** |
| gap area the nozzle fills in | — | 0.46 mm² | 0.59 mm² |
| fidelity | unusable | 94.5 % | **98.8 %** |

As drawn, strokes are ~0.2 mm — half a nozzle width — and 94 % of the logo area
is thinner than 0.4 mm. The cross and the outer ring disappear entirely; only the
thick lower-left wave arc survives. Scaling cannot fix it: the plateau is
13.6 × 13.2 mm, and full fidelity would need roughly 22–25 mm.

At **+0.15 mm** the cross's horizontal arms are still dropped. At **+0.25 mm**
nothing is dropped and the red merge artefacts are confined to sharp interior
junctions being rounded off. The mark reads as a bolder weight of itself.

**Decision: 12.0 mm diameter, strokes dilated by +0.25 mm.**

Caveat to carry into implementation: the erosion used a 4-connected (diamond)
structuring element, which is contained in the disc of the same radius, so it
removes slightly less than a true disc would. The survival figures are therefore
mildly optimistic and must be confirmed on the first print.

## Why the print orientation changes

The keycap is currently printed flipped, top face on the plate. A raised logo
cannot work that way, and the reason is geometric rather than a matter of taste.

The dish is a cylinder with its axis along X, so the top surface drops only in Y.
Measured on the built mesh: rim plane `z = 8.5522`, dish centre `z = 7.7000`.
For a logo whose top is one flat plane at the rim height, the relief available is:

| position | relief |
| --- | --- |
| along X, any offset | 0.852 mm |
| y = ±3 | 0.661 mm |
| y = ±5 | 0.336 mm |
| y = ±6 | **0.111 mm** |

0.111 mm is below both the 0.28 mm layer height and the 0.20 mm first layer, so
the ring's top and bottom would vanish while its left and right stood 0.852 mm
proud — a 7.7× asymmetry.

Giving the logo a dish-parallel top instead makes the relief uniform, but that
surface sits below the bed plane once the part is flipped, which is impossible.
**Uniform relief and flipped printing are mutually exclusive.**

**Decision: print the logo variant right side up** — bottom rim and stem base on
the plate, logo uppermost.

Right side up, the only surface that would need support is the cavity ceiling,
which currently runs parallel to the dish at about 6.4° from horizontal.
**Decision: make the ceiling flat at `z = 6.2`** so it becomes a ~15 mm bridge,
which needs no support. The cost is a roof that is no longer a constant
thickness: 1.5 mm at the centre, 2.24 mm at the plateau edge. For a keychain the
extra material does not matter.

Everything else prints in its best orientation: the outer walls narrow going up
(self-supporting), the stem grows from the plate, the ribs are ~3 mm bridges, the
cross socket's roof is a trivial bridge, and the visible top surface is printed
last.

## Separate variant, not a modification

The plain keycap stays exactly as it is. The logo version is a second output.

This is not tidiness: Task 2 of `docs/superpowers/plans/2026-08-10-mx-switch-keychain.md`
uses the current STL hashes (`f567510240023cb5a7808314c5a7bf60` and
`51c9fe26924c15bf2439d854c985276d`) as its refactor regression gate. Changing the
existing outputs would break that check.

- `models/keycap_1u_r3.stl` — unchanged, flipped-print orientation, no logo
- `models/keycap_1u_r3_logo.stl` — flat ceiling, right side up, logo

The logo and the flat ceiling are enabled together by one parameter block; the
ceiling shape follows from the print orientation, which follows from the logo.

## Construction

The relief is cut from between two copies of the dish cylinder rather than
extruded to a fixed height, which is what makes the relief uniform:

```
logo_2d    = disc − white_cutters, dilated +0.25 mm, scaled to 12.0 mm
logo_prism = logo_2d extruded well past both surfaces
logo_solid = logo_prism ∩ dish_cutter − dish_cutter_raised_by_0.5mm
keycap     = keycap ∪ logo_solid
```

`dish_cutter` is the same cylinder the keycap already uses for the dish, so its
lower boundary *is* the top surface. Raising a second copy by 0.5 mm gives the
logo's top surface, parallel by construction.

Dilation: try `Curve.offset` on the composed 2D curve first and measure the
resulting stroke widths. If it does not offset the fill correctly, fall back to
rasterising at 0.02 mm and tracing contours — 20× finer than the 0.4 mm the
printer can resolve, so the faceting is invisible in the print.

## Accepted consequence: the logo crests the rim

At y = ±6 the dish surface is at 8.4416, so the logo top reaches 8.9416 — about
0.39 mm above the rim plane at 8.5522. The ring's top and bottom therefore stand
proud of the keycap's top edge, giving a medallion look from the side, and the
part's height becomes 8.94 mm instead of 8.5522 mm.

Printing right side up means this costs nothing technically; it is purely
appearance, and it is accepted. The alternative — shrinking the logo to 8 mm so it
tucks under the rim — was rejected because the stroke-width evidence was gathered
at 12 mm and would have to be redone.

## Verification

Same automated gates as the keycap, plus logo-specific ones:

- watertight (no non-manifold edges, no loose vertices) and normals outward
- relief height ray-cast at eight points spread around the logo; every one must
  read 0.5 mm ± 0.02 mm — this is the check that would have caught the flat-top
  defect
- minimum stroke width on the **final** mesh, measured by rasterising and
  eroding; must be ≥ 0.45 mm, giving margin over the 0.4 mm nozzle
- ceiling flatness: ray-cast up from inside the cavity at several points, all
  returning the same z
- roof thickness measured at the centre (expect 1.5 mm) and at the plateau edge
  (expect 2.24 mm)
- ASCII cross-section just below the top surface, showing the logo outline
- exported STL re-read; bounding box must be 18.0 × 18.0 × 8.94 mm
- top-down render for a visual check against the reference art

A run that fails watertightness or the relief-height check still writes the STL
for inspection but reports `VERDICT: NOT PRINTABLE`.

## Print settings

Right side up, no support, brim 3 mm, 0.28 mm layers, textured PEI plate at
65 °C, sliced through `tools/slice_part.ps1` from the keychain plan.

## Out of scope

Text legends, a second filament colour for the logo, any change to the plain
keycap or to the switch housing, and re-cutting the source SVG by hand.
