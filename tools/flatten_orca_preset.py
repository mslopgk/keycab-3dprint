"""Flatten an OrcaSlicer system preset by resolving its `inherits` chain.

OrcaSlicer's bundled presets are deltas: "0.28mm Extra Draft @BBL A1M" only
stores what differs from its parent. Handing such a leaf file to
`orca-slicer --load-settings` loads the delta and silently falls back to
built-in defaults for everything else -- you get 0.2 mm layers and 60 mm/s walls
instead of the vendor's real high-speed values.

This walks `inherits` up to the root, merges parent-first, and writes one
self-contained JSON per preset.

    python tools/flatten_orca_preset.py <resources/profiles> <vendor> \
        --machine "Bambu Lab A1 mini 0.4 nozzle" \
        --process "0.28mm Extra Draft @BBL A1M" \
        --filament "Generic PLA High Speed @BBL A1M" \
        --outdir <dir>
"""

import argparse
import json
import os
import sys

# Keys describing the preset's place in the inheritance graph, not a setting.
# `from` is deliberately NOT here: the CLI rejects a config without it
# ("...json's from  unsupported"). The flattened file is standalone, so it is
# re-stamped as a user preset in write().
META_KEYS = {"inherits", "setting_id"}


def load_index(profiles_dir, vendor):
    """name -> parsed json, for every preset file belonging to the vendor."""
    index = {}
    vendor_root = os.path.join(profiles_dir, vendor)
    for sub in ("machine", "process", "filament"):
        directory = os.path.join(vendor_root, sub)
        if not os.path.isdir(directory):
            continue
        for entry in os.listdir(directory):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(directory, entry)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception as exc:
                print(f"  skip {entry}: {exc}", file=sys.stderr)
                continue
            name = data.get("name") or os.path.splitext(entry)[0]
            index[name] = (path, data)
    return index


def flatten(name, index, seen=None):
    seen = seen or []
    if name in seen:
        raise SystemExit(f"inherits cycle: {' -> '.join(seen + [name])}")
    if name not in index:
        raise SystemExit(f"preset not found: {name!r}")
    path, data = index[name]
    parent = data.get("inherits")
    merged = flatten(parent, index, seen + [name]) if parent else {}
    for key, value in data.items():
        if key in META_KEYS:
            continue
        merged[key] = value
    merged["_chain"] = merged.get("_chain", []) + [name]
    return merged


def write(preset, outdir, filename, keep_name):
    chain = preset.pop("_chain", [])
    preset["name"] = keep_name
    # Standalone now, with no system bundle behind it.
    preset["from"] = "User"
    preset.pop("instantiation", None)
    path = os.path.join(outdir, filename)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(preset, handle, indent=1, ensure_ascii=False)
    print(f"{filename}: {len(preset)} keys")
    print(f"   chain: {' <- '.join(reversed(chain))}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles_dir")
    ap.add_argument("vendor")
    ap.add_argument("--machine", required=True)
    ap.add_argument("--process", required=True)
    ap.add_argument("--filament", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    index = load_index(args.profiles_dir, args.vendor)
    print(f"indexed {len(index)} presets from {args.vendor}\n")

    machine = flatten(args.machine, index)
    process = flatten(args.process, index)
    filament = flatten(args.filament, index)

    # Surface the values that decide whether this is actually a fast print.
    print("\nresolved speed-relevant values:")
    for key in ("layer_height", "initial_layer_print_height", "outer_wall_speed",
                "inner_wall_speed", "sparse_infill_speed", "internal_solid_infill_speed",
                "top_surface_speed", "travel_speed", "default_acceleration",
                "outer_wall_acceleration", "sparse_infill_density", "wall_loops"):
        if key in process:
            print(f"   process.{key} = {process[key]}")
    for key in ("filament_max_volumetric_speed", "nozzle_temperature",
                "hot_plate_temp", "filament_type"):
        if key in filament:
            print(f"   filament.{key} = {filament[key]}")
    for key in ("printer_model", "machine_max_acceleration_x", "nozzle_diameter"):
        if key in machine:
            print(f"   machine.{key} = {machine[key]}")

    print()
    paths = [
        write(machine, args.outdir, "machine.json", args.machine),
        write(process, args.outdir, "process.json", args.process),
        write(filament, args.outdir, "filament.json", args.filament),
    ]
    print("\n".join(paths))


main()
