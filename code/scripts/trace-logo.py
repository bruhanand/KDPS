#!/usr/bin/env python3
"""Turn the KDPS Lifestyle logo PNG into vector art.

The client's artwork exists only as a 350x87 PNG whose lettering is pure white,
so it is invisible on the app's cream paper. This script traces that PNG once,
and everything the app wears is generated from the trace:

  * app/frontend/src/components/KdpsLogo.tsx  - the lockup as inline SVG
  * app/frontend/public/kdps-mark.svg         - the ribbon mark, for the tab
  * app/frontend/public/icon-*.png            - the installed-app icons

Traced rather than hand-drawn, and committed rather than run at build time, so
the result is faithful to the client's own artwork and reproducible: re-run it
against a new PNG and every asset moves together.

How the trace works
-------------------
1. Every pixel is put in one colour class (four ribbon loops, the needle's dark
   body, its silver highlight, the white lettering). The class keeps the
   pixel's alpha as *coverage*, so the source anti-aliasing survives.
2. Each coverage map is upscaled 6x with LANCZOS, blurred a third of a source
   pixel and thresholded, which puts the outline back on a sub-pixel-accurate
   edge rather than on the source's own staircase. The ribbons are barely 2px
   wide - without this they trace as a wobble. The threshold is half coverage,
   which is also what keeps the weight honest: every traced class comes out
   within ~5% of the ink the source spends on it (the script prints it).
3. The boundary between inside and outside is chained into closed loops, then
   simplified (Douglas-Peucker) and softened (Chaikin, with the corner cut
   capped so letter corners stay sharp).
4. Loops are filled even-odd, which is exactly "XOR of the loop interiors" -
   so holes need no winding bookkeeping, and the PNG icons can be rasterised
   from the same loops by XOR-ing polygon masks.

Every trace is checked back against the mask it came from (intersection over
union, printed per class); a regression in the tracer shows up as a number,
not as a logo somebody has to squint at.

The theming trick
-----------------
The four ribbon loops carry their literal brand hexes. The needle and the
"KDPS LIFESTYLE" lettering are `currentColor`, so they take the colour of
whatever they sit in: navy on the light shell, pale on dark, white on the navy
login hero. One asset, no light/dark duplicates, no PNG to flash in.

Usage:  python3 code/scripts/trace-logo.py [--preview out.png]
Needs:  Pillow (11.3 here). Deliberately no numpy / scikit-image / cairosvg -
        this must run on a plain checkout.
"""

from __future__ import annotations

import argparse
import colorsys
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/data-from-kdps/05-reference-data/KDPS-logo.png"
FRONTEND = ROOT / "app/frontend"
COMPONENT = FRONTEND / "src/components/KdpsLogo.tsx"
MARK_SVG = FRONTEND / "public/kdps-mark.svg"

# Trace resolution: the source is upscaled this much before the outline is
# followed, so the outline lands between source pixels instead of on them.
SCALE = 6
# Blur applied after upscaling, in traced pixels. A hard threshold on an
# upscaled mask keeps the source's anti-aliasing ripple, and a Douglas-Peucker
# tolerance loose enough to swallow that ripple is also loose enough to bend a
# letter stem. Half a source pixel of blur removes the ripple instead: it moves
# a straight edge nowhere (a symmetric ramp still crosses 50% in the same
# place) and only softens corners, by about its own radius.
BLUR = 2.0
# Douglas-Peucker tolerance, in traced (6x) pixels: ~0.27 of a source pixel.
SIMPLIFY = 1.6
# Chaikin's corner cut, capped in traced pixels. Uncapped, Chaikin takes a
# quarter of each edge, which would bevel a letter stem into a chamfer.
SMOOTH_CAP = 1.8
SMOOTH_PASSES = 2
# Loops smaller than this (traced px^2, ~0.7 of a source pixel) are the source's
# own anti-aliasing speckle, not artwork.
MIN_AREA = 24.0

PAPER = (250, 247, 242)  # --paper, the icons' background
ICON_INK = (31, 45, 77)  # --navy, standing in for currentColor off-app

Point = tuple[float, float]
Loop = list[Point]


@dataclass(frozen=True)
class ClassDef:
    """One colour class of the artwork, and how it is painted."""

    key: str
    fill: str  # a literal hex, or "currentColor"
    in_mark: bool


# Draw order, back to front. Classes are disjoint (one pixel, one class), so
# order only decides what sits on top where two traces round into each other.
CLASSES: tuple[ClassDef, ...] = (
    ClassDef("lime", "#bed63a", True),
    ClassDef("orange", "#fcba63", True),
    ClassDef("cyan", "#57b6dd", True),
    ClassDef("red", "#e44044", True),
    ClassDef("silver", "#b6b6b6", True),
    ClassDef("needle", "currentColor", True),
    ClassDef("word", "currentColor", False),
)

# The mark's own square, in source coordinates: the lockup is the mark plus the
# wordmark to its right, and the mark alone is what narrow screens and the
# favicon show.
MARK_BOX = (0, 0, 87, 87)
FULL_BOX = (0, 0, 350, 87)


# --------------------------------------------------------------------------
# 1 · classify
# --------------------------------------------------------------------------
def classify(r: int, g: int, b: int) -> str | None:
    """Which class a pixel's colour belongs to (alpha is coverage, not class)."""
    hue, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    deg = hue * 360
    if val < 0.45:
        return "needle"
    if sat < 0.18:
        # The lettering is pure white; the needle's lit edge is mid-grey. One
        # threshold separates them, and it has to, because they are painted
        # differently: the lettering themes, the highlight does not.
        return "word" if val >= 0.93 else "silver"
    if deg < 20 or deg >= 330:
        return "red"
    if deg < 45:
        return "orange"
    if deg < 160:
        return "lime"
    if deg < 270:
        return "cyan"
    return None


def coverage_masks(image: Image.Image) -> dict[str, Image.Image]:
    """One greyscale coverage map per class, at source size."""
    width, height = image.size
    pixels = image.load()
    masks = {c.key: Image.new("L", (width, height), 0) for c in CLASSES}
    out = {key: mask.load() for key, mask in masks.items()}
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a < 8:  # fully transparent: its RGB means nothing
                continue
            key = classify(r, g, b)
            if key is not None:
                out[key][x, y] = a
    return masks


def upscale(mask: Image.Image) -> list[list[bool]]:
    """Coverage map -> binary grid at trace resolution."""
    width, height = mask.size
    big = mask.resize((width * SCALE, height * SCALE), Image.LANCZOS)
    big = big.filter(ImageFilter.GaussianBlur(BLUR))
    px = big.load()
    return [[px[x, y] >= 128 for x in range(big.width)] for y in range(big.height)]


# --------------------------------------------------------------------------
# 2 · follow the outline
# --------------------------------------------------------------------------
# Each inside pixel contributes the sides that face outside, directed so that
# the whole boundary reads clockwise (screen coordinates, y down) around solid
# regions and anticlockwise around holes.
_SIDES = (
    ((0, -1), (0, 0), (1, 0)),  # above is outside: left corner -> right corner
    ((1, 0), (1, 0), (1, 1)),  # right
    ((0, 1), (1, 1), (0, 1)),  # below
    ((-1, 0), (0, 1), (0, 0)),  # left
)


def _turn_rank(incoming: Point, outgoing: Point) -> int:
    """Order candidate directions at a junction: left turn first.

    A vertex where two inside pixels meet only at their corner has two ways on.
    Preferring the left turn keeps such a pair as one outline (8-connected),
    which matters here: the ribbons are one pixel wide in places and would
    otherwise trace as a string of separate diamonds.
    """
    ix, iy = incoming
    ox, oy = outgoing
    cross = ix * oy - iy * ox  # >0 is a clockwise turn in screen coordinates
    dot = ix * ox + iy * oy
    if cross < 0:
        return 0  # left
    if dot > 0:
        return 1  # straight on
    if cross > 0:
        return 2  # right
    return 3  # back the way we came


def trace(grid: list[list[bool]]) -> list[Loop]:
    """Chain the inside/outside boundary of a binary grid into closed loops."""
    height = len(grid)
    width = len(grid[0]) if height else 0
    edges: dict[Point, list[Point]] = {}
    for y in range(height):
        row = grid[y]
        for x in range(width):
            if not row[x]:
                continue
            for (dx, dy), (sx, sy), (ex, ey) in _SIDES:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and grid[ny][nx]:
                    continue
                edges.setdefault((float(x + sx), float(y + sy)), []).append(
                    (float(x + ex), float(y + ey))
                )

    loops: list[Loop] = []
    for start in list(edges):
        while edges.get(start):
            loop: Loop = [start]
            here = start
            incoming = (0.0, 0.0)
            while True:
                options = edges.get(here)
                if not options:
                    break
                if incoming == (0.0, 0.0):
                    nxt = options.pop()
                else:
                    nxt = min(
                        options,
                        key=lambda p: _turn_rank(incoming, (p[0] - here[0], p[1] - here[1])),
                    )
                    options.remove(nxt)
                incoming = (nxt[0] - here[0], nxt[1] - here[1])
                here = nxt
                if here == start:
                    break
                loop.append(here)
            if len(loop) >= 4:
                loops.append(loop)
    return loops


# --------------------------------------------------------------------------
# 3 · simplify and soften
# --------------------------------------------------------------------------
def _area(loop: Loop) -> float:
    total = 0.0
    for i, (x1, y1) in enumerate(loop):
        x2, y2 = loop[(i + 1) % len(loop)]
        total += x1 * y2 - x2 * y1
    return total / 2


def simplify(points: list[Point], epsilon: float) -> list[Point]:
    """Douglas-Peucker on an open run of points."""
    if len(points) < 3:
        return points
    (ax, ay), (bx, by) = points[0], points[-1]
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy)
    worst, index = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if span == 0:
            dist = math.hypot(px - ax, py - ay)
        else:
            dist = abs(dy * px - dx * py + bx * ay - by * ax) / span
        if dist > worst:
            worst, index = dist, i
    if worst <= epsilon:
        return [points[0], points[-1]]
    left = simplify(points[: index + 1], epsilon)
    right = simplify(points[index:], epsilon)
    return left[:-1] + right


def simplify_loop(loop: Loop, epsilon: float) -> Loop:
    # Split at the two furthest-apart-ish anchors so the closing point is not
    # privileged: simplifying a ring as one open run pins an arbitrary vertex.
    half = len(loop) // 2
    first = simplify([*loop[: half + 1]], epsilon)
    second = simplify([*loop[half:], loop[0]], epsilon)
    return first[:-1] + second[:-1]


def chaikin(loop: Loop, cap: float) -> Loop:
    """One corner-cutting pass, with the cut capped in absolute distance."""
    out: Loop = []
    count = len(loop)
    for i in range(count):
        ax, ay = loop[i]
        bx, by = loop[(i + 1) % count]
        length = math.hypot(bx - ax, by - ay)
        if length == 0:
            continue
        t = min(0.25, cap / length)
        out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        out.append((bx - (bx - ax) * t, by - (by - ay) * t))
    return out


def outline(grid: list[list[bool]]) -> list[Loop]:
    loops: list[Loop] = []
    for raw in trace(grid):
        loop = simplify_loop(raw, SIMPLIFY)
        if len(loop) < 3 or abs(_area(loop)) < MIN_AREA:
            continue
        for _ in range(SMOOTH_PASSES):
            loop = chaikin(loop, SMOOTH_CAP)
        loop = simplify_loop(loop, 0.12)
        if len(loop) >= 3:
            loops.append(loop)
    return loops


# --------------------------------------------------------------------------
# 4 · render back, to check and to make icons
# --------------------------------------------------------------------------
def fill_even_odd(loops: list[Loop], size: tuple[int, int], scale: float, offset: Point) -> Image.Image:
    """Rasterise loops even-odd: XOR of each loop's interior."""
    canvas = Image.new("1", size, 0)
    for loop in loops:
        layer = Image.new("1", size, 0)
        pts = [(x * scale + offset[0], y * scale + offset[1]) for x, y in loop]
        ImageDraw.Draw(layer).polygon(pts, fill=1)
        canvas = ImageChops.logical_xor(canvas, layer)
    return canvas


def iou(traced: Image.Image, grid: list[list[bool]]) -> float:
    px = traced.load()
    inter = union = 0
    for y, row in enumerate(grid):
        for x, on in enumerate(row):
            hit = px[x, y] != 0
            if on or hit:
                union += 1
                if on and hit:
                    inter += 1
    return inter / union if union else 1.0


# --------------------------------------------------------------------------
# 5 · emit
# --------------------------------------------------------------------------
def path_d(loops: list[Loop]) -> str:
    parts: list[str] = []
    for loop in loops:
        for i, (x, y) in enumerate(loop):
            sx = round(x / SCALE, 2)
            sy = round(y / SCALE, 2)
            parts.append(f"{'M' if i == 0 else 'L'}{sx:g} {sy:g}")
        parts.append("Z")
    return "".join(parts)


def svg_paths(traces: dict[str, list[Loop]], mark_only: bool) -> str:
    out: list[str] = []
    for spec in CLASSES:
        if mark_only and not spec.in_mark:
            continue
        loops = traces[spec.key]
        if not loops:
            continue
        out.append(f'<path fill="{spec.fill}" d="{path_d(loops)}" />')
    return "".join(out)


def write_component(traces: dict[str, list[Loop]]) -> None:
    full_w, full_h = FULL_BOX[2], FULL_BOX[3]
    mark_w, mark_h = MARK_BOX[2], MARK_BOX[3]
    body: list[str] = []
    for spec in CLASSES:
        loops = traces[spec.key]
        if not loops:
            continue
        body.append(
            f'  {{ fill: "{spec.fill}", mark: {"true" if spec.in_mark else "false"},'
            f' d: "{path_d(loops)}" }},'
        )
    paths = "\n".join(body)
    COMPONENT.write_text(
        f'''/* GENERATED by code/scripts/trace-logo.py from
   docs/data-from-kdps/05-reference-data/KDPS-logo.png - do not hand-edit.
   Re-run the script to change the artwork. */

/** The KDPS Lifestyle logo, as vector art traced from the client's own file.
 *
 *  The four ribbon loops keep their brand hexes. The needle and the "KDPS
 *  LIFESTYLE" lettering are `currentColor`, so the lockup takes the colour of
 *  whatever it sits in - navy on the light shell, pale in dark mode, white on
 *  the navy login hero. That is what makes one asset enough: the source PNG's
 *  lettering is pure white and would be invisible on our cream paper.
 *
 *  Sized like a `lucide-react` icon: give it a height and the width follows the
 *  artwork's own ratio. CSS wins over both, so a caller can set `width` and
 *  `height: auto` instead (the login hero does).
 */

type LogoPath = {{ fill: string; mark: boolean; d: string }};

const PATHS: LogoPath[] = [
{paths}
];

const FULL = {{ width: {full_w}, height: {full_h} }};
const MARK = {{ width: {mark_w}, height: {mark_h} }};

export type KdpsLogoProps = {{
  /** `"full"` is the whole lockup; `"mark"` is the ribbon alone, for narrow bars. */
  variant?: "full" | "mark";
  /** Rendered height in px; the width follows from the artwork. */
  height?: number;
  className?: string;
  /** Accessible name. Set it to "" for a purely decorative copy. */
  title?: string;
}};

export function KdpsLogo({{
  variant = "full",
  height = 28,
  className,
  title = "KDPS Lifestyle",
}}: KdpsLogoProps) {{
  const box = variant === "mark" ? MARK : FULL;
  const width = Math.round((height * box.width) / box.height);
  return (
    <svg
      className={{className}}
      viewBox={{`0 0 ${{box.width}} ${{box.height}}`}}
      width={{width}}
      height={{height}}
      role={{title ? "img" : undefined}}
      aria-label={{title || undefined}}
      aria-hidden={{title ? undefined : true}}
      focusable="false"
    >
      <g fillRule="evenodd">
        {{PATHS.filter((p) => variant === "full" || p.mark).map((p) => (
          <path key={{p.d.slice(0, 24)}} fill={{p.fill}} d={{p.d}} />
        ))}}
      </g>
    </svg>
  );
}}
'''
    )


def write_mark_svg(traces: dict[str, list[Loop]]) -> None:
    """The tab icon. `currentColor` has nothing to inherit from in a file loaded
    as an image, so the root element carries an explicit navy for it to take."""
    MARK_SVG.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 87 87" width="87" height="87" '
        f'color="#1f2d4d"><g fill-rule="evenodd">{svg_paths(traces, mark_only=True)}</g></svg>\n'
    )


def render_icon(traces: dict[str, list[Loop]], size: int, fraction: float) -> Image.Image:
    """The ribbon mark on paper, rendered from the vector at 4x and stepped down.

    From the vector rather than from the 87px source: there is no SVG
    rasteriser on a plain checkout, and upscaling the source would ship the
    blur the trace exists to remove.
    """
    ss = 4
    canvas = Image.new("RGB", (size * ss, size * ss), PAPER)
    span = size * ss * fraction
    scale = span / (MARK_BOX[2] * SCALE)
    offset = ((size * ss - span) / 2, (size * ss - span) / 2)
    for spec in CLASSES:
        if not spec.in_mark or not traces[spec.key]:
            continue
        mask = fill_even_odd(traces[spec.key], canvas.size, scale, offset)
        colour = ICON_INK if spec.fill == "currentColor" else _hex(spec.fill)
        canvas.paste(Image.new("RGB", canvas.size, colour), mask=mask)
    return canvas.resize((size, size), Image.LANCZOS)


def _hex(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def write_icons(traces: dict[str, list[Loop]]) -> None:
    public = FRONTEND / "public"
    render_icon(traces, 192, 0.76).save(public / "icon-192.png")
    render_icon(traces, 512, 0.76).save(public / "icon-512.png")
    render_icon(traces, 180, 0.76).save(public / "apple-touch-icon.png")
    # Maskable icons are cropped to a circle 80% of the icon across, so the art
    # has to fit a square inscribed in that circle: 0.8 / sqrt(2) ≈ 0.56.
    render_icon(traces, 512, 0.55).save(public / "icon-maskable-512.png")


def write_preview(traces: dict[str, list[Loop]], path: Path) -> None:
    """A flat PNG of the traced lockup, for eyeballing the trace itself."""
    scale = 3
    size = (FULL_BOX[2] * scale, FULL_BOX[3] * scale)
    canvas = Image.new("RGB", size, PAPER)
    for spec in CLASSES:
        if not traces[spec.key]:
            continue
        mask = fill_even_odd(traces[spec.key], size, scale / SCALE, (0.0, 0.0))
        colour = ICON_INK if spec.fill == "currentColor" else _hex(spec.fill)
        canvas.paste(Image.new("RGB", size, colour), mask=mask)
    canvas.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, help="also write a flat PNG of the trace")
    args = parser.parse_args()

    image = Image.open(SOURCE).convert("RGBA")
    masks = coverage_masks(image)
    traces: dict[str, list[Loop]] = {}
    for spec in CLASSES:
        grid = upscale(masks[spec.key])
        loops = outline(grid)
        traces[spec.key] = loops
        check = fill_even_odd(loops, (len(grid[0]), len(grid)), 1.0, (0.0, 0.0))
        points = sum(len(loop) for loop in loops)
        # Two numbers, so a change to the tracer is read rather than squinted at:
        # how much of the mask the trace lands on, and whether it spends the same
        # ink the source does (1.00 = same weight; over is fat, under is thin).
        drawn = sum(1 for v in check.getdata() if v) / SCALE**2
        spent = sum(masks[spec.key].getdata()) / 255
        print(
            f"{spec.key:>7}: {len(loops):3d} loops, {points:5d} points, "
            f"IoU {iou(check, grid):.3f}, weight {drawn / spent:.2f}"
        )

    write_component(traces)
    write_mark_svg(traces)
    write_icons(traces)
    if args.preview:
        write_preview(traces, args.preview)
    print(f"wrote {COMPONENT.relative_to(ROOT)}, {MARK_SVG.relative_to(ROOT)} and 4 icons")


if __name__ == "__main__":
    main()
