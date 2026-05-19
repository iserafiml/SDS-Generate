"""
Generate the nine standard GHS hazard pictograms as PNG assets.

The PDF builder (`sds_pdf_builder._draw_pictogram_row`) already prefers
`assets/pictograms/GHS0X.png` and only falls back to the crude text-label
diamonds when those files are missing. This script renders recognizable
red-diamond pictograms (white field, black symbol) at high resolution with
4x supersampling for smooth edges, then writes them to that directory.

Run once:  python3 make_pictograms.py
The output PNGs are visual stand-ins; drop in the official UNECE artwork
under the same filenames at any time to override them.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

SS = 4                       # supersample factor
SIZE = 256                   # final px
S = SIZE * SS
RED = (208, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
OUT = Path(__file__).parent / "assets" / "pictograms"


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _frame(d: ImageDraw.ImageDraw) -> None:
    """Red GHS diamond (square rotated 45°) with white fill."""
    c = S / 2
    r = S * 0.46
    outer = [(c, c - r), (c + r, c), (c, c + r), (c - r, c)]
    bw = S * 0.055
    ri = r - bw * 1.42
    inner = [(c, c - ri), (c + ri, c), (c, c + ri), (c - ri, c)]
    d.polygon(outer, fill=RED)
    d.polygon(inner, fill=WHITE)


def _bone(d, x1, y1, x2, y2, w):
    d.line([(x1, y1), (x2, y2)], fill=BLACK, width=int(w))
    for (x, y) in ((x1, y1), (x2, y2)):
        ang = math.atan2(y2 - y1, x2 - x1)
        for s in (-1, 1):
            ox = x + math.cos(ang + s * math.pi / 2) * w * 0.5
            oy = y + math.sin(ang + s * math.pi / 2) * w * 0.5
            d.ellipse([ox - w * 0.62, oy - w * 0.62,
                       ox + w * 0.62, oy + w * 0.62], fill=BLACK)


def _star(d, cx, cy, ro, ri, n, fill):
    pts = []
    for i in range(n * 2):
        ang = -math.pi / 2 + i * math.pi / n
        rr = ro if i % 2 == 0 else ri
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    d.polygon(pts, fill=fill)


def sym_GHS05(d):  # Corrosion (tube→metal bar | tube→hand)
    surf = S * 0.66
    d.line([(S * 0.16, surf), (S * 0.84, surf)], fill=BLACK, width=int(S * 0.018))

    def tube(x, drip_to):
        d.line([(x - S * 0.05, S * 0.20), (x + S * 0.05, S * 0.255)],
               fill=BLACK, width=int(S * 0.045))           # tilted test tube
        d.polygon([(x + S * 0.045, S * 0.255), (x + S * 0.075, S * 0.30),
                   (x + S * 0.045, S * 0.34)], fill=BLACK)  # spout
        for k in range(3):                                  # falling drops
            yy = S * (0.34 + k * 0.05)
            d.ellipse([drip_to - S * 0.013, yy, drip_to + S * 0.013,
                       yy + S * 0.03], fill=BLACK)

    # LEFT — liquid eating a metal bar (wedge bitten out of the top)
    tube(S * 0.30, S * 0.345)
    d.polygon([(S * 0.20, surf), (S * 0.20, S * 0.57), (S * 0.30, S * 0.57),
               (S * 0.345, S * 0.49), (S * 0.39, S * 0.57), (S * 0.46, S * 0.57),
               (S * 0.46, surf)], fill=BLACK)

    # RIGHT — liquid dripping onto the back of a hand
    tube(S * 0.62, S * 0.665)
    d.polygon([(S * 0.55, surf), (S * 0.55, S * 0.58),
               (S * 0.585, S * 0.50), (S * 0.61, S * 0.58),
               (S * 0.635, S * 0.49), (S * 0.66, S * 0.58),
               (S * 0.685, S * 0.50), (S * 0.71, S * 0.58),
               (S * 0.78, S * 0.60), (S * 0.80, surf)], fill=BLACK)


def sym_GHS06(d):  # Skull & crossbones
    c = S / 2
    w = S * 0.085
    _bone(d, S * 0.30, S * 0.60, S * 0.70, S * 0.80, w)
    _bone(d, S * 0.70, S * 0.60, S * 0.30, S * 0.80, w)
    d.ellipse([S * 0.34, S * 0.26, S * 0.66, S * 0.58], fill=BLACK)
    d.polygon([(S * 0.40, S * 0.54), (S * 0.60, S * 0.54),
               (S * 0.58, S * 0.64), (S * 0.42, S * 0.64)], fill=BLACK)
    d.ellipse([S * 0.40, S * 0.36, S * 0.475, S * 0.45], fill=WHITE)
    d.ellipse([S * 0.525, S * 0.36, S * 0.60, S * 0.45], fill=WHITE)
    d.polygon([(S * 0.50, S * 0.45), (S * 0.47, S * 0.52),
               (S * 0.53, S * 0.52)], fill=WHITE)


def sym_GHS07(d):  # Exclamation mark
    c = S / 2
    d.polygon([(c - S * 0.045, S * 0.30), (c + S * 0.045, S * 0.30),
               (c + S * 0.028, S * 0.58), (c - S * 0.028, S * 0.58)], fill=BLACK)
    d.ellipse([c - S * 0.045, S * 0.63, c + S * 0.045, S * 0.72], fill=BLACK)


def sym_GHS08(d):  # Health hazard (silhouette + chest starburst)
    c = S / 2
    d.ellipse([c - S * 0.085, S * 0.30, c + S * 0.085, S * 0.46], fill=BLACK)
    d.polygon([(c - S * 0.20, S * 0.74), (c - S * 0.14, S * 0.50),
               (c + S * 0.14, S * 0.50), (c + S * 0.20, S * 0.74)], fill=BLACK)
    _star(d, c, S * 0.585, S * 0.115, S * 0.045, 6, WHITE)


def sym_GHS09(d):  # Environment (tree + fish over waterline)
    d.line([(S * 0.26, S * 0.60), (S * 0.74, S * 0.60)], fill=BLACK, width=int(S * 0.02))
    # bare tree
    d.line([(S * 0.36, S * 0.58), (S * 0.36, S * 0.30)], fill=BLACK, width=int(S * 0.03))
    d.line([(S * 0.36, S * 0.40), (S * 0.30, S * 0.32)], fill=BLACK, width=int(S * 0.022))
    d.line([(S * 0.36, S * 0.44), (S * 0.43, S * 0.36)], fill=BLACK, width=int(S * 0.022))
    # dead fish (belly up: X eye)
    d.polygon([(S * 0.50, S * 0.70), (S * 0.66, S * 0.64), (S * 0.50, S * 0.78)], fill=BLACK)
    d.ellipse([S * 0.56, S * 0.66, S * 0.74, S * 0.78], fill=BLACK)
    d.polygon([(S * 0.74, S * 0.68), (S * 0.80, S * 0.64),
               (S * 0.80, S * 0.80), (S * 0.74, S * 0.76)], fill=BLACK)
    xe = (S * 0.635, S * 0.70)
    d.line([(xe[0] - S * 0.013, xe[1] - S * 0.013),
            (xe[0] + S * 0.013, xe[1] + S * 0.013)], fill=WHITE, width=int(S * 0.009))
    d.line([(xe[0] - S * 0.013, xe[1] + S * 0.013),
            (xe[0] + S * 0.013, xe[1] - S * 0.013)], fill=WHITE, width=int(S * 0.009))


def _flame(d, cx, cy, scale):
    pts = [(cx, cy - 0.26 * scale), (cx + 0.12 * scale, cy - 0.05 * scale),
           (cx + 0.07 * scale, cy - 0.10 * scale), (cx + 0.15 * scale, cy + 0.14 * scale),
           (cx + 0.04 * scale, cy + 0.22 * scale), (cx - 0.06 * scale, cy + 0.20 * scale),
           (cx - 0.15 * scale, cy + 0.05 * scale), (cx - 0.05 * scale, cy - 0.02 * scale),
           (cx - 0.10 * scale, cy - 0.14 * scale)]
    d.polygon(pts, fill=BLACK)


def sym_GHS02(d):  # Flammable
    c = S / 2
    _flame(d, c, S * 0.50, S)
    d.line([(S * 0.30, S * 0.74), (S * 0.70, S * 0.74)], fill=BLACK, width=int(S * 0.022))


def sym_GHS03(d):  # Oxidizer (flame over circle)
    c = S / 2
    d.ellipse([S * 0.32, S * 0.42, S * 0.68, S * 0.78], outline=BLACK, width=int(S * 0.03))
    d.line([(S * 0.30, S * 0.60), (S * 0.70, S * 0.60)], fill=BLACK, width=int(S * 0.022))
    _flame(d, c, S * 0.34, S * 0.62)


def sym_GHS01(d):  # Explosive (bursting bomb)
    c = S / 2
    by = S * 0.60
    d.ellipse([c - S * 0.13, by - S * 0.13, c + S * 0.13, by + S * 0.13], fill=BLACK)
    # explosion spikes radiating from the top of the sphere
    ox, oy = c, by - S * 0.10
    for ang, ln in ((-90, 0.20), (-58, 0.16), (-32, 0.13), (-122, 0.16),
                     (-150, 0.13), (-12, 0.11), (-168, 0.11)):
        a = math.radians(ang)
        tx, ty = ox + math.cos(a) * S * ln, oy + math.sin(a) * S * ln
        pa = a + math.pi / 2
        d.polygon([(ox + math.cos(pa) * S * 0.028, oy + math.sin(pa) * S * 0.028),
                   (ox - math.cos(pa) * S * 0.028, oy - math.sin(pa) * S * 0.028),
                   (tx, ty)], fill=BLACK)


def sym_GHS04(d):  # Gas cylinder
    c = S / 2
    d.rounded_rectangle([c - S * 0.10, S * 0.30, c + S * 0.10, S * 0.74],
                        radius=S * 0.10, fill=BLACK)
    d.rectangle([c - S * 0.03, S * 0.24, c + S * 0.03, S * 0.32], fill=BLACK)


_SYMBOLS = {
    "GHS01": sym_GHS01, "GHS02": sym_GHS02, "GHS03": sym_GHS03,
    "GHS04": sym_GHS04, "GHS05": sym_GHS05, "GHS06": sym_GHS06,
    "GHS07": sym_GHS07, "GHS08": sym_GHS08, "GHS09": sym_GHS09,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for code, fn in _SYMBOLS.items():
        img, d = _canvas()
        _frame(d)
        fn(d)
        img = img.resize((SIZE, SIZE), Image.LANCZOS)
        img.save(OUT / f"{code}.png")
    print(f"Wrote {len(_SYMBOLS)} pictograms to {OUT}")


if __name__ == "__main__":
    main()
