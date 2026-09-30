"""Colored engineering drawing (A3, 2:1) of the keychain, written to docs/.

    python drawing.py --text "Carson B. (CB)" --cid 1652726 --rating SUP --top orb
"""
import argparse
import datetime
import os

import keychain
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import PathPatch, Rectangle, Circle
from matplotlib.path import Path
from shapely import affinity
from shapely.geometry import LineString

from keychain import (BLACK, WHITE, GRAY, RED, COLORS, CX, HOLE_D, OCULUS, THICK, INLAY, HERE,
                      FILAMENT_SLOT, Fonts, body_parts, ribbon_parts, circle, compose, front_items,
                      back_items, _polys, unary_union)

FILL = {BLACK: "#1d1d1d", WHITE: "#f4f2ec", GRAY: "#8e9089", RED: "#c8102e"}
INK = "#1a1a1a"
DIM = "#1f4e8c"      # dimension color
SHEET_W, SHEET_H = 420, 297
S = 2.0              # view scale
PLA_DENSITY = 1.24e-3  # g / mm3

for f in ("B612-Regular.ttf", "B612-Bold.ttf", "B612Mono-Regular.ttf", "B612Mono-Bold.ttf"):
    p = os.path.join(HERE, "fonts", f)
    if os.path.exists(p):
        font_manager.fontManager.addfont(p)
plt.rcParams["font.family"] = ["B612", "DejaVu Sans"]


def geometry(text, cid, rating):
    HOLE = keychain.HOLE
    fonts = Fonts()
    main, _ = ribbon_parts()
    outline = unary_union([body_parts(), main]).difference(circle(*HOLE, HOLE_D / 2))
    front = compose(front_items(fonts), outline)
    back = compose(back_items(fonts, text, cid, rating.upper()), outline)
    return outline, front, back, main


class Sheet:
    def __init__(self):
        self.fig = plt.figure(figsize=(SHEET_W / 25.4, SHEET_H / 25.4))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, SHEET_W)
        self.ax.set_ylim(0, SHEET_H)
        self.ax.set_aspect("equal")
        self.ax.axis("off")

    # -- placing design geometry (mm, y down) on the sheet (mm, y up) --
    @staticmethod
    def tf(g, ox, oy, s=S, x0=0.0, y0=0.0):
        g = affinity.translate(g, -x0, -y0)
        g = affinity.scale(g, s, -s, origin=(0, 0))
        return affinity.translate(g, ox, oy)

    def fill(self, g, color, lw=0.0, edge="none", z=1):
        for p in _polys(g):
            verts, codes = [], []
            for r in [p.exterior] + list(p.interiors):
                xy = list(r.coords)
                verts += xy
                codes += [Path.MOVETO] + [Path.LINETO] * (len(xy) - 2) + [Path.CLOSEPOLY]
            self.ax.add_patch(PathPatch(Path(verts, codes), facecolor=color, edgecolor=edge, lw=lw, zorder=z))

    def outline(self, g, lw=1.1, z=5):
        for p in _polys(g):
            for r in [p.exterior] + list(p.interiors):
                x, y = r.xy
                self.ax.plot(x, y, color=INK, lw=lw, zorder=z, solid_joinstyle="round")

    def text(self, x, y, s, size=7, ha="center", va="center", color=INK, weight="normal", rot=0, mono=False, z=10):
        self.ax.text(x, y, s, fontsize=size, ha=ha, va=va, color=color, weight=weight, rotation=rot,
                     family=["B612 Mono"] if mono else ["B612"], zorder=z)

    def line(self, x, y, lw=0.4, color=INK, ls="-", z=6):
        self.ax.plot(x, y, color=color, lw=lw, ls=ls, zorder=z)

    def arrow(self, p0, p1, color=DIM, both=True):
        style = "<|-|>" if both else "-|>"
        self.ax.annotate("", xy=p1, xytext=p0, zorder=8,
                         arrowprops=dict(arrowstyle=style, color=color, lw=0.5, shrinkA=0, shrinkB=0,
                                         mutation_scale=6))

    def hdim(self, x1, x2, yf1, yf2, yd, label, above=True):
        gap = 1.2
        for x, yf in ((x1, yf1), (x2, yf2)):
            d = 1 if yd > yf else -1
            self.line([x, x], [yf + d * gap, yd + d * 1.5], lw=0.35, color=DIM)
        self.arrow((x1, yd), (x2, yd))
        self.text((x1 + x2) / 2, yd + (1.8 if above else -1.8), label, size=6.5, color=DIM)

    def vdim(self, y1, y2, xf1, xf2, xd, label, left=True):
        gap = 1.2
        for y, xf in ((y1, xf1), (y2, xf2)):
            d = 1 if xd > xf else -1
            self.line([xf + d * gap, xd + d * 1.5], [y, y], lw=0.35, color=DIM)
        self.arrow((xd, y1), (xd, y2))
        self.text(xd + (-1.8 if left else 1.8), (y1 + y2) / 2, label, size=6.5, color=DIM, rot=90)

    def leader(self, tip, at, label, ha="left"):
        self.ax.annotate(label, xy=tip, xytext=at, fontsize=6.5, color=DIM, ha=ha, va="center", zorder=9,
                         family=["B612"],
                         arrowprops=dict(arrowstyle="-|>", color=DIM, lw=0.5, shrinkA=1, shrinkB=0, mutation_scale=6))

    def title(self, x, y, s, sub=None):
        self.text(x, y, s, size=8.5, weight="bold")
        if sub:
            self.text(x, y - 4.2, sub, size=6, color="#555")


def section_segments(layer_map, x):
    """Intersections of each color region with the vertical line at design x: {color: [(y0, y1), ...]}."""
    ln = LineString([(x, -5), (x, 65)])
    out = {}
    for c in COLORS:
        segs = []
        inter = layer_map[c].intersection(ln) if not layer_map[c].is_empty else None
        if inter is not None and not inter.is_empty:
            geoms = getattr(inter, "geoms", [inter])
            for g in geoms:
                if g.geom_type == "LineString":
                    ys = [p[1] for p in g.coords]
                    segs.append((min(ys), max(ys)))
        out[c] = segs
    return out


def draw(text, cid, rating, out_path, volumes=None):
    HOLE = keychain.HOLE
    outline, front, back, ribbon = geometry(text, cid, rating)
    sh = Sheet()
    ax = sh.ax
    x_min, y_min, x_max, y_max = outline.bounds
    W, H = x_max - x_min, y_max - y_min
    tf = lambda g, ox, oy, s=S: Sheet.tf(g, ox, oy, s, x_min, y_min)

    # sheet border and frame
    ax.add_patch(Rectangle((8, 8), SHEET_W - 16, SHEET_H - 16, fill=False, lw=1.2, ec=INK))
    ax.add_patch(Rectangle((10, 10), SHEET_W - 20, SHEET_H - 20, fill=False, lw=0.5, ec=INK))

    # ---------------- FRONT VIEW ----------------
    fx, fy = 36, 272  # top-left of view on sheet
    for c in COLORS:
        sh.fill(tf(front[c], fx, fy), FILL[c])
    sh.outline(tf(outline, fx, fy))
    sh.title(fx + W * S / 2, fy - H * S - 12, "FRONT VIEW", "SCALE 2:1")
    # center lines
    hx, hy = fx + (HOLE[0] - x_min) * S, fy - (HOLE[1] - y_min) * S
    sh.line([hx, hx], [fy + 4, fy - H * S - 4], lw=0.3, color="#555", ls=(0, (8, 2, 1, 2)))
    sh.line([hx - 7, hx + 7], [hy, hy], lw=0.3, color="#555", ls=(0, (8, 2, 1, 2)))
    # section A-A cutting plane marks
    for yy, dy in ((fy + 6, 1), (fy - H * S - 6, -1)):
        sh.line([hx, hx], [yy, yy - dy * 4], lw=1.2)
        sh.arrow((hx, yy), (hx + 6, yy), color=INK, both=False)
        sh.text(hx + 9, yy, "A", size=8, weight="bold")
    # dimensions
    sh.hdim(fx, fx + W * S, fy - (H - 5) * S, fy - (H - 5) * S, fy - H * S - 22, f"{W:.1f}")
    sh.vdim(fy, fy - H * S, fx + (W / 2) * S, fx + 0.1 * S, fx - 12, f"{H:.1f}")
    sh.vdim(fy, hy, fx + (W / 2) * S, hx - 2, fx - 5, f"{HOLE[1] - y_min:.2f}")
    sh.hdim(fx, hx, fy - (H - 8) * S, hy - 4, fy + 11, f"{HOLE[0] - x_min:.1f} (CL)")
    sh.leader((hx + HOLE_D / 2 * S * 0.7, hy + HOLE_D / 2 * S * 0.7), (hx + 26, hy + 12),
              f"Ø{HOLE_D} THRU\nFITS AN 8 mm SPLIT RING")
    sh.leader((hx + OCULUS * S * 0.95, hy + OCULUS * S * 0.3), (hx + 26, hy - 12),
              f"Ø{OCULUS * 2:.1f} WHITE RING\n{INLAY} DEEP BOTH FACES")

    # ---------------- RIGHT SIDE VIEW (third angle) ----------------
    sx = fx + W * S + 26
    t = THICK * S
    # visible edge: ribbon (red, full depth) at the bottom, black body above
    rib_top, rib_bot = fy - (47.0 - y_min) * S, fy - H * S
    ax.add_patch(Rectangle((sx, rib_top), t, fy - rib_top, fc=FILL[BLACK], ec="none", zorder=1))
    ax.add_patch(Rectangle((sx, rib_bot), t, rib_top - rib_bot, fc=FILL[RED], ec="none", zorder=1))
    ax.add_patch(Rectangle((sx, rib_bot), t, fy - rib_bot, fill=False, ec=INK, lw=1.1, zorder=5))
    for yy in (hy + HOLE_D / 2 * S, hy - HOLE_D / 2 * S):  # hidden hole edges
        sh.line([sx, sx + t], [yy, yy], lw=0.5, color="#bbb", ls=(0, (3, 1.5)))
    sh.line([sx - 3, sx + t + 3], [hy, hy], lw=0.3, color="#555", ls=(0, (8, 2, 1, 2)))
    sh.hdim(sx, sx + t, fy, fy, fy + 7, f"{THICK}")
    sh.text(sx - 3, fy + 2.5, "FRONT", size=5, rot=90, ha="right", va="top", color="#555")
    sh.text(sx + t + 3, fy + 2.5, "BACK", size=5, rot=90, ha="left", va="top", color="#555")
    sh.title(sx + t / 2, fy - H * S - 12, "RIGHT SIDE", "SCALE 2:1")

    # ---------------- BACK VIEW ----------------
    bx = sx + t + 26
    for c in COLORS:
        sh.fill(tf(back[c], bx, fy), FILL[c])
    sh.outline(tf(outline, bx, fy))
    sh.title(bx + W * S / 2, fy - H * S - 12, "BACK VIEW", f"SCALE 2:1  ·  SAMPLE: {text}")
    sh.leader((bx + 24.8 * S, fy - (49.9 - y_min) * S), (bx + W * S + 4, fy - 44 * S),
              "NAME: SHRINKS TO FIT\n38 mm MAX WIDTH")
    sh.leader((bx + 30.5 * S, fy - (22 - y_min) * S), (bx + W * S + 4, fy - 14 * S), "RATING BADGE\nWIDTH FITS TEXT")

    # ---------------- SECTION A-A ----------------
    ax0 = bx + W * S + 42
    segs = {"front": section_segments(front, CX), "back": section_segments(back, CX)}
    core_red = section_segments({c: (ribbon.intersection(outline) if c == RED else
                                     outline.difference(ribbon) if c == BLACK else outline.difference(outline))
                                 for c in COLORS}, CX)
    def band_rects(sg, z0, z1):
        for c, lst in sg.items():
            for (a, b) in lst:
                ax.add_patch(Rectangle((ax0 + z0 * S, fy - (b - y_min) * S), (z1 - z0) * S, (b - a) * S,
                                       fc=FILL[c], ec="none", zorder=2))
    band_rects(segs["front"], 0, INLAY)
    band_rects(core_red, INLAY, THICK - INLAY)
    band_rects(segs["back"], THICK - INLAY, THICK)
    # cut-face outline per solid run along the section line
    ln = outline.intersection(LineString([(CX, -5), (CX, 65)]))
    for g in getattr(ln, "geoms", [ln]):
        ys = [p[1] for p in g.coords]
        a, b = min(ys), max(ys)
        ax.add_patch(Rectangle((ax0, fy - (b - y_min) * S), t, (b - a) * S, fill=False, ec=INK, lw=0.9, zorder=5))
    sh.title(ax0 + t / 2, fy - H * S - 12, "SECTION A-A", "SCALE 2:1")
    ax.add_patch(Circle((ax0 + t / 2, hy), 11, fill=False, ec=INK, lw=0.6, ls=(0, (5, 2)), zorder=7))
    sh.text(ax0 + t / 2 + 10, hy + 10, "B", size=8, weight="bold")

    # ---------------- DETAIL B (hole + layer stack), 6:1 ----------------
    D = 5.0
    dx, dy = 346, 172  # bottom-left of detail frame
    y_lo, y_hi = max(HOLE[1] - 4.6, y_min), HOLE[1] + 4.6
    def dz(z): return dx + 8 + z * D
    def dyy(y): return dy + (y_hi - y) * D
    def detail_bands(sg, z0, z1):
        for c, lst in sg.items():
            for (a, b) in lst:
                a2, b2 = max(a, y_lo), min(b, y_hi)
                if b2 > a2:
                    ax.add_patch(Rectangle((dz(z0), dyy(b2)), (z1 - z0) * D, (b2 - a2) * D, fc=FILL[c], ec="none", zorder=2))
    detail_bands(segs["front"], 0, INLAY)
    detail_bands(core_red, INLAY, THICK - INLAY)
    detail_bands(segs["back"], THICK - INLAY, THICK)
    h0, h1 = HOLE[1] - HOLE_D / 2, HOLE[1] + HOLE_D / 2
    for (a, b) in ((y_lo, h0), (h1, y_hi)):
        ax.add_patch(Rectangle((dz(0), dyy(b)), THICK * D, (b - a) * D, fill=False, ec=INK, lw=0.9, zorder=5))
    # break lines
    for yy in (y_lo, y_hi):
        sh.line([dz(0) - 2, dz(THICK) + 2], [dyy(yy), dyy(yy)], lw=0.5, color="#666", ls=(0, (4, 1.5)))
    sh.vdim(dyy(h0), dyy(h1), dz(0), dz(0), dz(0) - 6, f"Ø{HOLE_D}")
    # part y grows downward, so y_lo is the top edge of the detail on the sheet
    top, bot = dyy(y_lo), dyy(y_hi)
    sh.hdim(dz(0), dz(INLAY), top, top, top + 6, f"{INLAY}")
    sh.hdim(dz(THICK - INLAY), dz(THICK), top, top, top + 6, f"{INLAY}")
    sh.hdim(dz(0), dz(THICK), bot, bot, bot - 7, f"{THICK}", above=False)
    sh.vdim(dyy(h0), top, dz(THICK), dz(THICK), dz(THICK) + 7, f"{h0 - y_min:.1f} ABOVE HOLE", left=False)
    sh.text(dz(INLAY / 2) - 3, top + 12, "FRONT INLAY", size=5.5, color="#555")
    sh.text(dz(THICK - INLAY / 2) + 3, top + 12, "BACK INLAY", size=5.5, color="#555")
    sh.text(dz(THICK / 2), dyy((h1 + y_hi) / 2), f"CORE\n{THICK - 2 * INLAY:.2f}", size=5.5, color="#ddd")
    sh.title(dz(THICK / 2), bot - 17, "DETAIL B", "HOLE AND LAYER STACK, SCALE 5:1")

    # ---------------- REFERENCE RENDER ----------------
    ref = os.path.join(HERE, "docs", f"render_front_hero_{keychain.TOP}.png")
    if os.path.exists(ref):
        img = plt.imread(ref)
        h_img = 48
        w_img = h_img * img.shape[1] / img.shape[0]
        rx = 20
        ry = 64
        ax.imshow(img, extent=(rx, rx + w_img, ry, ry + h_img), zorder=3)
        ax.add_patch(Rectangle((rx, ry), w_img, h_img, fill=False, ec="#999", lw=0.4, zorder=4))
        sh.text(rx + w_img + 4, ry + h_img - 4, "3D REFERENCE", size=7.5, weight="bold", ha="left")
        for i, line in enumerate(("Rendered from the print files.", "Not to scale. Split ring shown",
                                  "for reference, not printed.")):
            sh.text(rx + w_img + 4, ry + h_img - 9 - 4 * i, line, size=5.8, ha="left", color="#555")

    # ---------------- COLOR / FILAMENT TABLE ----------------
    tx, ty = 20, 58
    cols = [0, 14, 44, 104, 128]
    heads = ["SLOT", "FILAMENT", "WHERE", "VOLUME", "MASS"]
    where = {BLACK: "Body, columns, dome", WHITE: "Windows, hole ring, text",
             GRAY: "Lines, shading, ARTCC text", RED: "Ribbon (full depth), badge"}
    ax.add_patch(Rectangle((tx - 2, ty - 5 * 7 - 2), 150, 5 * 7 + 6, fill=False, ec=INK, lw=0.6))
    for i, hd in enumerate(heads):
        sh.text(tx + cols[i], ty, hd, size=6, ha="left", weight="bold")
    for r, c in enumerate(COLORS):
        yy = ty - 7 * (r + 1)
        sh.text(tx + cols[0] + 3, yy, str(FILAMENT_SLOT[c]), size=6.5, mono=True)
        ax.add_patch(Rectangle((tx + cols[1], yy - 2), 5, 4, fc=FILL[c], ec=INK, lw=0.4, zorder=6))
        sh.text(tx + cols[1] + 7, yy, c.upper(), size=6.5, ha="left")
        sh.text(tx + cols[2], yy, where[c], size=6.2, ha="left")
        if volumes:
            sh.text(tx + cols[3], yy, f"{volumes[c]:.0f} mm³", size=6.2, ha="left")
            sh.text(tx + cols[4], yy, f"{volumes[c] * PLA_DENSITY:.2f} g", size=6.2, ha="left")
    sh.text(tx, ty - 5 * 7 - 6, "Masses are the part only. Purge adds about 14 g per plate of 10-11, about 1.4 g each.",
            size=5.5, ha="left", color="#555")

    # ---------------- NOTES ----------------
    nx, ny = 182, 64
    notes = [
        "NOTES",
        "1. Material: PLA (Bambu PLA Basic), 4 colors via AMS. Bambu Lab P2S, 0.2 mm nozzle.",
        "2. Print front face down on the plate. Layer height 0.14 mm. Iron the top (back) surface.",
        f"3. Color inlays are flush, {INLAY} mm (3 layers) deep on each face. Core {THICK - 2 * INLAY:.2f} mm.",
        "4. Ribbon is red through its full thickness. All other core material is black.",
        "5. Minimum feature 0.55 mm. Minimum text cap height 1.9 mm (thinnest stroke 0.6 mm).",
        "6. Back ribbon is one free text field per attendee; rating and CID optional. See attendees.csv.",
        "7. Dimensions in mm. General tolerance ±0.2 unless noted.",
    ]
    for i, n in enumerate(notes):
        sh.text(nx, ny - i * 5.2, n, size=6.3 if i else 7.5, ha="left", weight="bold" if i == 0 else "normal")

    # ---------------- TITLE BLOCK ----------------
    tbx, tby, tbw, tbh = 300, 12, 108, 50
    ax.add_patch(Rectangle((tbx, tby), tbw, tbh, fill=False, ec=INK, lw=1.0))
    for yy in (tby + 36, tby + 24, tby + 12):
        sh.line([tbx, tbx + tbw], [yy, yy], lw=0.5)
    sh.line([tbx + 54, tbx + 54], [tby, tby + 24], lw=0.5)
    sh.text(tbx + 3, tby + 45, "vZDC LIVE 2026 KEYCHAIN", size=10, ha="left", weight="bold")
    sh.text(tbx + 3, tby + 39.5, "Night Ribbon · Virtual Washington ARTCC · Oct 17 · Vinton, VA", size=5.8, ha="left", color="#444")
    sh.text(tbx + 3, tby + 30, f"SAMPLE: {text} · {cid} · {rating.upper()} · TOP: {keychain.TOP.upper()}", size=6.5, ha="left")
    def cell(x, y, k, v):
        sh.text(x + 3, y + 8.3, k, size=4.8, ha="left", color="#666")
        sh.text(x + 3, y + 3.6, v, size=7, ha="left", weight="bold")
    cell(tbx, tby + 12, "PART NO.", "ZDC-KC-2026-01")
    cell(tbx + 54, tby + 12, "SCALE", "2:1 · DETAIL 5:1")
    cell(tbx, tby, "UNITS / TOL.", "mm · ±0.2")
    cell(tbx + 54, tby, "DATE · SHEET", f"{datetime.date.today():%Y-%m-%d} · 1/1")

    sh.fig.savefig(out_path + ".pdf")
    sh.fig.savefig(out_path + ".png", dpi=200)
    plt.close(sh.fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", "--name", dest="text", default="Carson B. (CB)")
    ap.add_argument("--top", default="orb", choices=list(keychain.TOPS))
    ap.add_argument("--cid", default="1652726")
    ap.add_argument("--rating", default="SUP")
    ap.add_argument("--out", default=os.path.join(HERE, "docs", "keychain_drawing"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    keychain.set_top(a.top)
    _, report, _, _ = keychain.build(keychain.Fonts(), a.text, a.cid, a.rating, os.path.join(HERE, "out"))
    volumes = {c: v for c, v, _, _ in report}
    out = f"{a.out}_{a.top}"
    draw(a.text, a.cid, a.rating, out, volumes)
    print("wrote", out + ".pdf/.png")


if __name__ == "__main__":
    main()
