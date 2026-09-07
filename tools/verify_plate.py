"""Check a sliced plate: copy count, per-copy footprint, spacing, and bed fit.

    python tools/verify_plate.py gcode/plate_1.gcode [bed_x bed_y]

Bambu gcode brackets every object with
    ; printing object <name> id:<n> copy <k>
    ; stop printing object <name> id:<n> copy <k>
so the copies are counted from those markers rather than guessed by clustering.
Extruding moves between a start/stop pair give that copy's footprint.

Only the opening layers are read -- a 13-hour plate is hundreds of megabytes and
the layout is already fixed by the first layer. The purge line lives at negative
Y, outside the bed, and is skipped.
"""

import re
import sys

path = sys.argv[1]
bed_x = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0
bed_y = float(sys.argv[3]) if len(sys.argv) > 3 else 180.0
LINE_BUDGET = 600_000

# Copies of one STL all carry "id:0 copy 0", so that marker cannot separate them.
# The per-instance identifier is the unique label id on the following line.
start_re = re.compile(r"^; start printing object, unique label id:\s*(\d+)")
stop_re = re.compile(r"^; stop printing object")
move_re = re.compile(r"^G[01]\s")
# The slicer writes values with no leading zero -- "E.8", "X.25". A pattern that
# requires a digit before the decimal point silently matches nothing on those,
# which reads as "this plate has no extrusion" rather than as a parser bug.
NUM = r"(-?(?:\d+\.?\d*|\.\d+))"
x_re = re.compile("X" + NUM)
y_re = re.compile("Y" + NUM)
e_re = re.compile("E" + NUM)

boxes = {}
current = None
x = y = None
lines_read = 0

with open(path, "r", encoding="utf-8", errors="replace") as handle:
    for line in handle:
        lines_read += 1
        if lines_read > LINE_BUDGET:
            break

        started = start_re.match(line)
        if started:
            current = int(started.group(1))
            continue
        stopped = stop_re.match(line)
        if stopped:
            current = None
            continue

        if current is None or not move_re.match(line):
            continue
        mx, my, me = x_re.search(line), y_re.search(line), e_re.search(line)
        if mx:
            x = float(mx.group(1))
        if my:
            y = float(my.group(1))
        if not (me and float(me.group(1)) > 0):
            continue
        if x is None or y is None or y < 0.0:
            continue
        box = boxes.get(current)
        if box is None:
            boxes[current] = [x, y, x, y]
        else:
            box[0] = min(box[0], x)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x)
            box[3] = max(box[3], y)

print(f"lines read        : {lines_read}")
print(f"copies with output: {len(boxes)}  (ids {min(boxes)}..{max(boxes)})" if boxes
      else "no object output found")
if not boxes:
    sys.exit(1)

sizes = sorted({(round(b[2] - b[0], 2), round(b[3] - b[1], 2)) for b in boxes.values()})
print(f"footprint sizes   : {sizes[:5]}{' ...' if len(sizes) > 5 else ''}")

all_x = [v for b in boxes.values() for v in (b[0], b[2])]
all_y = [v for b in boxes.values() for v in (b[1], b[3])]
print(f"plate extent      : X {min(all_x):.2f}..{max(all_x):.2f}  "
      f"Y {min(all_y):.2f}..{max(all_y):.2f}")
fits = min(all_x) >= 0 and max(all_x) <= bed_x and min(all_y) >= 0 and max(all_y) <= bed_y
print(f"inside {bed_x:.0f}x{bed_y:.0f} bed : {fits}")

ordered = sorted(boxes.items())
worst = None
overlaps = 0
for i in range(len(ordered)):
    for j in range(i + 1, len(ordered)):
        a, b = ordered[i][1], ordered[j][1]
        gap = max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])
        if gap < 0:
            overlaps += 1
        if worst is None or gap < worst:
            worst = gap
if worst is None:
    print("closest pair gap  : n/a (only one object seen)")
else:
    print(f"closest pair gap  : {worst:.2f} mm")
print(f"overlapping pairs : {overlaps}")
sys.exit(0 if (fits and overlaps == 0) else 1)
