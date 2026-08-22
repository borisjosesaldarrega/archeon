"""Render the native Ghost radial geometry for transparent-window visual QA."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from archeon.ui.ghost_native import radial_layout


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "ui-comparison" / "after" / "ghost-radial.png"


def font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = Path("C:/Windows/Fonts") / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def main() -> int:
    edge, center, orb_size = 336, 168, 112
    radius, node_half = 121, 22
    image = Image.new("RGBA", (edge, edge), (2, 7, 9, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse((center - radius, center - radius, center + radius, center + radius), outline=(8, 125, 153, 180), width=1)

    actions = (("↗", "Abrir"), ("●", "Escuchar"), ("A", "Apps"), ("G", "Juegos"), ("★", "Favoritos"), ("⚙", "Configuración"))
    symbol_font = font("seguisym.ttf", 18)
    label_font = font("segoeui.ttf", 10)
    for (icon, _label), (x, y) in zip(actions, radial_layout(len(actions), center, radius)):
        angle = math.atan2(y - center, x - center)
        start = (center + math.cos(angle) * orb_size / 2, center + math.sin(angle) * orb_size / 2)
        draw.line((start, (x, y)), fill=(8, 125, 153, 190), width=1)
        draw.ellipse((x - node_half, y - node_half, x + node_half, y + node_half), fill=(7, 26, 33, 255), outline=(0, 217, 245, 255), width=2)
        draw.text((x, y), icon, font=symbol_font, fill=(229, 255, 255), anchor="mm")

    logo = Image.open(ROOT / "src" / "archeon" / "ui" / "logo_asitente.png").convert("RGBA")
    logo = ImageOps.contain(logo, (82, 82), Image.Resampling.LANCZOS)
    draw.ellipse((center - 56, center - 56, center + 56, center + 56), fill=(4, 15, 20, 255), outline=(8, 217, 255, 255), width=3)
    image.alpha_composite(logo, (center - logo.width // 2, center - logo.height // 2))
    draw.text((center, 319), "Aplicaciones", font=label_font, fill=(185, 250, 255), anchor="mm")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
