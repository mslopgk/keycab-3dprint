"""Apply key=value overrides to a flattened OrcaSlicer preset JSON.

    python tools/patch_preset.py <preset.json> key=value [key=value ...]

Values are written in the same shape the key already has: a key holding a list
gets a list of the same length, a scalar stays scalar. Unknown keys are added as
scalars. Nozzle temperature is range-checked against the filament's own limits.

Patching the flattened JSON rather than passing CLI flags is deliberate: an
option name the CLI does not recognise is silently ignored, and the slice then
comes out at the preset value with no warning at all.
"""

import json
import sys

RANGE_CHECKED = {
    "nozzle_temperature": ("nozzle_temperature_range_low", "nozzle_temperature_range_high"),
    "nozzle_temperature_initial_layer": ("nozzle_temperature_range_low",
                                         "nozzle_temperature_range_high"),
}


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    path = sys.argv[1]
    overrides = []
    for item in sys.argv[2:]:
        key, sep, value = item.partition("=")
        if not sep:
            sys.exit(f"expected key=value, got {item!r}")
        overrides.append((key, value))

    with open(path, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)

    for key, value in overrides:
        if key in RANGE_CHECKED:
            low_key, high_key = RANGE_CHECKED[key]
            low = int(cfg.get(low_key, ["0"])[0])
            high = int(cfg.get(high_key, ["999"])[0])
            if not (low <= int(value) <= high):
                sys.exit(f"{key}={value} is outside {low}-{high} from the filament preset")

        existing = cfg.get(key)
        if isinstance(existing, list):
            cfg[key] = [value] * len(existing)
        else:
            cfg[key] = value
        was = existing if existing is not None else "(absent)"
        print(f"  {key}: {was} -> {cfg[key]}")

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=1, ensure_ascii=False)


main()
