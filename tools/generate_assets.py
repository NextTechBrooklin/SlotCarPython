r"""Export the procedural racing icon set to PNG files and build the app .ico.

Usage:  .venv\Scripts\python tools\generate_assets.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from slotcar import icons, theme as T  # noqa: E402
from slotcar.paths import APP_ICON_FILE, ICONS_DIR  # noqa: E402


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    names = [n for n in icons.ICONS if n != "logo"]
    for name in names:
        icons.render(name, 128, "#ffffff").save(ICONS_DIR / f"{name}.png")
    icons.app_icon(512, T.ACCENT).save(ICONS_DIR / "app_logo.png")
    icons.app_icon(256, T.ACCENT).save(APP_ICON_FILE, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    # Contact sheet for documentation.
    cell, cols = 132, 7
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), T.SURFACE)
    d = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        x, y = (i % cols) * cell, (i // cols) * cell
        im = icons.render(name, 72, T.TEXT)
        sheet.paste(im, (x + 30, y + 18), im)
        d.text((x + cell // 2, y + 108), name, fill=T.TEXT_MUTED, anchor="mm")
    sheet.save(ICONS_DIR / "_contact_sheet.png")
    print(f"Wrote {len(names)} icons to {ICONS_DIR} and {APP_ICON_FILE}")


if __name__ == "__main__":
    main()
