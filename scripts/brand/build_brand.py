"""Build Offshoot's brand assets as SVG (docs/BRAND.md, ADR-051).

The wordmark is drawn from Inter's own outlines (the self-hosted, OFL-licensed subset in
frontend/public/fonts), shaped with HarfBuzz, so the SVGs need no font at all. The PNG and ICO
files are rasterized from these SVGs by scripts/brand/rasterize.mjs.

    uv run --with fonttools==4.60.1 --with brotli --with uharfbuzz==0.57.0 python scripts/brand/build_brand.py
"""

from __future__ import annotations

import io
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / "frontend" / "public" / "fonts" / "inter-var.woff2"
BRAND = ROOT / "assets" / "brand"
PUBLIC = ROOT / "frontend" / "public"

INK_DARK = "#0B0D12"  # text on light backgrounds
INK_LIGHT = "#F4F5F7"  # text on dark backgrounds
SURFACE = "#08090C"  # the darkest surface of the dark theme
GRADIENT = (("0", "#A3E635"), (".55", "#34D399"), ("1", "#22D3EE"))

# The mark, on a 64 x 64 grid: a block of legacy code (three lines of a listing) with a new
# shoot branching from its top edge. Block colours are mid-tones that hold on light and dark.
BLOCK = "#343B4D"
LINES = "#69738C"


def gradient(gid: str, x1: float, y1: float, x2: float, y2: float) -> str:
    stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in GRADIENT)
    return (
        f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'gradientUnits="userSpaceOnUse">{stops}</linearGradient>'
    )


def mark_body(gid: str, simple: bool = False) -> str:
    """The mark's shapes. `simple` drops a code line and thickens the shoot for 16-32 px."""
    if simple:
        return (
            f'<rect x="4" y="29" width="37" height="31" rx="8" fill="{BLOCK}"/>'
            f'<rect x="10.5" y="38" width="20" height="5" rx="2.5" fill="{LINES}"/>'
            f'<rect x="10.5" y="47" width="13" height="5" rx="2.5" fill="{LINES}"/>'
            f'<path d="M32 30 V25 C32 17 36.5 13 43.5 12" fill="none" stroke="url(#{gid})" '
            'stroke-width="7" stroke-linecap="round"/>'
            f'<path d="M40.5 15 C41 6 48 2 60 2.5 C60.5 13.5 54 20.5 42 19 Z" fill="url(#{gid})"/>'
        )
    return (
        f'<rect x="5" y="30" width="34" height="29" rx="8" fill="{BLOCK}"/>'
        f'<rect x="11" y="37.5" width="17" height="3.5" rx="1.75" fill="{LINES}"/>'
        f'<rect x="11" y="44.5" width="22" height="3.5" rx="1.75" fill="{LINES}"/>'
        f'<rect x="11" y="51.5" width="12" height="3.5" rx="1.75" fill="{LINES}"/>'
        f'<path d="M31 31 V25 C31 17.5 35.5 13.5 42.5 12.5" fill="none" stroke="url(#{gid})" '
        'stroke-width="5.5" stroke-linecap="round"/>'
        f'<path d="M40.5 14.5 C41 6 47.5 2.5 59 3 C59.5 13 53.5 19.5 42 18.5 Z" fill="url(#{gid})"/>'
        f'<path d="M30.5 24.5 C25.5 25 21 22 19.5 15.5 C25.5 14.5 29.5 18 30.5 24.5 Z" fill="url(#{gid})"/>'
    )


def mark_defs(gid: str) -> str:
    return gradient(gid, 14, 40, 58, 4)


def svg(width: float, height: float, body: str, title: str, view: str | None = None) -> str:
    view_box = view or f"0 0 {width:g} {height:g}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
        f'viewBox="{view_box}" role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n'
    )


def wordmark_paths(text: str, size: float, weight: float, tracking_em: float) -> tuple[str, float, float]:
    """Outlined text: one SVG path, its advance width and its cap height, at `size` px."""
    tt = TTFont(str(FONT))
    # HarfBuzz reads TrueType, not WOFF2, so it shapes a decompressed copy held in memory.
    raw = io.BytesIO()
    tt.flavor = None
    tt.save(raw)
    tt = TTFont(io.BytesIO(raw.getvalue()))
    face = hb.Face(raw.getvalue())
    font = hb.Font(face)
    font.set_variations({"wght": weight})
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True, "calt": True})

    upem = tt["head"].unitsPerEm
    scale = size / upem
    glyph_set = tt.getGlyphSet(location={"wght": weight})
    order = tt.getGlyphOrder()
    cap_height = tt["OS/2"].sCapHeight * scale
    pen = SVGPathPen(glyph_set, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    x = 0.0
    tracking = tracking_em * upem
    for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
        name = order[info.codepoint]
        # Flip the font's y-up outlines into SVG's y-down space, with the baseline at y = 0.
        transform = TransformPen(pen, (scale, 0, 0, -scale, (x + pos.x_offset) * scale, -pos.y_offset * scale))
        glyph_set[name].draw(transform)
        x += pos.x_advance + tracking
    width = (x - tracking) * scale
    return pen.getCommands(), width, cap_height


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print(f"wrote {path.relative_to(ROOT).as_posix()}")


def main() -> None:
    # The mark alone.
    mark = f"<defs>{mark_defs('osg')}</defs>{mark_body('osg')}"
    write(BRAND / "offshoot-mark.svg", svg(64, 64, mark, "Offshoot"))
    simple = f"<defs>{mark_defs('osg')}</defs>{mark_body('osg', simple=True)}"
    write(BRAND / "offshoot-mark-small.svg", svg(64, 64, simple, "Offshoot"))

    # The wordmark: Inter at weight 640, tracked in by 2.5% of the em.
    size = 48.0
    paths, width, cap = wordmark_paths("Offshoot", size, 640, -0.025)
    height = round(size * 1.25, 2)
    baseline = round((height + cap) / 2, 2)
    for variant, ink in (("on-dark", INK_LIGHT), ("on-light", INK_DARK)):
        body = f'<path transform="translate(0 {baseline})" fill="{ink}" d="{paths}"/>'
        write(BRAND / f"offshoot-wordmark-{variant}.svg", svg(round(width, 2), height, body, "Offshoot"))

    # The lockup: mark, then the wordmark, its cap height centred on the mark.
    mark_size = 56.0
    gap = 14.0
    lockup_w = round(mark_size + gap + width, 2)
    lockup_h = mark_size
    text_y = round(lockup_h / 2 + cap / 2, 2)
    for variant, ink in (("on-dark", INK_LIGHT), ("on-light", INK_DARK)):
        body = (
            f"<defs>{mark_defs('osg')}</defs>"
            f'<g transform="scale({mark_size / 64:g})">{mark_body("osg")}</g>'
            f'<path transform="translate({mark_size + gap:g} {text_y})" fill="{ink}" d="{paths}"/>'
        )
        write(BRAND / f"offshoot-logo-{variant}.svg", svg(lockup_w, lockup_h, body, "Offshoot"))

    # The app icon: the mark on the darkest surface, with a soft glow behind the shoot.
    icon = (
        "<defs>"
        f"{mark_defs('osg')}"
        '<radialGradient id="glow" cx="44" cy="14" r="34" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#34D399" stop-opacity=".28"/>'
        '<stop offset="1" stop-color="#34D399" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="edge" x1="0" y1="0" x2="0" y2="64" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity=".14"/>'
        '<stop offset="1" stop-color="#ffffff" stop-opacity=".03"/></linearGradient>'
        "</defs>"
        f'<rect width="64" height="64" rx="14" fill="{SURFACE}"/>'
        '<rect width="64" height="64" rx="14" fill="url(#glow)"/>'
        '<rect x=".5" y=".5" width="63" height="63" rx="13.5" fill="none" stroke="url(#edge)"/>'
        f'<g transform="translate(9.6 9.6) scale(.7)">{mark_body("osg")}</g>'
    )
    write(BRAND / "offshoot-app-icon.svg", svg(64, 64, icon, "Offshoot"))
    # Maskable: the safe zone is the inner 80%, so the mark is smaller and the field is full bleed.
    maskable = (
        f"<defs>{mark_defs('osg')}</defs>"
        f'<rect width="64" height="64" fill="{SURFACE}"/>'
        f'<g transform="translate(14.4 14.4) scale(.55)">{mark_body("osg")}</g>'
    )
    write(BRAND / "offshoot-app-icon-maskable.svg", svg(64, 64, maskable, "Offshoot"))

    # The favicon: the simple mark, which holds at 16 px on light and dark browser chrome.
    write(PUBLIC / "favicon.svg", svg(64, 64, simple, "Offshoot"))
    write(PUBLIC / "brand" / "offshoot-mark.svg", svg(64, 64, mark, "Offshoot"))

    # The Open Graph image, 1200 x 630. Its numbers are the stored rounding-defect run
    # (docs/EVALUATION.md: RATECALC 484 of 500, blocked; 500 of 500 after one repair).
    head_paths, head_w, head_cap = wordmark_paths("COBOL to C#, with proof.", 76, 700, -0.03)
    sub_paths, sub_w, _ = wordmark_paths("AI-assisted modernization that a harness has to agree with.", 28, 450, -0.01)
    stat_a, stat_a_w, _ = wordmark_paths("484 / 500", 30, 650, -0.01)
    stat_b, stat_b_w, _ = wordmark_paths("500 / 500", 30, 650, -0.01)
    lbl_a, lbl_a_w, _ = wordmark_paths("first translation: blocked", 20, 500, 0)
    lbl_b, lbl_b_w, _ = wordmark_paths("after one repair: verified", 20, 500, 0)
    og_logo = wordmark_paths("Offshoot", 40, 640, -0.025)
    caption, _, _ = wordmark_paths("RATECALC, 500 seeded cases (seed 20261107), from stored runs", 17, 450, 0)
    og = (
        "<defs>"
        f"{mark_defs('osg')}"
        f"{gradient('ogText', 80, 300, 1100, 200)}"
        '<radialGradient id="ogGlow" cx="980" cy="80" r="620" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#34D399" stop-opacity=".30"/>'
        '<stop offset=".45" stop-color="#22D3EE" stop-opacity=".08"/>'
        '<stop offset="1" stop-color="#22D3EE" stop-opacity="0"/></radialGradient>'
        '<pattern id="ogGrid" width="40" height="40" patternUnits="userSpaceOnUse">'
        '<path d="M40 0H0V40" fill="none" stroke="#ffffff" stroke-opacity=".045"/></pattern>'
        "</defs>"
        f'<rect width="1200" height="630" fill="{SURFACE}"/>'
        '<rect width="1200" height="630" fill="url(#ogGrid)"/>'
        '<rect width="1200" height="630" fill="url(#ogGlow)"/>'
        f'<g transform="translate(80 72) scale(.875)">{mark_body("osg")}</g>'
        f'<path transform="translate(150 {72 + 28 + og_logo[2] / 2:.2f})" fill="{INK_LIGHT}" d="{og_logo[0]}"/>'
        f'<path transform="translate(80 {300:g})" fill="url(#ogText)" d="{head_paths}"/>'
        f'<path transform="translate(80 360)" fill="#A6ADBB" d="{sub_paths}"/>'
        # Two result cards: blocked, then verified.
        '<rect x="80" y="430" width="440" height="120" rx="18" fill="#12141A" stroke="#ffffff" stroke-opacity=".08"/>'
        '<circle cx="118" cy="470" r="8" fill="#F87171"/>'
        f'<path transform="translate(140 481)" fill="{INK_LIGHT}" d="{stat_a}"/>'
        f'<path transform="translate(108 525)" fill="#A6ADBB" d="{lbl_a}"/>'
        '<path d="M548 490 H612 M598 476 L614 490 L598 504" fill="none" stroke="#69738C" stroke-width="4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<rect x="640" y="430" width="440" height="120" rx="18" fill="#12141A" stroke="#34D399" stroke-opacity=".45"/>'
        '<circle cx="678" cy="470" r="8" fill="#34D399"/>'
        f'<path transform="translate(700 481)" fill="{INK_LIGHT}" d="{stat_b}"/>'
        f'<path transform="translate(668 525)" fill="#A6ADBB" d="{lbl_b}"/>'
        f'<path transform="translate(80 594)" fill="#69738C" d="{caption}"/>'
    )
    write(BRAND / "offshoot-og.svg", svg(1200, 630, og, "Offshoot: COBOL to C#, with proof"))
    _ = (head_w, head_cap, sub_w, stat_a_w, stat_b_w, lbl_a_w, lbl_b_w)


if __name__ == "__main__":
    main()
