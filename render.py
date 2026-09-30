"""Photo-style 3D renders of a generated keychain (needs pyvista: pip install pyvista).

    python render.py out/carson_berget_1652726
Writes PNGs to docs/.
"""
import glob
import math
import os
import sys

import numpy as np
import pyvista as pv

import keychain

HERE = os.path.dirname(os.path.abspath(__file__))
PLA = {"black": "#1b1b1b", "white": "#f2f0ea", "gray": "#8e9089", "red": "#c11a2b"}
THICK = keychain.THICK
RING_D, RING_WIRE = 8.0, 1.2   # the split ring from the keychain kit


def load_parts(folder):
    parts = {}
    for c in PLA:
        f = glob.glob(os.path.join(folder, f"*_{c}.stl"))
        if f:
            parts[c] = pv.read(f[0])
    return parts


def split_ring(hole_xy, hole_r, radius, wire):
    """Steel split ring through the hole, in the plane that contains the hole axis."""
    ring = pv.ParametricTorus(ringradius=radius, crosssectionradius=wire, u_res=160, v_res=24)
    ring = ring.rotate_y(90, inplace=False)                 # ring plane -> YZ
    # the keychain hangs with the top of the hole resting on the wire
    return ring.translate((hole_xy[0], hole_xy[1] + hole_r - wire + radius, THICK / 2), inplace=False)


def scene(parts, window=(2400, 1800), ring=None, bg=("#f1efe9", "#d9d5cb")):
    p = pv.Plotter(off_screen=True, window_size=window, lighting="none")
    p.set_background(bg[1], top=bg[0])
    for c, mesh in parts.items():
        p.add_mesh(mesh, color=PLA[c], smooth_shading=False, specular=0.35 if c != "black" else 0.5,
                   specular_power=28, ambient=0.18, diffuse=0.85)
    if ring:
        p.add_mesh(split_ring(*ring), color="#c9ccd1", specular=1.0, specular_power=60, ambient=0.25,
                   diffuse=0.6, smooth_shading=True)
    key = pv.Light(position=(-60, 120, 160), focal_point=(25, 28, 2), intensity=0.95)
    fill = pv.Light(position=(140, -40, 90), focal_point=(25, 28, 2), intensity=0.35)
    rim = pv.Light(position=(25, 200, -120), focal_point=(25, 28, 2), intensity=0.45)
    for l in (key, fill, rim):
        p.add_light(l)
    p.enable_anti_aliasing("ssaa")
    return p


def shoot(parts, path, cam, ring=None, window=(2400, 1800), zoom=1.0):
    p = scene(parts, window, ring)
    p.camera_position = cam
    p.camera.zoom(zoom)
    p.screenshot(path, transparent_background=False)
    p.close()
    print("wrote", path)


def orbit(center, dist, az, el):
    az, el = math.radians(az), math.radians(el)
    return (center[0] + dist * math.cos(el) * math.sin(az),
            center[1] + dist * math.sin(el),
            center[2] + dist * math.cos(el) * math.cos(az))


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(HERE, "out", "*")))[0]
    out = os.path.join(HERE, "docs")
    os.makedirs(out, exist_ok=True)
    top = next((t for t in keychain.TOPS if folder.rstrip("/\\").endswith("_" + t)), "orb")
    keychain.set_top(top)
    parts = load_parts(folder)
    y_max = max(m.bounds[3] for m in parts.values())
    # design y grows downward and the model is placed with the ribbon's bottom edge at Y = 0
    base = keychain.ribbon_parts()[0].bounds[3]
    hole = (keychain.HOLE[0], base - keychain.HOLE[1])
    ring = (hole, keychain.HOLE_D / 2, (keychain.TOPS[top]["ring_d"] - RING_WIRE) / 2, RING_WIRE / 2)
    lo = min(m.bounds[2] for m in parts.values())
    ctr = (25.0, (y_max + lo) / 2, 2.0)

    front = {c: m.copy() for c, m in parts.items()}
    # turn it over (180 degrees about Y) so the front faces the +z cameras
    for m in front.values():
        m.points[:, 0] = 50.0 - m.points[:, 0]
        m.points[:, 2] = THICK - m.points[:, 2]
    up = (0, 1, 0)
    dist = 150 + (y_max - lo) * 0.9
    shoot(front, os.path.join(out, f"render_front_hero_{top}.png"),
          [orbit(ctr, dist, -28, 14), ctr, up], ring=ring, zoom=1.05)
    shoot(parts, os.path.join(out, f"render_back_hero_{top}.png"),
          [orbit(ctr, dist, 30, 10), ctr, up], ring=ring, zoom=1.05)
    if "--all" in sys.argv:
        shoot(front, os.path.join(out, f"render_front_flat_{top}.png"),
              [(25, ctr[1], 150), (25, ctr[1], 2), up], window=(1800, 2000), zoom=1.0)
        shoot(front, os.path.join(out, f"render_edge_{top}.png"),
              [orbit(ctr, dist * 1.1, -62, 18), ctr, up], ring=ring, zoom=0.95)


if __name__ == "__main__":
    main()
