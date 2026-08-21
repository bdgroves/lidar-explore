r"""
Prepare figures for the web.

Analysis PNGs come out of matplotlib and QGIS at print resolution, which is far
too heavy for a blog post — the full set ran to about 11 MB. This resizes to a
sensible max width and picks the right encoder per image:

  * Charts and line art  -> PNG with a reduced palette. Flat colour compresses
    enormously this way and stays crisp.
  * Maps and rasters     -> JPEG. Continuous tone with millions of colours does
    not palettise well, and PNG cannot compress it usefully.

Writes into a web/ subfolder, leaving originals untouched, and prints a
before/after table.

Usage:
  python optimize_figures.py
  python optimize_figures.py --max-width 1600 --quality 82
  python optimize_figures.py --src data --dst data/web
"""
import argparse
from pathlib import Path

from PIL import Image

# Images with continuous tone (maps, rasters) -> JPEG.
# Everything else is chart/line art -> palettised PNG.
PHOTOGRAPHIC = {
    "map_nuuksio_story", "map_nuuksio_story_web",
    "fig1_overview", "fig4_change",
    "nuuksio_overview", "nuuksio_detection",
    "chm_change", "harvest_targeting",
}

DEFAULT_FILES = [
    "nuuksio_overview.png", "nuuksio_detection.png",
    "fig1_overview.png", "fig2_validation.png",
    "fig3_density.png", "fig4_change.png",
    "map_nuuksio_story_web.png", "map_nuuksio_story.png",
]


def flatten(im, bg=(253, 252, 248)):
    """Composite transparency onto the parchment background before JPEG."""
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[-1])
        return base
    return im.convert("RGB")


def process(path: Path, dst: Path, max_w: int, quality: int, colors: int):
    im = Image.open(path)
    before = path.stat().st_size

    if im.width > max_w:
        h = round(im.height * max_w / im.width)
        im = im.resize((max_w, h), Image.LANCZOS)

    stem = path.stem
    if stem in PHOTOGRAPHIC:
        out = dst / f"{stem}.jpg"
        flatten(im).save(out, "JPEG", quality=quality, optimize=True,
                         progressive=True, subsampling=1)
    else:
        out = dst / f"{stem}.png"
        pal = im.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT,
                                         dither=Image.FLOYDSTEINBERG)
        pal.save(out, "PNG", optimize=True)

    after = out.stat().st_size
    return out, before, after, im.size


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="data")
    ap.add_argument("--dst", default="data/web")
    ap.add_argument("--max-width", type=int, default=1800)
    ap.add_argument("--quality", type=int, default=84, help="JPEG quality")
    ap.add_argument("--colors", type=int, default=128, help="PNG palette size")
    ap.add_argument("--files", nargs="*", default=None)
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    names = args.files or DEFAULT_FILES

    print(f"{'file':32} {'before':>9} {'after':>9} {'saved':>7}  dimensions")
    print("-" * 74)
    tb = ta = 0
    for n in names:
        p = src / n
        if not p.exists():
            print(f"{n:32} {'--':>9} {'--':>9} {'':>7}  not found")
            continue
        out, b, a, size = process(p, dst, args.max_width, args.quality, args.colors)
        tb += b; ta += a
        print(f"{out.name:32} {b/1e6:8.2f}M {a/1e6:8.2f}M "
              f"{100*(1-a/b):6.0f}%  {size[0]}x{size[1]}")
    print("-" * 74)
    if tb:
        print(f"{'TOTAL':32} {tb/1e6:8.2f}M {ta/1e6:8.2f}M {100*(1-ta/tb):6.0f}%")
        print(f"\nWrote to {dst}/")
        print("Remember: JPEG outputs need .jpg in the HTML src, not .png")
