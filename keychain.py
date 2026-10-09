"""vZDC Live 2026 keychain: multi-color STL generator (Night Ribbon design).

Writes, per attendee, a Bambu Studio .3mf (one object, four color parts already
on filament slots 1-4: black, white, gray, red) plus one watertight STL per
color as a fallback. Load the STLs together and choose "load as a single object
with multiple parts".

    python keychain.py                      # everyone in attendees.csv
    python keychain.py --name "Carson Berget" --cid 1652726 --rating SUP

Model coordinates: mm, Z up. The FRONT face is on the build plate (z = 0) and
is mirrored so it reads correctly once flipped. The BACK face is on top
(z = 4.0) and is the surface to iron.
"""
import argparse
import csv
import math
import os
import re
import struct

import manifold3d as m3d
import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- build parameters (mm) ----
THICK = 0.10 + 29 * 0.14   # 4.16 mm: a whole number of layers
# Layer plan: first layer 0.10 mm (crisper small features where it matters most), then 0.14 mm.
# The inlay depths are whole numbers of layers so the colour boundaries land on layer boundaries.
LAYER_0, LAYER = 0.10, 0.14
INLAY_BOTTOM = LAYER_0 + 2 * LAYER   # 0.38: the back face, against the plate
INLAY_TOP = 3 * LAYER                # 0.42: the front face, ironed
INLAY = INLAY_TOP                    # what the drawing quotes
HOLE_D = 3.4         # key-ring hole diameter (fits a doubled 1.2 mm split-ring wire)
NAME_SIZE = 4.3      # ribbon text size when it fits
NAME_MAX_W = 38.0    # widest the ribbon text may run before it shrinks
NAME_MIN_SIZE = 2.8  # smallest font size the ribbon text may shrink to

# ---- design geometry (design coordinates: mm, y down, 50 mm wide) ----
CX = 25.0
D_TOP, D_BOT, D_HW = 15.0, 25.8, 13.0
D_H = (D_BOT - D_TOP) / math.sqrt(1 - (4.0 / D_HW) ** 2)
OCULUS = 2.45                  # white ring around the hole, like an eyelet

# Three tops. A split ring has to loop from the hole around the material above it, so the
# material above the hole plus the 4 mm thickness must fit through the ring's inner opening.
#   orb   - the finial IS the ring boss: shortest, works with an 8 mm ring
#   spire - the full statue and spire kept, with the ring boss added above them (8 mm ring)
#   dome  - the original look: tall spire, hole through the upper dome (needs a 25 mm ring)
def _cap(y0, y1, hw):
    return poly(qbez((CX - hw, y1), (CX - hw, y0 + 0.1), (CX, y0)) + qbez((CX, y0), (CX + hw, y0 + 0.1), (CX + hw, y1)))


TOPS = {
    "orb": {
        "hole": (CX, 4.6), "ring": "8 mm split ring", "ring_d": 8.0,
        "parts": lambda: [circle(CX, 4.6, 4.0), trap(6.8, 9.8, 1.9, 2.6),
                          _cap(9.5, 11.6, 2.2), band(11.4, 14.0, 2.8)],
        "slits": (11.7, 13.1, 2.8, (CX - 1.3, CX, CX + 1.3)),
    },
    "spire": {
        "hole": (CX, -3.2), "ring": "8 mm split ring", "ring_d": 8.0,
        "parts": lambda: [circle(CX, -3.2, 4.0),        # the ring boss
                          trap(-1.0, 3.2, 1.6, 1.2),    # neck, 3 mm wide x 4 mm thick
                          circle(CX, 2.9, 1.05), trap(3.4, 5.8, 0.85, 1.05), trap(5.6, 9.7, 1.3, 1.9),
                          _cap(9.5, 11.6, 2.2), band(11.4, 14.0, 2.8)],
        "slits": (11.7, 13.1, 2.8, (CX - 1.3, CX, CX + 1.3)),
    },
    "dome": {
        "hole": (CX, 15.8), "ring": "25 mm split ring", "ring_d": 25.0,
        "parts": lambda: [circle(CX, 1.9, 1.05), trap(2.4, 4.8, 0.85, 1.05), trap(4.6, 5.9, 1.3, 1.5),
                          _cap(5.5, 8.5, 2.1), band(8.3, 14.0, 2.7)],
        "slits": (9.2, 12.9, 2.7, (CX - 1.35, CX, CX + 1.35)),
    },
}
TOP = "orb"
HOLE = TOPS[TOP]["hole"]


def set_top(name):
    global TOP, HOLE
    if name not in TOPS:
        raise SystemExit(f"--top must be one of {', '.join(TOPS)}")
    TOP, HOLE = name, TOPS[name]["hole"]
K = 0.11  # perspective: rings seen from below bow upward in the middle

BLACK, WHITE, GRAY, RED = "black", "white", "gray", "red"
COLORS = (BLACK, WHITE, GRAY, RED)


def dw(y):
    t = (D_BOT - y) / D_H
    return D_HW * math.sqrt(max(0.0, 1 - t * t))


def sag(hw):
    return K * hw


def yo(x, hw):
    u = (x - CX) / hw
    return -sag(hw) * (1 - u * u)


def spread(n, radius, edge):
    out = []
    for i in range(n):
        th = (-1 + 2 * i / (n - 1)) * math.asin(edge)
        out.append((CX + radius * math.sin(th), math.cos(th)))
    return out


def shade(x, radius):
    return GRAY if (x - CX) / radius > 0.7 else WHITE


# ---- 2D primitives ----
def rect(x0, y0, x1, y1, r=0.0):
    if r <= 0:
        return box(x0, y0, x1, y1)
    r = min(r, (x1 - x0) / 2 - 1e-3, (y1 - y0) / 2 - 1e-3)
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=6)


def poly(pts):
    return Polygon(pts).buffer(0)


def circle(cx, cy, r):
    return Point(cx, cy).buffer(r, quad_segs=24)


def qbez(p0, c, p2, n=24):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p2[1])
            for t in (i / n for i in range(n + 1))]


def band(y0, y1, hw):
    s2 = 2 * sag(hw)
    top = qbez((CX - hw, y0), (CX, y0 - s2), (CX + hw, y0))
    bot = qbez((CX + hw, y1), (CX, y1 - s2), (CX - hw, y1))
    return poly(top + bot)


def trap(y0, y1, hw0, hw1):
    return poly([(CX - hw0, y0), (CX + hw0, y0), (CX + hw1, y1), (CX - hw1, y1)])


def arch_win(x, y0, y1, wd):
    r = wd / 2
    return unary_union([box(x - r, y0 + r, x + r, y1), circle(x, y0 + r, r)])


def ys(a, b, n=40):
    return [a + (b - a) * i / n for i in range(n + 1)]


# ---- the keychain ----
def body_parts():
    dome = poly([(CX - dw(y), y) for y in ys(D_BOT, D_TOP)] + [(CX + dw(y), y) for y in ys(D_TOP, D_BOT)])
    return unary_union(TOPS[TOP]["parts"]() + [
        trap(13.0, 16.2, 4.0, 5.7), dome,
        band(25.7, 27.5, 14.0), band(27.4, 32.5, 15.0), band(32.4, 34.5, 18.0),
        band(34.4, 45.1, 17.4), band(45.0, 50.0, 18.6),
    ])


def ribbon_parts():
    # The swallowtail tips are chamfered: a sharp point there has almost no material holding it to
    # the plate, so it curls up and the nozzle eventually catches it. The notch stays crisp.
    wings = unary_union([
        poly([(1.3, 49.0), (6.5, 49.0), (6.5, 58.2), (1.3, 58.2), (0.4, 56.8), (2.6, 53.6), (0.4, 50.4)]),
        poly([(48.7, 49.0), (43.5, 49.0), (43.5, 58.2), (48.7, 58.2), (49.6, 56.8), (47.4, 53.6), (49.6, 50.4)]),
    ])
    main = unary_union([wings, rect(4.2, 47.0, 45.8, 56.4, 0.4)])
    folds = unary_union([poly([(4.2, 56.4), (6.5, 58.2), (6.5, 56.4)]),
                         poly([(45.8, 56.4), (43.5, 58.2), (43.5, 56.4)])])
    return main, folds


def highlight():
    y0, y1, n = 16.6, 24.4, 32
    outer, inner = [], []
    for i in range(n + 1):
        y = y0 + (y1 - y0) * i / n
        x = CX - dw(y) + 1.0
        outer.append((x, y))
        inner.append((x + 0.95 * math.sin(math.pi * i / n), y))
    return poly(outer + inner[::-1])


def oculus():
    return circle(*HOLE, OCULUS).difference(circle(*HOLE, HOLE_D / 2))


def front_items(fonts):
    it = []
    sy0, sy1, shw, sxs = TOPS[TOP]["slits"]
    for x in sxs:
        d = yo(x, shw)
        it.append((WHITE, rect(x - 0.28, sy0 + d, x + 0.28, sy1 + d, 0.2)))
    it.append((GRAY, band(13.2, 13.6, 3.6)))
    it.append((WHITE, oculus()))
    it.append((GRAY, highlight()))
    R = dw(23.4) * 0.97
    for x, k in spread(13, R, 0.95):
        wd, d = max(0.55, 0.95 * k), yo(x, R)
        it.append((shade(x, R), rect(x - wd / 2, 22.6 + d, x + wd / 2, 24.2 + d, 0.2)))
    it.append((GRAY, band(25.3, 25.75, 13.4)))
    it.append((GRAY, band(27.45, 27.9, 15.0)))
    for x, k in spread(15, 14.0, 0.94):
        d = yo(x, 15.0)
        it.append((shade(x, 14.0), arch_win(x, 28.7 + d, 31.5 + d, max(0.6, 1.05 * k))))
    it.append((GRAY, band(33.7, 34.15, 18.0)))
    for x, k in spread(12, 16.6, 0.96):
        wd, d = max(0.55, 1.45 * k), yo(x, 17.4)
        it.append((shade(x, 16.6), rect(x - wd / 2, 35.3 + d, x + wd / 2, 44.2 + d, 0.25)))
    it.append((GRAY, band(45.6, 46.05, 18.6)))
    main, folds = ribbon_parts()
    it += [(RED, main), (GRAY, folds)]
    it.append((WHITE, fonts.text("vZDC LIVE 2026", 4.2, 47.9, 45.8, 4.3, ls=0.4)))
    it.append((WHITE, fonts.text("OCT 17 · VINTON, VA", 4.2, 52.9, 45.8, 2.8, ls=0.6)))
    return it


def back_items(fonts, text, cid, rating):
    """text is free-form and goes on the ribbon (e.g. "CARSON B. (CB)"); cid and rating may be blank."""
    it = [(WHITE, oculus())]
    main, folds = ribbon_parts()
    it += [(RED, main), (GRAY, folds)]
    if rating:
        bw = 5.0 + 2.3 * len(rating)
        it.append((RED, rect(CX - bw / 2, 21.3, CX + bw / 2, 25.3, 1.0)))
        it.append((WHITE, fonts.text(rating, CX - bw / 2, 21.7, CX + bw / 2, 3.3, ls=1)))
    if cid:
        it.append((WHITE, fonts.text(cid, 3, 27.2, 47, 4.0, ls=0, mono=True)))
    if cid or rating:
        it.append((GRAY, fonts.text("VIRTUAL", 3, 35.4, 47, 3.2, ls=1.6)))
        it.append((GRAY, fonts.text("WASHINGTON ARTCC", 3, 39.4, 47, 3.2, ls=0.2)))
    else:  # name only: fill the space the badge and CID would have used
        it.append((GRAY, fonts.text("VIRTUAL", 3, 27.6, 47, 4.0, ls=2.0)))
        it.append((GRAY, fonts.text("WASHINGTON", 3, 32.6, 47, 4.0, ls=0.4)))
        it.append((GRAY, fonts.text("ARTCC", 3, 37.6, 47, 4.0, ls=2.0)))
        it.append((RED, rect(17, 43.2, 33, 43.8, 0.3)))
    if text:
        size = NAME_SIZE
        while fonts.width(text, size, 0.3) > NAME_MAX_W and size > NAME_MIN_SIZE:
            size -= 0.05
        if fonts.width(text, size, 0.3) > NAME_MAX_W:
            raise SystemExit(f"Text too long for the ribbon even at {NAME_MIN_SIZE} mm: {text!r}")
        y0 = 49.4 + (NAME_SIZE - size) / 2
        it.append((WHITE, fonts.text(text, 4.2, y0, 45.8, size, ls=0.3)))
    return it


# ---- text -> polygons ----
class _FlatPen(BasePen):
    def __init__(self, gs):
        super().__init__(gs)
        self.contours, self.cur = [], []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        for i in range(1, 9):
            t = i / 8
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            self.cur.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                             a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        self.cur += qbez(p0, p1, p2, 8)[1:]

    def _closePath(self):
        if len(self.cur) >= 3:
            self.contours.append(self.cur)
        self.cur = []

    _endPath = _closePath


class Fonts:
    def __init__(self):
        self.faces = {False: TTFont(os.path.join(HERE, "fonts", "B612-Bold.ttf")),
                      True: TTFont(os.path.join(HERE, "fonts", "B612Mono-Bold.ttf"))}
        self.cache = {}

    def _glyph(self, mono, ch):
        key = (mono, ch)
        if key not in self.cache:
            f = self.faces[mono]
            name = f.getBestCmap().get(ord(ch))
            if name is None:
                raise SystemExit(f"Character {ch!r} is not in the font")
            gs = f.getGlyphSet()
            pen = _FlatPen(gs)
            gs[name].draw(pen)
            shape = Polygon()
            for c in pen.contours:  # even-odd: counters become holes
                shape = shape.symmetric_difference(Polygon(c).buffer(0))
            self.cache[key] = (shape, f["hmtx"][name][0])
        return self.cache[key]

    def width(self, s, size, ls_px, mono=False):
        upm = self.faces[mono]["head"].unitsPerEm
        return sum(self._glyph(mono, ch)[1] for ch in s) * size / upm + len(s) * ls_px / 6

    def text(self, s, x0, y0, x1, size, ls=0.0, mono=False):
        """Lay out like the mockup: centered in [x0, x1], line box of height `size` at y0."""
        f = self.faces[mono]
        upm = f["head"].unitsPerEm
        sc = size / upm
        asc, desc = f["hhea"].ascent, -f["hhea"].descent
        baseline = y0 + (size - (asc + desc) * sc) / 2 + asc * sc
        pen_x = (x0 + x1) / 2 - self.width(s, size, ls, mono) / 2 + ls / 12
        parts = []
        for ch in s:
            shape, adv = self._glyph(mono, ch)
            if not shape.is_empty:
                g = affinity.scale(shape, sc, -sc, origin=(0, 0))
                parts.append(affinity.translate(g, pen_x, baseline))
            pen_x += adv * sc + ls / 6
        return unary_union(parts)


# ---- compositing and solids ----
def compose(items, outline):
    """Paint items in order (later wins) and return {color: region} clipped to the outline."""
    layers = {c: Polygon() for c in COLORS}
    for color, g in items:
        for c in COLORS:
            layers[c] = layers[c].difference(g)
        layers[color] = layers[color].union(g)
    painted = unary_union(list(layers.values()))
    layers[BLACK] = layers[BLACK].union(outline.difference(painted))
    return {c: clean(g.intersection(outline)) for c, g in layers.items()}


MIN_FEATURE = 0.3    # a 0.2 mm nozzle lays ~0.25 mm; islands thinner than this come loose


def merge_slivers(layers, min_w=MIN_FEATURE):
    """Give any color region narrower than min_w to the neighbouring color.

    A 0.2 mm nozzle cannot lay a reliable bead below about 0.4 mm, and such slivers come loose on
    the face printed against the plate and end up dragged around by the nozzle.
    """
    r = min_w / 2
    kept = {c: list(_polys(g)) for c, g in layers.items()}
    loose = []
    for c, polys in kept.items():
        good = [p for p in polys if not p.buffer(-r).buffer(r).is_empty and p.area >= 0.15]
        loose += [(p, c) for p in polys if p not in good]
        kept[c] = good
    for p, c in loose:                # hand each loose island to whichever color surrounds it most
        ring = p.buffer(0.3).difference(p)
        best, best_len = None, 0.0
        for d, polys in kept.items():
            if d == c:
                continue
            a = sum(ring.intersection(q).area for q in polys)
            if a > best_len:
                best, best_len = d, a
        kept.setdefault(best or BLACK, []).append(p)
    return {c: unary_union(polys) if polys else Polygon() for c, polys in kept.items()}


def clean(g, min_area=0.02):
    polys = [p for p in _polys(g) if p.area >= min_area]
    return MultiPolygon(polys) if polys else Polygon()


def _polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if hasattr(g, "geoms"):
        return [p for sub in g.geoms for p in _polys(sub)]
    return []


def to_model(g, mirror):
    """Design coords -> model coords (Y up). Mirrored for the face that prints face-down."""
    if mirror:
        g = affinity.scale(g, -1, 1, origin=(CX, 0))
    return affinity.scale(g, 1, -1, origin=(0, 0))


def extrude(g, z0, z1):
    contours = []
    for p in _polys(g):
        contours.append(np.array(p.exterior.coords[:-1]))
        contours += [np.array(r.coords[:-1]) for r in p.interiors]
    if not contours:
        return None
    cs = m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
    return m3d.Manifold.extrude(cs, z1 - z0).translate((0, 0, z0))


def write_stl(man, path):
    mesh = man.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    t = np.asarray(mesh.tri_verts)
    with open(path, "wb") as fh:
        fh.write(b"vZDC Live 2026 keychain".ljust(80, b" "))
        fh.write(struct.pack("<I", len(t)))
        for a, b, c in t:
            p0, p1, p2 = v[a], v[b], v[c]
            n = np.cross(p1 - p0, p2 - p0)
            ln = np.linalg.norm(n)
            n = n / ln if ln else n
            fh.write(struct.pack("<12fH", *n, *p0, *p1, *p2, 0))


# Filament slot for each part in the 3MF (1-based, as Bambu Studio numbers filaments)
FILAMENT_SLOT = {BLACK: 1, WHITE: 2, GRAY: 3, RED: 4}
FILAMENT_HEX = {BLACK: "#161616", WHITE: "#FFFFFF", GRAY: "#8E9089", RED: "#C8102E"}
PLATE_CENTER = (128.0, 128.0)  # P2S plate is 256 x 256 mm
TEMPLATE = os.path.join(HERE, "bambu", "p2s_0.2_template.json")
# purge volume (mm3) when switching INTO a color; lighter colors need more
FLUSH_INTO = {BLACK: 150, WHITE: 450, GRAY: 280, RED: 300}

_NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
       'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
       'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')
_ID = "1 0 0 0 1 0 0 0 1 0 0 0"
_ID4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def project_settings(colors, tower=None):
    """P2S 0.2 mm nozzle project settings, expanded from one filament to one per color."""
    import json
    tpl = json.load(open(TEMPLATE, encoding="utf-8"))
    ps, n = dict(tpl["settings"]), len(colors)
    for k in tpl["per_filament_keys"]:
        ps[k] = list(ps[k]) * n  # values are grouped per filament (e.g. [std, high-flow] per filament)
    variants = len(tpl["settings"]["filament_self_index"])
    ps["filament_self_index"] = [str(i + 1) for i in range(n) for _ in range(variants)]
    ps["filament_colour"] = [FILAMENT_HEX[c] for c in colors]
    ps["filament_multi_colour"] = [FILAMENT_HEX[c] for c in colors]
    ps["filament_map"] = ["1"] * n
    ps["flush_volumes_matrix"] = [str(0 if a == b else FLUSH_INTO[b]) for a in colors for b in colors]
    ps["layer_height"] = str(LAYER)
    ps["initial_layer_print_height"] = str(LAYER_0)
    ps["wall_loops"] = "3"
    ps["ironing_type"] = "top"
    ps["flush_into_infill"] = "1"            # purge into infill where it can
    ps["wipe_tower_no_sparse_layers"] = "1"  # no tower on layers without a color change
    # layers 1-2 are nothing but small colour islands, so hold them down and lay them slowly
    ps["brim_type"], ps["brim_width"], ps["brim_object_gap"] = "outer_only", "4", "0.1"
    ps["initial_layer_speed"] = ["25"] * len(ps["initial_layer_speed"])
    ps["initial_layer_infill_speed"] = ["35"] * len(ps["initial_layer_infill_speed"])
    # the profile shaves 0.15 mm off every island on layer 1, which eats letter strokes
    ps["elefant_foot_compensation"] = "0"
    ps["only_one_wall_first_layer"] = "1"   # one clean bead per thin stroke, not two overlapping
    # background first, small text last: the text beads land against walls that already exist
    order = [str(FILAMENT_SLOT[c]) for c in (BLACK, RED, GRAY, WHITE) if c in colors]
    ps["first_layer_print_sequence"] = order
    ps["other_layers_print_sequence"] = order
    ps["other_layers_print_sequence_nums"] = "1"   # one sequence, used on every layer
    # always lift on travel so the nozzle cannot clip a lifted edge
    ps["z_hop_types"] = ["Normal Lift"] * len(ps["z_hop_types"])
    ps["z_hop"] = ["0.6"] * len(ps["z_hop"])
    # PLA shrinks as it cools, and the part nearest the side fan lifts first. Hold the cooling off
    # while the part gets a grip, and anchor it with a wider brim.
    n = len(ps["close_fan_the_first_x_layers"])
    ps["close_fan_the_first_x_layers"] = ["4"] * n
    ps["close_additional_fan_first_x_layers"] = ["6"] * n
    ps["first_x_layer_fan_speed"] = ["0"] * len(ps["first_x_layer_fan_speed"])
    ps["additional_cooling_fan_speed"] = ["40"] * len(ps["additional_cooling_fan_speed"])
    ps["brim_width"] = "8"
    ps["reduce_crossing_wall"] = "1"   # route travel around parts instead of over them
    # name the process for what it is, so the dropdown does not keep reading "0.10mm Standard"
    parent = ps["print_settings_id"]
    ps["print_settings_id"] = "0.14mm vZDC keychain @BBL P2S 0.2 nozzle"
    ps["inherits_group"] = [parent] + [""] * (len(colors) + 1)
    tx, ty = tower or (175, 150)   # clear of the keychains, well inside the plate
    ps["wipe_tower_x"], ps["wipe_tower_y"] = [str(tx)], [str(ty)]
    return json.dumps(ps, indent=4)


def write_3mf(entries, path, tower=None):
    """Bambu Studio project. entries: [(title, solids, (x, y), rot90)] - one object per keychain,
    each with its color parts on their own filament slot."""
    import json
    import uuid
    import zipfile
    from xml.sax.saxutils import quoteattr

    tpl_version = json.load(open(TEMPLATE, encoding="utf-8"))["settings"]["version"]
    colors = [c for c in COLORS if any(c in sol for _, sol, _, _ in entries)]
    u = lambda: str(uuid.uuid4())

    meshes, objects, items, obj_cfgs, instances, assembles = [], [], [], [], [], []
    mesh_id = 1
    first_obj_id = 1 + sum(len([c for c in COLORS if c in sol]) for _, sol, _, _ in entries)
    for n, (title, solids, (px, py), rot) in enumerate(entries):
        parts = [(mesh_id + i, c, solids[c]) for i, c in enumerate(c for c in COLORS if c in solids)]
        mesh_id += len(parts)
        lo = np.min([s.bounding_box()[:3] for _, _, s in parts], axis=0)
        hi = np.max([s.bounding_box()[3:] for _, _, s in parts], axis=0)
        ctr = (lo + hi) / 2                  # meshes are stored centered, as Bambu Studio writes them
        faces = {}
        for pid, c, s in parts:
            m = s.to_mesh()
            v = np.asarray(m.vert_properties)[:, :3] - ctr
            t = np.asarray(m.tri_verts)
            faces[pid] = len(t)
            verts = "\n".join('     <vertex x="%.5f" y="%.5f" z="%.5f"/>' % tuple(p) for p in v)
            tris = "\n".join('     <triangle v1="%d" v2="%d" v3="%d"/>' % tuple(f) for f in t)
            meshes.append('  <object id="%d" p:UUID="%s" type="model">\n   <mesh>\n    <vertices>\n%s\n'
                          '    </vertices>\n    <triangles>\n%s\n    </triangles>\n   </mesh>\n  </object>'
                          % (pid, u(), verts, tris))
        obj_id = first_obj_id + n            # object ids continue after the mesh ids
        comps = "\n".join('    <component p:path="/3D/Objects/object_1.model" objectid="%d" p:UUID="%s" '
                          'transform="%s"/>' % (pid, u(), _ID) for pid, _, _ in parts)
        objects.append('  <object id="%d" p:UUID="%s" type="model">\n   <components>\n%s\n   </components>\n'
                       '  </object>' % (obj_id, u(), comps))
        rotm = "0 1 0 -1 0 0 0 0 1" if rot else "1 0 0 0 1 0 0 0 1"
        place = "%s %.4f %.4f %.4f" % (rotm, px, py, ctr[2])
        items.append('  <item objectid="%d" p:UUID="%s" transform="%s" printable="1"/>' % (obj_id, u(), place))
        part_cfg = "".join(
            '    <part id="%d" subtype="normal_part">\n      <metadata key="name" value=%s/>\n'
            '      <metadata key="matrix" value="%s"/>\n      <metadata key="extruder" value="%d"/>\n'
            '      <mesh_stat face_count="%d" edges_fixed="0" degenerate_facets="0" facets_removed="0" '
            'facets_reversed="0" backwards_edges="0"/>\n    </part>\n'
            % (pid, quoteattr(c), _ID4, FILAMENT_SLOT[c], faces[pid]) for pid, c, _ in parts)
        obj_cfgs.append('  <object id="%d">\n    <metadata key="name" value=%s/>\n'
                        '    <metadata key="extruder" value="1"/>\n    <metadata face_count="%d"/>\n%s  </object>\n'
                        % (obj_id, quoteattr(title), sum(faces.values()), part_cfg))
        instances.append('    <model_instance>\n      <metadata key="object_id" value="%d"/>\n'
                         '      <metadata key="instance_id" value="0"/>\n'
                         '      <metadata key="identify_id" value="%d"/>\n    </model_instance>\n' % (obj_id, 100 + n))
        assembles.append('   <assemble_item object_id="%d" instance_id="0" transform="%s" offset="0 0 0" />\n'
                         % (obj_id, place))

    objects_model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" %s>\n'
                     ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n%s\n </resources>\n'
                     ' <build/>\n</model>\n' % (_NS, "\n".join(meshes)))
    title = entries[0][0] if len(entries) == 1 else "%d keychains" % len(entries)
    main_model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" %s>\n'
                  ' <metadata name="Application">BambuStudio-%s</metadata>\n'
                  ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
                  ' <metadata name="Title">%s</metadata>\n <resources>\n%s\n </resources>\n'
                  ' <build p:UUID="%s">\n%s\n </build>\n</model>\n'
                  % (_NS, tpl_version, title, "\n".join(objects), u(), "\n".join(items)))
    settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n%s'
                '  <plate>\n    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value=""/>\n'
                '    <metadata key="locked" value="false"/>\n%s  </plate>\n  <assemble>\n%s  </assemble>\n</config>\n'
                % ("".join(obj_cfgs), "".join(instances), "".join(assembles)))

    rel = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
    rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                   ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
                   ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
                   ' <Default Extension="png" ContentType="image/png"/>\n'
                   ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="%s">\n'
                                  ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="%s"/>\n</Relationships>\n'
                                  % (rels_ns, rel))
        z.writestr("3D/_rels/3dmodel.model.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="%s">\n'
                   ' <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="%s"/>\n</Relationships>\n'
                   % (rels_ns, rel))
        z.writestr("3D/3dmodel.model", main_model)
        z.writestr("3D/Objects/object_1.model", objects_model)
        z.writestr("Metadata/project_settings.config", project_settings(colors, tower))
        z.writestr("Metadata/model_settings.config", settings)


def solids_for(fonts, text, cid, rating):
    """One watertight solid per color, bottom edge at Y = 0.

    The BACK face prints against the plate: it has about half as many separate color islands as the
    front, which is what layer 1 has to make stick. The front then ends up on top, where it is ironed.
    """
    text, rating = text.strip(), rating.strip().upper()
    main, _ = ribbon_parts()
    outline = unary_union([body_parts(), main]).difference(circle(*HOLE, HOLE_D / 2))
    front = merge_slivers(compose(front_items(fonts), outline))
    back = merge_slivers(compose(back_items(fonts, text, cid, rating), outline))
    core = {c: Polygon() for c in COLORS}
    core[RED] = main.intersection(outline)
    core[BLACK] = outline.difference(main)
    maxy = outline.bounds[3]

    def place(g, mirror):
        return affinity.translate(to_model(g, mirror), 0, maxy)

    solids = {}
    for c in COLORS:
        pieces = [extrude(place(back[c], True), 0, INLAY_BOTTOM),     # back face down, mirrored
                  extrude(place(core[c], False), INLAY_BOTTOM, THICK - INLAY_TOP),
                  extrude(place(front[c], False), THICK - INLAY_TOP, THICK)]
        pieces = [p for p in pieces if p is not None and not p.is_empty()]
        if pieces:
            solids[c] = m3d.Manifold.batch_boolean(pieces, m3d.OpType.Add)
    return solids, front, back, outline


def build(fonts, text, cid, rating, out_dir, preview=False):
    text, rating = text.strip(), rating.strip().upper()
    solids, front, back, outline = solids_for(fonts, text, cid, rating)
    slug = re.sub(r"[^a-z0-9]+", "_", f"{text}_{cid}_{TOP}".lower()).strip("_") or "keychain"
    out_dir = os.path.join(out_dir, slug)
    os.makedirs(out_dir, exist_ok=True)
    report, total = [], 0.0
    for c, solid in solids.items():
        path = os.path.join(out_dir, f"{slug}_{c}.stl")
        write_stl(solid, path)
        total += solid.volume()
        report.append((c, solid.volume(), solid.genus(), os.path.basename(path)))
    title = " ".join(x for x in (text, cid) if x)
    write_3mf([(title, solids, PLATE_CENTER, 0)], os.path.join(out_dir, f"{slug}.3mf"))
    if preview:
        render_preview(front, back, os.path.join(out_dir, f"{slug}_preview.png"), outline.bounds)
    return slug, report, total, outline


def render_preview(front, back, path, bounds):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path
    hexes = {BLACK: "#161616", WHITE: "#F3F1EA", GRAY: "#8C8C8A", RED: "#C8102E"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 6.2), facecolor="#E6E3DA")
    for ax, (title, layer) in zip(axes, (("FRONT (as seen)", front), ("BACK", back))):
        for c in COLORS:
            for p in _polys(layer[c]):
                rings = [p.exterior] + list(p.interiors)
                verts, codes = [], []
                for r in rings:
                    xy = list(r.coords)
                    verts += xy
                    codes += [Path.MOVETO] + [Path.LINETO] * (len(xy) - 2) + [Path.CLOSEPOLY]
                ax.add_patch(PathPatch(Path(verts, codes), facecolor=hexes[c], edgecolor="none"))
        ax.set_xlim(bounds[0] - 2, bounds[2] + 2); ax.set_ylim(bounds[3] + 2, bounds[1] - 2)
        ax.set_aspect("equal"); ax.axis("off")
        ax.set_title(title, fontsize=10)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def read_table(path):
    """One row per keychain. Columns: text (or name), cid, rating. cid and rating are optional."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]
    out = []
    for i, r in enumerate(rows, start=2):
        text = r.get("text") or r.get("name") or ""
        if not text and not r.get("cid"):
            continue  # blank line
        if not text:
            raise SystemExit(f"{path} line {i}: needs a 'text' (or 'name') column with the ribbon text")
        out.append({"text": text, "cid": r.get("cid", ""), "rating": r.get("rating", "")})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=os.path.join(HERE, "attendees.csv"))
    ap.add_argument("--text", "--name", dest="text", help="ribbon text for a single keychain, used as typed")
    ap.add_argument("--cid", default=""); ap.add_argument("--rating", default="")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--top", default="both", choices=list(TOPS) + ["both"],
                    help="orb: short finial holding the hole; spire: full statue with a ring boss above it")
    ap.add_argument("--preview", action="store_true", help="also write a PNG of both faces")
    args = ap.parse_args()

    people = ([{"text": args.text, "cid": args.cid, "rating": args.rating}] if args.text
              else read_table(args.csv))
    fonts = Fonts()
    grand = 0.0
    for top in (list(TOPS) if args.top == "both" else [args.top]):
        set_top(top)
        for p in people:
            slug, report, total, _ = build(fonts, p["text"], p["cid"], p["rating"], args.out, args.preview)
            grand += total
            print(f"{slug}: " + ", ".join(f"{c} {v:.0f} mm3" for c, v, g, _ in report) + f"  (total {total:.0f} mm3)")
    if len(people) > 1:
        print(f"{len(people)} keychains, {grand * 1.24e-3:.0f} g of plastic in the parts "
              f"(purge for color changes is extra)")


if __name__ == "__main__":
    main()
