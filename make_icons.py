#!/usr/bin/env python3
"""Generate menu-bar icon (PNG, template) and app icon (.icns) for Token Spendie."""

import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent


def _font(size: int):
    for path in (
        "/System/Library/Fonts/SFNSRounded.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_menubar_icon():
    """A monochrome template icon (◈ diamond) that adapts to light/dark menu bar."""
    size = 44  # @2x for a ~22pt menu bar
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    r = size * 0.34
    # Outer diamond
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
              fill=(0, 0, 0, 255))
    # Inner cut-out for a "gem" look
    ri = r * 0.42
    d.polygon([(cx, cy - ri), (cx + ri, cy), (cx, cy + ri), (cx - ri, cy)],
              fill=(0, 0, 0, 0))
    out = HERE / "menubar_icon.png"
    img.save(out)
    print(f"✓ {out.name}")


def _rounded_rect(d, box, radius, fill):
    d.rounded_rectangle(box, radius=radius, fill=fill)


def make_app_iconset():
    """A colourful gauge-style app icon, exported to .icns via iconutil."""
    base = 1024
    img = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background: rounded "squircle" with vertical gradient (indigo → violet)
    top = (88, 86, 214)      # indigo
    bot = (159, 90, 253)     # violet
    grad = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(base):
        t = y / base
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        gd.line([(0, y), (base, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (base, base), 0)
    md = ImageDraw.Draw(mask)
    margin = base * 0.08
    md.rounded_rectangle([margin, margin, base - margin, base - margin],
                         radius=base * 0.225, fill=255)
    img.paste(grad, (0, 0), mask)

    # Gauge arc (270°) showing ~65% fill
    cx = cy = base / 2
    ring_r = base * 0.30
    ring_w = int(base * 0.075)
    start, sweep = 135, 270
    # track
    d.arc([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
          start, start + sweep, fill=(255, 255, 255, 70), width=ring_w)
    # value (green→amber blend)
    d.arc([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
          start, start + int(sweep * 0.65), fill=(126, 230, 160, 255), width=ring_w)

    # Center diamond gem
    r = base * 0.13
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
              fill=(255, 255, 255, 255))
    ri = r * 0.4
    d.polygon([(cx, cy - ri), (cx + ri, cy), (cx, cy + ri), (cx - ri, cy)],
              fill=top + (255,))

    iconset = HERE / "TokenSpendie.iconset"
    iconset.mkdir(exist_ok=True)
    specs = [
        (16, "16x16"), (32, "16x16@2x"),
        (32, "32x32"), (64, "32x32@2x"),
        (128, "128x128"), (256, "128x128@2x"),
        (256, "256x256"), (512, "256x256@2x"),
        (512, "512x512"), (1024, "512x512@2x"),
    ]
    for px, name in specs:
        img.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{name}.png")

    icns = HERE / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                   check=True)
    print(f"✓ {icns.name}")
    # keep the iconset around? remove for tidiness
    for p in iconset.glob("*.png"):
        p.unlink()
    iconset.rmdir()


if __name__ == "__main__":
    make_menubar_icon()
    make_app_iconset()
    print("Done.")
