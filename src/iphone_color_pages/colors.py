"""Local, heuristic icon colors and image previews.

The classifier measures visible pixels; it does not recognize an app or infer a
brand color. A mostly white icon stays white even when its small logo is vivid.
Mixed artwork, gradients and unusual icons still benefit from a human review.
"""

from __future__ import annotations

import colorsys
import math
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


PALETTE = (
    "red", "orange", "yellow", "green", "teal", "blue", "purple", "pink",
    "black", "gray", "white", "multicolor",
)
LABELS = {
    "red": "红色", "orange": "橙色", "yellow": "黄色", "green": "绿色",
    "teal": "青色", "blue": "蓝色", "purple": "紫色", "pink": "粉色",
    "black": "黑色", "gray": "灰色", "white": "白色", "multicolor": "多色",
}

_SWATCHES = {
    "red": "#e94c4c", "orange": "#f6993f", "yellow": "#f4d658",
    "green": "#73b866", "teal": "#54bdb4", "blue": "#5088df",
    "purple": "#9371cf", "pink": "#e985b8", "black": "#25272b",
    "gray": "#a3a6ac", "white": "#ffffff", "multicolor": "#b0a3be",
}
_HUES = PALETTE[:8]


def _hue_color(hue: float) -> str:
    """Map a hue in degrees to the eight chromatic groups."""
    if hue < 12 or hue >= 355:
        return "red"
    for upper, color in (
        (42, "orange"), (70, "yellow"), (160, "green"), (190, "teal"),
        (255, "blue"), (292, "purple"), (355, "pink"),
    ):
        if hue < upper:
            return color
    return "red"


def classify_icon(path: Path) -> str:
    """Return one palette color from the visible center of an icon.

    Transparent pixels are ignored, including rounded corners. Near-white,
    black and gray regions are counted separately from hue. Several substantial
    hue groups without a dominant group produce ``multicolor``. An empty
    transparent icon is neutral white. Missing or unreadable files raise the
    corresponding Pillow / operating-system exception so callers can flag them
    for review instead of silently treating them as classified icons.
    """
    with Image.open(path) as source:
        icon = ImageOps.exif_transpose(source).convert("RGBA")
    if icon.width < 1 or icon.height < 1:
        raise ValueError(f"Icon has no pixels: {path}")
    # A small crop removes app-icon edges without throwing away the background.
    inset_x, inset_y = int(icon.width * .04), int(icon.height * .04)
    icon = icon.crop((inset_x, inset_y, icon.width - inset_x, icon.height - inset_y))
    icon.thumbnail((96, 96), Image.Resampling.LANCZOS)
    counts: Counter[str] = Counter()
    hue_vectors: dict[str, list[float]] = {color: [0., 0.] for color in _HUES}
    total = 0.
    pixels = icon.load()
    for index in range(icon.width * icon.height):
        red, green, blue, alpha = pixels[index % icon.width, index // icon.width]
        if alpha < 32:
            continue
        weight = alpha / 255.
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255., green / 255., blue / 255.)
        total += weight
        if value <= .16 or (value <= .22 and saturation < .50):
            color = "black"
        elif saturation <= .17 and value >= .87:
            color = "white"
        elif saturation < .23:
            color = "gray"
        else:
            color = _hue_color(hue * 360)
            hue_vectors[color][0] += math.cos(hue * math.tau) * weight
            hue_vectors[color][1] += math.sin(hue * math.tau) * weight
        counts[color] += weight
    if not total:
        return "white"
    fractions = {color: counts[color] / total for color in PALETTE}
    for color, threshold in (("white", .50), ("black", .57), ("gray", .57)):
        if fractions[color] >= threshold:
            return color
    chromatic = sum(counts[color] for color in _HUES)
    ranked = sorted(_HUES, key=lambda color: counts[color], reverse=True)
    strongest = ranked[0]
    if chromatic / total >= .25:
        if counts[strongest] / chromatic >= .62 or fractions[strongest] >= .42:
            return strongest
        # A hue at a bucket boundary, or a red-to-orange gradient, should not
        # become "multicolor" merely because two adjacent buckets are occupied.
        position = _HUES.index(strongest)
        neighbors = (_HUES[(position - 1) % 8], _HUES[(position + 1) % 8])
        neighbor = max(neighbors, key=lambda color: counts[color])
        if (counts[strongest] + counts[neighbor]) / chromatic >= .82:
            vector_x = hue_vectors[strongest][0] + hue_vectors[neighbor][0]
            vector_y = hue_vectors[strongest][1] + hue_vectors[neighbor][1]
            return _hue_color(math.degrees(math.atan2(vector_y, vector_x)) % 360)
        if chromatic / total >= .40 and counts[ranked[1]] / chromatic >= .18:
            return "multicolor"
    neutral = max(("white", "black", "gray"), key=lambda color: counts[color])
    return neutral if counts[neutral] >= counts[strongest] else strongest


def _font(size: int) -> tuple[Any, bool]:
    """Choose an installed font; ASCII text is used if CJK is unavailable."""
    cjk_paths = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    )
    for candidate in cjk_paths:
        try:
            return ImageFont.truetype(candidate, size), True
        except OSError:
            pass
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size), False
        except OSError:
            pass
    return ImageFont.load_default(), False


def _text(text: Any, cjk: bool) -> str:
    value = str(text)
    return value if cjk else value.encode("ascii", "replace").decode("ascii")


def _lines(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int, limit: int = 2) -> list[str]:
    """Wrap both CJK and long identifiers, bounding all output to the cell."""
    text = " ".join(text.split())[:240]
    lines: list[str] = []
    remaining = text
    while remaining and len(lines) < limit:
        take = 1
        while take < len(remaining) and draw.textlength(remaining[:take + 1], font=font) <= width:
            take += 1
        line, remaining = remaining[:take], remaining[take:]
        if len(lines) == limit - 1 and remaining:
            while line and draw.textlength(line + "...", font=font) > width:
                line = line[:-1]
            line += "..."
        lines.append(line)
    return lines or [""]


def _icon_file(icons_dir: Path, identifier: str) -> Path | None:
    # Web-clip IDs can be URLs. They must never become paths outside icons_dir.
    if not identifier or identifier in (".", "..") or "/" in identifier or "\\" in identifier:
        return None
    return icons_dir / f"{identifier}.png"


def _draw_icon(canvas: Image.Image, identifier: str, icons_dir: Path, xy: tuple[int, int], size: int,
               *, webclip: bool = False) -> None:
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    path = None if webclip else _icon_file(icons_dir, identifier)
    try:
        if path is None:
            raise FileNotFoundError(identifier)
        with Image.open(path) as source:
            icon = ImageOps.contain(ImageOps.exif_transpose(source).convert("RGBA"), (size, size))
        canvas.paste(icon, (x + (size - icon.width) // 2, y + (size - icon.height) // 2), icon)
    except (OSError, ValueError):
        draw.rounded_rectangle((x, y, x + size, y + size), radius=max(3, size // 5),
                               fill="#e4e7ed", outline="#c8ced8")
        font, _ = _font(max(10, size // 3))
        marker = "W" if webclip else "?"
        draw.text((x + size / 2, y + size / 2), marker, font=font, fill="#657186", anchor="mm")


def render_contact_sheets(records: list[dict], icons_dir: Path, output_dir: Path) -> list[Path]:
    """Render numbered icon review sheets, retaining input order and all records.

    Each sheet contains up to 64 records. Missing app images and web clips get a
    visible placeholder; their supplied color is still printed for review.
    """
    output_dir = Path(output_dir)
    icons_dir = Path(icons_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    title_font, cjk = _font(23)
    name_font, _ = _font(14)
    small_font, _ = _font(12)
    columns, per_sheet = 8, 64
    cell_width, cell_height, margin, header = 150, 148, 18, 58
    paths: list[Path] = []
    for start in range(0, len(records), per_sheet):
        batch = records[start:start + per_sheet]
        rows = math.ceil(len(batch) / columns)
        canvas = Image.new("RGB", (columns * cell_width + margin * 2,
                                   rows * cell_height + header + margin), "#f3f5f8")
        draw = ImageDraw.Draw(canvas)
        title = f"Icons {start + 1}-{start + len(batch)} / {len(records)}"
        draw.text((margin, 15), title, font=title_font, fill="#24334b")
        for offset, record in enumerate(batch):
            x = margin + (offset % columns) * cell_width
            y = header + (offset // columns) * cell_height
            identifier = str(record.get("id", ""))
            _draw_icon(canvas, identifier, icons_dir, (x + 35, y + 3), 80,
                       webclip=record.get("kind") == "webclip")
            name = str(record.get("name") or identifier or "Unknown")
            if not cjk and not name.isascii():
                name = identifier or name
            label = _text(f"{start + offset + 1:03d} {name}", cjk)
            for line_index, line in enumerate(_lines(draw, label, name_font, cell_width - 10)):
                draw.text((x + 5, y + 88 + line_index * 17), line, font=name_font, fill="#202a39")
            color = str(record.get("color", "multicolor"))
            if color not in PALETTE:
                color = "multicolor"
            draw.rounded_rectangle((x + 5, y + 126, x + 18, y + 139), radius=3,
                                   fill=_SWATCHES[color], outline="#bcc3cd")
            color_label = LABELS[color] if cjk else color
            draw.text((x + 24, y + 124), color_label, font=small_font, fill="#526074")
        destination = output_dir / f"icons-{len(paths) + 1:03d}.png"
        canvas.save(destination)
        paths.append(destination)
    return paths


def _members(entry: Any) -> list[str]:
    """Read the public layout representation without requiring device modules."""
    if isinstance(entry, str):
        return [entry]
    if not isinstance(entry, list) or not entry:
        return []

    def flatten(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [member for item in value for member in flatten(item)]
        return []

    # Folder representation: [display name, [members], ...] or [name, id, ...].
    return flatten(entry[1:]) if isinstance(entry[0], str) else flatten(entry)


def _draw_entry(canvas: Image.Image, entry: Any, icons_dir: Path, xy: tuple[int, int], size: int) -> str:
    if isinstance(entry, str):
        _draw_icon(canvas, entry, icons_dir, xy, size)
        return entry
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    draw.rounded_rectangle((x, y, x + size, y + size), radius=max(3, size // 5),
                           fill="#dce2eb", outline="#bac4d2")
    mini = max(5, (size - 8) // 3)
    for index, identifier in enumerate(_members(entry)[:9]):
        _draw_icon(canvas, identifier, icons_dir,
                   (x + 3 + (index % 3) * (mini + 1), y + 3 + (index // 3) * (mini + 1)), mini)
    return str(entry[0]) if isinstance(entry, list) and entry else "Folder"


def render_plan_preview(layout: list, classifications: dict[str, str], icons_dir: Path,
                        destination: Path, *, names: dict[str, str] | None = None) -> None:
    """Show the Dock and all pages in one PNG, including folder miniatures.

    ``layout[0]`` is the Dock, followed by pages containing app IDs or folder
    lists. It is an explanatory preview, not a screenshot of the phone.
    """
    if not isinstance(layout, list) or not layout or not all(isinstance(page, list) for page in layout):
        raise ValueError("Layout must contain a Dock list followed by page lists")
    icons_dir, destination = Path(icons_dir), Path(destination)
    names = names or {}
    dock, pages = layout[0], layout[1:]
    panel_width, panel_height, gap, margin = 282, 472, 18, 22
    columns = min(4, max(1, math.ceil(math.sqrt(len(pages)))))
    rows = max(1, math.ceil(len(pages) / columns))
    width = max(620, columns * panel_width + (columns - 1) * gap + 2 * margin)
    dock_height = 118 + max(0, math.ceil(len(dock) / 8) - 1) * 88
    header = 65 + dock_height
    canvas = Image.new("RGB", (width, header + rows * panel_height + (rows - 1) * gap + margin), "#edf1f7")
    draw = ImageDraw.Draw(canvas)
    title_font, cjk = _font(26)
    header_font, _ = _font(18)
    label_font, _ = _font(10)
    draw.text((margin, 18), "Color pages - layout preview", font=title_font, fill="#25354d")
    draw.text((margin, 65), "Dock", font=header_font, fill="#43546e")
    for index, entry in enumerate(dock):
        x, y = margin + 57 + (index % 8) * 68, 63 + (index // 8) * 88
        label = _draw_entry(canvas, entry, icons_dir, (x, y), 46)
        if isinstance(entry, str):
            label = names.get(entry, label)
        for line_index, line in enumerate(_lines(draw, _text(label, cjk), label_font, 62)):
            draw.text((x - 3, y + 49 + line_index * 12), line, font=label_font, fill="#485a74")
    if not pages:
        draw.text((margin, header + 20), "No Home Screen pages", font=header_font, fill="#657186")
    for page_index, page in enumerate(pages):
        x = margin + (page_index % columns) * (panel_width + gap)
        y = header + (page_index // columns) * (panel_height + gap)
        color_counts = Counter(classifications.get(identifier, "multicolor")
                               for entry in page for identifier in _members(entry))
        color = color_counts.most_common(1)[0][0] if color_counts else "white"
        if color not in PALETTE:
            color = "multicolor"
        draw.rounded_rectangle((x, y, x + panel_width, y + panel_height), radius=15,
                               fill="white", outline="#c5cedb", width=2)
        draw.rounded_rectangle((x + 14, y + 18, x + 29, y + 33), radius=4,
                               fill=_SWATCHES[color], outline="#bcc3cd")
        color_label = LABELS[color] if cjk else color
        draw.text((x + 39, y + 13), f"Page {page_index + 1} - {color_label}",
                  font=header_font, fill="#2a3d59")
        for entry_index, entry in enumerate(page[:24]):
            slot_x = x + 18 + (entry_index % 4) * 64
            slot_y = y + 56 + (entry_index // 4) * 67
            label = _draw_entry(canvas, entry, icons_dir, (slot_x + 8, slot_y), 44)
            if isinstance(entry, str):
                label = names.get(entry, label)
            for line_index, line in enumerate(_lines(draw, _text(label, cjk), label_font, 60)):
                draw.text((slot_x, slot_y + 46 + line_index * 10), line, font=label_font, fill="#53627a")
        if len(page) > 24:
            draw.text((x + 18, y + panel_height - 17), f"+ {len(page) - 24} entries omitted",
                      font=label_font, fill="#ad3737")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)
