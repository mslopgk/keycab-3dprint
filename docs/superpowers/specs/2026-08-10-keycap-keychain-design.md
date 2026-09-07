# Keycap keychain with a mounted MX switch — design

Date: 2026-08-10
Status: approved, ready for implementation planning

## Goal

A keychain built around a real MX-compatible switch, with the existing
`models/keycap.py` keycap on top. The switch clicks, because the switch is
retained the way a keyboard retains it rather than glued into a shell.

## Decisions

Three questions were settled with the user up front. Each is recorded with the
option chosen, because they constrain everything downstream.

| Question | Chosen |
| --- | --- |
| Housing silhouette | Closed box — switch pins fully enclosed, nothing to snag in a pocket |
| Switch retention | Two pieces: MX latch retention on a 1.5 mm plate + removable snap-on bottom cap |
| Keyring attachment | Lug on one side with a 4.0 mm round hole |

Rejected and why:

- **Open plate frame** (bare 1.5 mm plate, no walls) — most keyboard-like, fastest
  to print, but leaves the pins exposed.
- **Press-fit pocket** (grip the 15.6 mm body, ignore the latches) — no tolerance
  headroom; 0.1 mm out and it either will not enter or does not hold.
- **One-piece closed box** — sturdiest and a single print, but with the bottom
  closed the latches cannot be reached, so the switch is in permanently.
- **Corner through-hole** / **strap slot** for the keyring — more compact, but a
  split ring in a corner hole rubs the keycap, and a strap slot cannot take a
  split ring at all.

## Parts

### A. Housing

| Parameter | Value | Note |
| --- | --- | --- |
| body footprint | 19.0 × 19.0 mm | pocket 15.8 + 2 × 1.6 wall |
| footprint incl. lug | 24.5 × 19.0 mm | |
| height | 11.0 mm | plate 1.5 + pocket 9.5 |
| top plate thickness | 1.5 mm | what the MX latches grab |
| plate opening | 14.0 × 14.0 mm, corner R0.5 | standard MX plate cutout |
| inner pocket | 15.8 × 15.8 mm | switch body 15.6 + 0.1 per side |
| pocket depth | 9.5 mm | below the plate underside |
| wall thickness | 1.6 mm | |
| latch relief | 1.0 mm deep groove below the opening, on **all four** sides | space for the latches to flex, whichever way the switch is rotated |
| lug | flat tab, 5.5 mm protrusion, 7.0 mm wide, 3.0 mm thick | see hole axis below |
| lug hole | 4.0 mm diameter, axis **vertical** (parallel to the box height), centre 2.0 mm out from the body face, 1.5 mm material around it | |

### Lug hole axis

Vertical, i.e. punched through the flat face of the tab rather than through its
edge. Two consequences, both wanted:

- Printed plate-down, a vertical hole needs no bridging. A horizontal hole would
  have to bridge across its own top.
- The keycap faces up when the keychain lies flat, instead of sideways.

The tab is deliberately offset to one side of the body, so the split ring never
touches the keycap. The assembly hangs slightly tilted because the centre of mass
is offset from the hole; this is accepted.

### B. Snap bottom cap

| Parameter | Value |
| --- | --- |
| plate | 19.0 × 19.0 × 1.2 mm, sits under the housing (assembled height 12.2 mm) |
| snap tongues | 4, one per side, 0.8 mm thick, rising into the pocket |
| undercut on housing inner wall | 0.6 mm, positioned 1.5 mm above the housing's bottom face |

### No individual pin holes

The pocket floor is flat and unbroken. The exact coordinates of the 5-pin
plastic posts and the metal pins are **not** reliably known here, and a hole
drilled at a wrong coordinate makes the part scrap. A generous flat pocket
accepts 3-pin and 5-pin switches alike without depending on those coordinates,
which also means one housing covers both switch types.

## Click travel

Nothing rises above plate level: the top face is a flat 19 × 19 plate with a
single 14 mm hole. The 18 mm keycap descends onto it unobstructed.

The argument for full 4 mm travel is structural, not arithmetic — the switch sits
in a standard 1.5 mm plate cutout, so its height relative to the plate is
identical to a keyboard's. No absolute stem or housing heights need to be known
or matched.

## Open tolerances, and how they get closed

Two values cannot be settled from specification alone:

1. **Effective plate thickness.** At a 0.28 mm layer height, a nominal 1.5 mm
   plate quantises to whatever the slicer rounds it to.
2. **Effective opening size.** Print shrinkage and extrusion width shift the
   14.0 mm cutout by an unknown fraction of a tenth.

Both are resolved empirically before the housing is printed:

**Coupon 1 — plate thickness.** One flat tile, 20 × 60 × 1.6 mm, three 20 × 20 mm
cells with plate thickness 1.4 / 1.5 / 1.6 mm at a fixed 14.0 mm opening, each
cell embossed with its thickness. Print flat, no support, roughly 4 minutes. The
cell where the switch latches with a clean click sets `plate_thickness`.

**Coupon 2 — opening (only if needed).** If every cell in coupon 1 is uniformly
loose or uniformly tight, a second coupon varies the opening 13.9 / 14.0 / 14.1
at the best thickness.

**Snap fit** will very likely need one or two iterations. The 0.6 mm undercut is a
starting value: too loose and the cap falls off, too tight and a tongue snaps.
Dial it on a coupon rather than on the full housing.

## Verification

The build script performs the same automated checks the keycap script does, for
both parts:

- watertight (no non-manifold edges, no loose vertices) and normals outward
- plate thickness measured by ray-cast at four points clear of the opening
- ASCII cross-sections at three heights — through the plate, through the pocket,
  and near the bottom face — confirming the 14.0 opening, the 15.8 pocket and the
  1.6 wall
- lug hole diameter measured
- exported STL re-read and its bounding box reported, to catch unit slips

A run that is not watertight still writes the STL for inspection but reports
`VERDICT: NOT PRINTABLE`.

## Print plan

| Part | Orientation | Support |
| --- | --- | --- |
| housing | plate face down on the bed, pocket opening upward | none |
| bottom cap | flat | none |
| coupons | flat | none |

Housing plate-down puts the flat plate face against the bed and grows the walls
upward, so the latch relief grooves and the pocket are never overhangs.

## Out of scope

Legends on the keycap, multi-unit sizes, a switch other than MX-compatible, and
any change to the existing keycap geometry. The keycap's own open question — the
1.35 mm cross slot fit — is tracked separately against the first keycap print and
does not affect this housing.
