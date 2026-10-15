"""The documented cfgutil icon format, without any device calls.

Top-level lists contain the Dock followed by Home Screen pages. A folder is
either [name, id, ...] or [name, [id, ...], [id, ...], ...]. A folder page is
not itself a folder: its first element is an icon and must never be skipped.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re


class LayoutError(ValueError):
    pass


def members(entry):
    if isinstance(entry, str):
        if not entry or any(ord(c) < 32 for c in entry):
            raise LayoutError("Icon identifiers must be nonempty strings without control characters")
        return [entry]
    if not isinstance(entry, list) or not entry or not isinstance(entry[0], str):
        raise LayoutError("Expected an icon identifier or [folder name, ...]")
    if any(ord(c) < 32 for c in entry[0]):
        raise LayoutError("Folder names cannot contain control characters")
    tail = entry[1:]
    if all(isinstance(item, str) for item in tail):
        return [icon for item in tail for icon in members(item)]
    if not all(isinstance(page, list) for page in tail):
        raise LayoutError("A folder cannot mix icon strings and folder page arrays")
    result = []
    for page in tail:
        if not all(isinstance(item, str) for item in page):
            raise LayoutError("Nested folders are not supported by cfgutil")
        result.extend(icon for item in page for icon in members(item))
    return result


def validate_layout(layout, *, max_slots=None):
    if not isinstance(layout, list) or len(layout) < 2:
        raise LayoutError("A layout must contain a Dock array and at least one Home Screen page")
    for i, page in enumerate(layout):
        if not isinstance(page, list):
            raise LayoutError(f"Layout entry {i} must be an array")
        if max_slots is not None and i and len(page) > max_slots:
            raise LayoutError(f"Page {i} exceeds the configured {max_slots} visible slots")
        for entry in page:
            members(entry)
    return layout


def icon_counter(pages):
    return Counter(icon for page in pages for entry in page for icon in members(entry))


def canonical(layout):
    """Normalize flat single-page folders; keep all page boundaries and positions."""
    validate_layout(layout)
    def normalize(entry):
        if isinstance(entry, str):
            return ("icon", entry)
        tail = entry[1:]
        pages = [tail] if tail and all(isinstance(x, str) for x in tail) else tail
        return ("folder", entry[0], tuple(tuple(p) for p in pages))
    return tuple(tuple(normalize(entry) for entry in page) for page in layout)


def fingerprint(layout):
    value = json.dumps(canonical(layout), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_app_id(value):
    # CtClient is an example of a valid legacy ID without a dot. URLs and the
    # '/' web-clip identifier must never become relative filesystem paths.
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value))


def make_folder(name, icons, folder_page_size=9):
    if folder_page_size < 1:
        raise LayoutError("Folder page size must be positive")
    return [name, *[icons[i:i + folder_page_size] for i in range(0, len(icons), folder_page_size)]]


def build_plan(source, classifications, palette, labels, *, slots=24):
    """One page per color, with excess entries in same-color folders.

    Up to `slots` direct icons remain visible. If a group is larger, the last
    slot becomes a folder. Duplicate icon occurrences are deliberately kept.
    Empty cfgutil folder placeholders carry no representable icons and are
    omitted; widgets cannot be represented by this format.
    """
    validate_layout(source)
    if not 4 <= slots <= 30:
        raise LayoutError("Visible slots must be between 4 and 30")
    palette = tuple(palette)
    ids = [icon for page in source[1:] for entry in page for icon in members(entry)]
    if not ids:
        raise LayoutError("Refusing to create a plan for an empty Home Screen")
    missing = sorted(set(ids) - set(classifications))
    if missing:
        raise LayoutError(f"Missing classifications for {len(missing)} icon identifiers")
    if any(classifications[icon] not in palette for icon in ids):
        raise LayoutError("A classification is outside the supported palette")
    target, summary = [deepcopy(source[0])], []
    for color in palette:
        group = [icon for icon in ids if classifications[icon] == color]
        if not group:
            continue
        page = group if len(group) <= slots else [*group[:slots - 1], make_folder(labels[color], group[slots - 1:])]
        target.append(page)
        summary.append({"color": color, "label": labels[color], "icons": len(group),
                        "visible_entries": len(page), "folders": sum(isinstance(e, list) for e in page)})
    validate_layout(target, max_slots=slots)
    if icon_counter(target[1:]) != icon_counter(source[1:]):
        raise LayoutError("The plan changed icon occurrences")
    if target[0] != source[0]:
        raise LayoutError("The plan changed the Dock")
    return target, summary


def verify_layout(expected, actual):
    """Describe differences; a successful cfgutil exit alone is not verification."""
    validate_layout(expected)
    validate_layout(actual)
    want, got = icon_counter(expected[1:]), icon_counter(actual[1:])
    missing, added = want - got, got - want
    position_match = canonical(expected) == canonical(actual)
    return {
        "ok": position_match,
        "dock_matches": canonical([expected[0], []])[0] == canonical([actual[0], []])[0],
        "expected_pages": len(expected) - 1,
        "actual_pages": len(actual) - 1,
        "missing": dict(missing),
        "added": dict(added),
        "positions_and_folders_match": position_match,
        "expected_icon_occurrences": sum(want.values()),
        "actual_icon_occurrences": sum(got.values()),
    }
