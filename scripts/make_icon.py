"""Generate a rich cannabis-leaf app icon for the TopShelf tray launcher.

Draws a stylized 7-leaflet cannabis leaf in the TopShelf palette (deep-green
radial background, emerald leaf with gold edges + veins) and writes a
multi-resolution ``assets/topshelf.ico`` (plus a ``topshelf.png`` preview).

Run once (the installer calls it):

    .\\.venv\\Scripts\\python.exe scripts\\make_icon.py

Idempotent — overwrites the icon each run.
"""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    raise SystemExit("Pillow is required: pip install Pillow")

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"

# TopShelf palette
BG_TOP = (24, 55, 31)        # #18371f
BG_BOTTOM = (6, 13, 9)       # #060d09
LEAF_TOP = (122, 206, 130)   # bright emerald
LEAF_BOTTOM = (28, 107, 57)  # #1c6b39
GOLD = (232, 198, 98)        # #e8c662
GOLD_DEEP = (184, 144, 46)   # #b8902e

S = 1024  # master render size (downscaled to icon sizes)
ICON_SIZES = [16, 32, 48, 64, 128, 256]


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """A size x size RGB image with a smooth top->bottom gradient."""
    col = Image.new("RGB", (1, size))
    px = col.load()
    for y in range(size):
        px[0, y] = _lerp(top, bottom, y / max(1, size - 1))
    return col.resize((size, size))


def _rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def _leaflet(length: float, width: float, teeth: int = 6) -> list[tuple]:
    """Polygon for one serrated leaflet pointing up (base at origin, tip at -length)."""
    left: list[tuple] = []
    right: list[tuple] = []
    for i in range(teeth + 1):
        f = i / teeth
        y = -length * f
        env = math.sin(math.pi * min(f, 0.999)) ** 0.5  # widest just past the base
        w = width * env * (1 - f * 0.12)
        tooth = 1.0 if i % 2 == 0 else 0.62  # serration in/out
        x = w * tooth
        left.append((-x, y))
        right.append((x, y))
    return left + [(0.0, -length)] + list(reversed(right))


def _rotate_translate(pts: list[tuple], ang: float, cx: float, cy: float) -> list[tuple]:
    ca, sa = math.cos(ang), math.sin(ang)
    return [(cx + (x * ca - y * sa), cy + (x * sa + y * ca)) for x, y in pts]


def _build_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded background with green radial-ish vertical gradient + gold rim.
    bg = _vertical_gradient(S, BG_TOP, BG_BOTTOM).convert("RGBA")
    mask = _rounded_mask(S, radius=int(S * 0.22))
    img.paste(bg, (0, 0), mask)
    rim = ImageDraw.Draw(img)
    rim.rounded_rectangle(
        [int(S * 0.012), int(S * 0.012), S - int(S * 0.012), S - int(S * 0.012)],
        radius=int(S * 0.205), outline=GOLD_DEEP, width=max(2, S // 160),
    )

    # Leaf geometry: 7 leaflets fanning up from a base near the lower-centre.
    cx, cy = S * 0.5, S * 0.78
    specs = [  # (angle_deg, length_frac, width_frac)
        (0, 0.60, 0.085),
        (30, 0.52, 0.078), (-30, 0.52, 0.078),
        (58, 0.40, 0.066), (-58, 0.40, 0.066),
        (84, 0.26, 0.052), (-84, 0.26, 0.052),
    ]

    # Leaf mask (all leaflets), then composite the leaf gradient through it.
    leaf_mask = Image.new("L", (S, S), 0)
    lmd = ImageDraw.Draw(leaf_mask)
    polys: list[list[tuple]] = []
    for ang_deg, lf, wf in specs:
        pts = _rotate_translate(
            _leaflet(S * lf, S * wf), math.radians(ang_deg), cx, cy
        )
        polys.append(pts)
        lmd.polygon(pts, fill=255)
    # Petiole (stem)
    lmd.line([(cx, cy), (cx, cy + S * 0.12)], fill=255, width=max(3, S // 120))

    leaf_grad = _vertical_gradient(S, LEAF_TOP, LEAF_BOTTOM).convert("RGBA")
    img.paste(leaf_grad, (0, 0), leaf_mask)

    # Gold outlines + central veins per leaflet.
    draw = ImageDraw.Draw(img)
    vein_w = max(2, S // 240)
    for (ang_deg, lf, wf), pts in zip(specs, polys):
        draw.line(pts + [pts[0]], fill=GOLD, width=max(2, S // 300), joint="curve")
        tip = (cx + math.sin(math.radians(ang_deg)) * S * lf,
               cy - math.cos(math.radians(ang_deg)) * S * lf)
        draw.line([(cx, cy), tip], fill=GOLD, width=vein_w)

    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = _build_master()

    preview = ASSETS / "topshelf.png"
    master.resize((256, 256), Image.LANCZOS).save(preview)

    ico = ASSETS / "topshelf.ico"
    master.save(ico, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    print(f"Wrote {ico} ({', '.join(str(s) for s in ICON_SIZES)}) and {preview}")


if __name__ == "__main__":
    main()
