"""Generate the toolbox icon (desktop/toolbox.ico and desktop/toolbox.png).

Run:  .venv\\Scripts\\python desktop\\make_icon.py

The generated files are committed, so this only needs re-running when the
design changes. Pillow ships with Streamlit, so no extra dependency.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024  # draw large, downsample for crisp small sizes

BG = (22, 58, 89)        # deep steel blue
RING = (233, 238, 242)   # gauge bezel
FACE = (248, 250, 252)
TICK = (40, 52, 64)
RED = (205, 56, 46)
NEEDLE = (22, 58, 89)


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = SIZE

    # Rounded-square tile
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.2), fill=BG)

    # Pressure-gauge dial
    cx, cy, r = s / 2, s * 0.53, s * 0.36
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RING)
    rf = r * 0.86
    d.ellipse((cx - rf, cy - rf, cx + rf, cy + rf), fill=FACE)

    # 270-degree scale from 225 deg (lower left) clockwise to -45 deg (lower right)
    start, sweep = 225.0, 270.0
    # Red zone over the last fifth of the scale
    rz = rf * 0.92
    pil_start = -(start - sweep * 0.8)   # PIL angles run clockwise from +x
    pil_end = -(start - sweep)
    d.arc((cx - rz, cy - rz, cx + rz, cy + rz), pil_start, pil_end, fill=RED, width=int(s * 0.045))

    for i in range(11):
        a = math.radians(start - sweep * i / 10)
        major = i % 5 == 0
        r1 = rf * (0.66 if major else 0.74)
        r2 = rf * 0.86
        d.line(
            (cx + r1 * math.cos(a), cy - r1 * math.sin(a), cx + r2 * math.cos(a), cy - r2 * math.sin(a)),
            fill=TICK, width=int(s * (0.028 if major else 0.016)),
        )

    # Needle at ~62% of scale
    a = math.radians(start - sweep * 0.62)
    tip = (cx + rf * 0.78 * math.cos(a), cy - rf * 0.78 * math.sin(a))
    perp = a + math.pi / 2
    w = s * 0.032
    base1 = (cx + w * math.cos(perp), cy - w * math.sin(perp))
    base2 = (cx - w * math.cos(perp), cy + w * math.sin(perp))
    tail = (cx - rf * 0.18 * math.cos(a), cy + rf * 0.18 * math.sin(a))
    d.polygon([tip, base1, tail, base2], fill=NEEDLE)
    hub = s * 0.055
    d.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=NEEDLE)

    # Gauge stem / fitting at the bottom of the tile
    stem_w, top = s * 0.12, cy + r * 0.98
    d.rectangle((cx - stem_w / 2, top, cx + stem_w / 2, s * 0.95), fill=RING)
    hex_w = s * 0.2
    d.rectangle((cx - hex_w / 2, s * 0.9, cx + hex_w / 2, s * 0.95), fill=RING)
    return img


def main() -> None:
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(HERE / "toolbox.png")
    img.save(HERE / "toolbox.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {HERE / 'toolbox.ico'} and {HERE / 'toolbox.png'}")


if __name__ == "__main__":
    main()
