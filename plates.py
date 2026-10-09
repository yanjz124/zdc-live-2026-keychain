"""Arrange keychains onto Bambu Studio plates.

    python plates.py --csv roster.local.csv --top orb

The CSV needs a `text` column (what goes on the ribbon) and may have `cid`, `rating` and `group`.
Rows are grouped in the order the groups first appear, and each group starts a new plate, so a
"going" group fills its own plates before a "tentative" one begins.
"""
import argparse
import csv
import math
import os
import shutil
import subprocess

from shapely import affinity

import keychain as k

PLATE = 256.0        # P2S build plate, mm
MARGIN = 6.0         # keep-out at the plate edge
GAP = 3.0            # between keychains
TOWER = 60.0         # space reserved for the purge tower (square)


def grid(item_w, item_h, count, skip_rear_left=False):
    """Cells for `count` keychains, rotated 90 degrees so they pack in rows. Returns (cells, tower, capacity).

    The rear-left cell sits in the strongest airflow from the side fan and is where parts lift, so
    --skip-rear-left leaves it empty.
    """
    w, h = item_h + GAP, item_w + GAP          # rotated footprint
    usable = PLATE - 2 * MARGIN
    cols = max(1, int((usable + GAP) // w))
    rows_for_tower = int((usable - TOWER - GAP + GAP) // h)
    rows = max(1, min(rows_for_tower, math.ceil((count + bool(skip_rear_left)) / cols)))
    spots = [(MARGIN + c * w + item_h / 2, MARGIN + r * h + item_w / 2)
             for r in range(rows) for c in range(cols)]
    if skip_rear_left and rows > 1:
        spots.pop(cols * (rows - 1))           # the rear-left cell
    # wipe_tower_x/y is the tower's centre, so keep a full half-tower clear of the last row
    top = MARGIN + rows * h
    tower = (PLATE / 2, min(top + GAP + TOWER / 2, PLATE - MARGIN - TOWER / 2))
    return spots[:count], tower, len(spots)


BBS = r"C:/Program Files/Bambu Studio/bambu-studio.exe"


def arrange(path, shape):
    """Re-pack with Bambu Studio's arrange, but keep the grid unless the result is actually valid.

    Its CLI arrange ignores the purge tower and has been seen to overlap parts outright, so the
    result is checked before it is accepted.
    """
    if not os.path.exists(BBS):
        print("   (Bambu Studio not found, keeping the grid layout)")
        return
    tmp = path + ".arranged.3mf"
    r = subprocess.run([BBS, "--arrange", "1", "--export-3mf", tmp, path], capture_output=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(tmp):
        print("   (arrange failed, keeping the grid layout)")
        return
    if placement_is_clean(tmp, shape):
        shutil.move(tmp, path)
    else:
        os.remove(tmp)
        print("   (arrange produced overlapping parts, keeping the grid layout)")


def placement_is_clean(path, shape, brim=8.0):
    """True when no two parts touch, nothing hits the purge tower and everything is on the plate."""
    import json, re, zipfile
    from shapely import affinity
    from shapely.geometry import box
    z = zipfile.ZipFile(path)
    model = z.read("3D/3dmodel.model").decode("utf-8", "ignore")
    placed = []
    for _, t in re.findall(r'<item objectid="(\d+)"[^>]*transform="([^"]+)"', model):
        v = [float(x) for x in t.split()]
        placed.append(affinity.affine_transform(shape, [v[0], v[3], v[1], v[4], v[9], v[10]]))
    cfg = json.loads(z.read("Metadata/project_settings.config"))
    tx, ty = float(cfg["wipe_tower_x"][0]), float(cfg["wipe_tower_y"][0])
    tower = box(tx - 20, ty - 32, tx + 20, ty + 32)
    plate = box(MARGIN / 2, MARGIN / 2, PLATE - MARGIN / 2, PLATE - MARGIN / 2)
    for i, a in enumerate(placed):
        if not plate.contains(a) or a.buffer(brim / 2).intersects(tower):
            return False
        if any(a.intersects(b) for b in placed[i + 1:]):
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=os.path.join(k.HERE, "attendees.csv"))
    ap.add_argument("--top", default="orb", choices=list(k.TOPS))
    ap.add_argument("--out", default=os.path.join(k.HERE, "out", "plates"))
    ap.add_argument("--per-plate", type=int, default=0, help="cap per plate (default: as many as fit)")
    ap.add_argument("--names", help="comma-separated names for a one-off plate, instead of --csv")
    ap.add_argument("--arrange", action="store_true",
                    help="let Bambu Studio pack the plate (fits more than the plain grid)")
    ap.add_argument("--skip-rear-left", action="store_true",
                    help="leave the rear-left cell empty (strongest airflow, where parts lift)")
    args = ap.parse_args()

    k.set_top(args.top)
    if args.names:
        rows = [{"text": n.strip()} for n in args.names.split(",") if n.strip()]
    else:
        with open(args.csv, newline="", encoding="utf-8-sig") as fh:
            rows = [{(a or "").strip().lower(): (b or "").strip() for a, b in r.items()}
                    for r in csv.DictReader(fh)]
        rows = [r for r in rows if r.get("text")]

    groups = {}
    for r in rows:
        groups.setdefault(r.get("group", ""), []).append(r)

    fonts = k.Fonts()
    os.makedirs(args.out, exist_ok=True)
    plate_no = 0
    for gname, members in groups.items():
        built = []
        outline_shape = None
        for r in members:
            solids, _, _, outline = k.solids_for(fonts, r["text"], r.get("cid", ""), r.get("rating", ""))
            outline_shape = outline
            x0, y0, x1, y1 = outline.bounds
            built.append((r["text"], solids, x1 - x0, y1 - y0))
        item_w = max(w for _, _, w, _ in built)
        item_h = max(h for _, _, _, h in built)
        # balance the group over as few plates as possible
        _, _, capacity = grid(item_w, item_h, len(built), args.skip_rear_left)
        cap = min(args.per_plate, capacity) if args.per_plate else capacity
        if args.per_plate and args.per_plate > capacity:
            print(f"   (only {capacity} fit on a plate with the brim, using that)")
        n_plates = math.ceil(len(built) / cap)
        per = math.ceil(len(built) / n_plates)
        for start in range(0, len(built), per):
            entries = [(t, s, h) for t, s, _, h in built[start:start + per]]
            cells, tower, _ = grid(item_w, item_h, len(entries), args.skip_rear_left)
            plate_no += 1
            name = f"plate_{plate_no}" + (f"_{gname.lower().replace(' ', '_')}" if gname else "")
            path = os.path.join(args.out, f"{name}.3mf")
            k.write_3mf([(t, s, cells[i], 1) for i, (t, s, _) in enumerate(entries)], path, tower)
            if args.arrange:
                centred = affinity.translate(outline_shape, -(outline_shape.bounds[0] + outline_shape.bounds[2]) / 2,
                                             -(outline_shape.bounds[1] + outline_shape.bounds[3]) / 2)
                arrange(path, centred)
            print(f"{name}.3mf: {len(entries)} keychains"
                  + (f" ({gname})" if gname else "")
                  + f", tower at {tower[0]:.0f},{tower[1]:.0f} mm")
            for t, _, _ in entries:
                print(f"    {t}")


if __name__ == "__main__":
    main()
