"""Local-first CLI. Only the explicit `apply` command writes to a phone."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

from PIL import Image, ImageDraw

from . import __version__
from .cfgutil import Configurator, DeviceError
from .colors import PALETTE, LABELS, classify_icon, render_contact_sheets, render_plan_preview
from .layout import (LayoutError, build_plan, canonical, fingerprint, icon_counter,
                     members, safe_app_id, validate_layout, verify_layout)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def session_device(session):
    data = read_json(session / "device.json")
    if data.get("demo") or not isinstance(data.get("ECID"), str) or not data["ECID"]:
        raise LayoutError("This session has no real device. Demo sessions cannot be applied.")
    return data


def make_manifest(layout, names):
    return [{"id": bid, "name": names.get(bid, bid),
             "kind": "app" if safe_app_id(bid) else "webclip"}
            for bid in sorted(icon_counter(layout))]


def refresh_assets(configurator, session, device, layout):
    old = read_json(session / "manifest.json") if (session / "manifest.json").exists() else []
    names = {r["id"]: r.get("name", r["id"]) for r in old}
    names.update(configurator.names(device["ECID"]))
    records = make_manifest(layout, names)
    warnings = configurator.export_icons(device["ECID"], [r["id"] for r in records], session / "icons")
    missing = []
    for r in records:
        if r["kind"] != "app":
            continue
        try:
            with Image.open(session / "icons" / f"{r['id']}.png") as image:
                if image.format != "PNG":
                    raise ValueError("Expected PNG")
                image.verify()
        except (OSError, ValueError):
            missing.append(r["id"])
    write_json(session / "manifest.json", records)
    write_json(session / "scan-report.json", {"missing_icons": missing, "warnings": warnings})
    if missing:
        print(f"Warning: {len(missing)} app icons are missing or unreadable. Review their multicolor placeholders.")


def cmd_devices(args):
    devices = Configurator(args.cfgutil).devices()
    if not devices:
        print("No connected devices. Connect by USB, unlock, and trust this Mac.")
    for device in devices:
        print(f"{device['ECID']}  {device.get('name', '(unnamed)')}  {device.get('deviceType', '')}")
    return 0


def cmd_scan(args):
    session = args.session.resolve()
    if session.exists() and any(session.iterdir()):
        raise LayoutError("Scan requires a new, empty session directory; existing phone snapshots are never overwritten.")
    configurator = Configurator(args.cfgutil)
    device = configurator.require_device(args.ecid)
    layout = configurator.layout(device["ECID"])
    session.mkdir(parents=True, exist_ok=True)
    # Only these fields are needed; never store UDID, serial, or unrelated account data.
    selected = {key: device[key] for key in ("ECID", "name", "deviceType") if key in device}
    write_json(session / "device.json", selected)
    write_json(session / "snapshot.json", layout)
    refresh_assets(configurator, session, selected, layout)
    print(f"Saved cfgutil icon-layout snapshot and local icons to {session}")
    print("This is not a full backup: cfgutil does not represent widgets or every duplicate Home Screen shortcut.")
    return 0


def cmd_snapshot(args):
    session = args.session.resolve()
    device = session_device(session)
    destination = args.output.resolve()
    if destination.exists():
        raise LayoutError("Snapshot output already exists; choose a new path to preserve earlier snapshots.")
    if destination in {session / "snapshot.json", session / "plan.json", session / "device.json", session / "manifest.json"}:
        raise LayoutError("Choose a separate snapshot output file")
    configurator = Configurator(args.cfgutil)
    device = configurator.require_device(device["ECID"])
    layout = configurator.layout(device["ECID"])
    write_json(destination, layout)
    refresh_assets(configurator, session, device, layout)
    print(f"Saved current icon layout to {destination}; refreshed icons for any newly visible apps.")
    return 0


def cmd_plan(args):
    session = args.session.resolve()
    device = read_json(session / "device.json")
    source_path = args.source.resolve() if args.source else session / "snapshot.json"
    source = validate_layout(read_json(source_path))
    ids = sorted(icon_counter(source))
    old = read_json(session / "manifest.json")
    names = {r["id"]: r.get("name", r["id"]) for r in old}
    records = make_manifest(source, names)
    overrides = read_json(args.overrides) if args.overrides else {}
    if not isinstance(overrides, dict) or any(not isinstance(k, str) or v not in PALETTE for k, v in overrides.items()):
        raise LayoutError("Overrides must be a JSON object mapping icon identifiers to supported palette names")
    if set(overrides) - set(ids):
        raise LayoutError("Overrides include identifiers that are absent from the selected source layout")
    classifications, needs_review = {}, []
    for record in records:
        bid = record["id"]
        if bid in overrides:
            color = overrides[bid]
        else:
            try:
                if record["kind"] != "app":
                    raise ValueError("Web clip icons are not exported by cfgutil")
                color = classify_icon(session / "icons" / f"{bid}.png")
            except (OSError, ValueError):
                color = "multicolor"
                needs_review.append(bid)
        classifications[bid] = color
        record["color"] = color
    target, summary = build_plan(source, classifications, PALETTE, LABELS, slots=args.page_capacity)
    plan = {"schema_version": 1, "device_ecid": device.get("ECID"),
            "source_fingerprint": fingerprint(source), "target_fingerprint": fingerprint(target),
            "source_layout": source, "layout": target, "classifications": classifications,
            "page_capacity": args.page_capacity, "summary": summary,
            "needs_color_review": needs_review}
    write_json(session / "plan.json", plan)
    write_json(session / "planned-layout.json", target)
    write_json(session / "classifications.json", classifications)
    render_contact_sheets(records, session / "icons", session / "contact-sheets")
    render_plan_preview(target, classifications, session / "icons", session / "preview.png", names=names)
    print(f"Planned {len(summary)} color pages, {sum(s['icons'] for s in summary)} icon occurrences; Dock unchanged.")
    for spec in summary:
        print(f"  {spec['color']}: {spec['icons']} icons, {spec['folders']} folder(s)")
    print(f"Review {session / 'preview.png'} and contact-sheets before applying. HSV suggestions need human review.")
    if needs_review:
        print(f"{len(needs_review)} missing images/web clips use multicolor placeholders; supply --overrides to correct them.")
    print("Planning did not access or write to the phone.")
    empty_folders = sum(isinstance(entry, list) and not members(entry) for page in source[1:] for entry in page)
    if empty_folders:
        print(f"{empty_folders} empty cfgutil placeholders have no representable icons and are omitted from the plan.")
    return 0


def load_plan(session):
    plan = read_json(session / "plan.json")
    if plan.get("schema_version") != 1:
        raise LayoutError("Unsupported plan schema; run plan again")
    source, target = plan["source_layout"], plan["layout"]
    validate_layout(source)
    validate_layout(target, max_slots=plan["page_capacity"])
    if fingerprint(source) != plan["source_fingerprint"] or fingerprint(target) != plan["target_fingerprint"]:
        raise LayoutError("Plan contents changed after generation. Edit overrides and run plan again.")
    if source[0] != target[0] or icon_counter(source[1:]) != icon_counter(target[1:]):
        raise LayoutError("Plan must retain the Dock and every source icon occurrence")
    for page in target[1:]:
        colors = {plan["classifications"].get(bid) for entry in page for bid in members(entry)}
        if len(colors) != 1 or not colors.issubset(set(PALETTE)):
            raise LayoutError("Every planned page must contain one supported color")
    return plan


def save_verification(session, plan, actual, tag):
    report = verify_layout(plan["layout"], actual)
    readback = session / f"readback-{tag}.json"
    write_json(readback, actual)
    write_json(session / "verification.json", report)
    if report["ok"]:
        print(f"Verified {report['actual_pages']} pages; Dock, icon occurrences, positions, and folder members match.")
        return 0
    print(f"Layout differs: {sum(report['missing'].values())} missing, {sum(report['added'].values())} added icon occurrences.")
    print(f"Saved readback to {readback} and details to {session / 'verification.json'}.")
    print("iOS may add App Library icons. No automatic rewrite or restore was attempted.")
    print(f"Replan explicitly with: iphone-color-pages snapshot --session {session} --output {session / 'current-layout.json'}")
    print("Then run plan --source <that snapshot>, review, and apply once more if appropriate.")
    return 3


def cmd_apply(args):
    session = args.session.resolve()
    device, plan = session_device(session), load_plan(session)
    if plan.get("device_ecid") != device["ECID"]:
        raise LayoutError("Plan device and session device do not match")
    if not args.accept_widget_changes:
        raise LayoutError("cfgutil can remove widgets and unrepresented duplicate shortcuts. Add --accept-widget-changes only if you accept this and can add them again.")
    if not args.yes:
        if not sys.stdin.isatty():
            raise LayoutError("Interactive confirmation requires a terminal. Noninteractive runs must explicitly pass --yes as well.")
        print(f"Device: {device.get('name', '(unnamed)')} ({device['ECID']})")
        print(f"Apply {len(plan['layout'])-1} pages with {sum(icon_counter(plan['layout'][1:]).values())} icon occurrences.")
        print("Widgets are not backed up; the original layout snapshot is not a complete undo.")
        if input(f"Type APPLY {device['ECID']} to write once: ").strip() != f"APPLY {device['ECID']}":
            print("Canceled without writing to the phone.")
            return 1
    configurator = Configurator(args.cfgutil)
    configurator.require_device(device["ECID"])
    current = configurator.layout(device["ECID"])
    tag = timestamp()
    write_json(session / f"before-{tag}.json", current)
    if canonical(current) == canonical(plan["layout"]):
        print("The phone already matches the plan; no device write was made.")
        return save_verification(session, plan, current, tag)
    if fingerprint(current) != plan["source_fingerprint"]:
        raise LayoutError("The phone layout changed since planning. No write made. Take a new snapshot, replan, and review it.")
    # Recreate the exact validated payload instead of trusting an independently
    # edited planned-layout.json next to the plan.
    payload = session / f"apply-payload-{tag}.json"
    write_json(payload, plan["layout"])
    try:
        configurator.apply(device["ECID"], payload)
    except DeviceError as exc:
        # A timeout/error does not prove that the write had no effect. One read
        # is useful, but never retry the mutation or attempt an automatic undo.
        try:
            actual = configurator.layout(device["ECID"])
            save_verification(session, plan, actual, tag)
        except DeviceError:
            pass
        raise DeviceError(f"Write could not be confirmed: {exc}. Inspect the phone and run verify before any further write.") from exc
    actual = configurator.layout(device["ECID"])
    return save_verification(session, plan, actual, tag)


def cmd_verify(args):
    session = args.session.resolve()
    device, plan = session_device(session), load_plan(session)
    if plan.get("device_ecid") != device["ECID"]:
        raise LayoutError("Plan device and session device do not match")
    configurator = Configurator(args.cfgutil)
    configurator.require_device(device["ECID"])
    return save_verification(session, plan, configurator.layout(device["ECID"]), timestamp())


def cmd_demo(args):
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise LayoutError("Choose a new empty demo directory")
    output.mkdir(parents=True, exist_ok=True)
    icons = output / "icons"
    icons.mkdir()
    rgb = {"red": "#e44747", "orange": "#f79a36", "yellow": "#f5db42", "green": "#59be68",
           "teal": "#45b8ae", "blue": "#3b81e9", "purple": "#8f5ad5", "pink": "#ed82b1",
           "black": "#151515", "gray": "#919191", "white": "#f7f7f7", "multicolor": "#ffffff"}
    records, classifications, ids = [], {}, []
    for color in PALETTE:
        count = 28 if color in ("blue", "white") else 3
        for i in range(count):
            bid = f"org.example.demo.{color}{i+1:02d}"
            ids.append(bid)
            classifications[bid] = color
            image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((0, 0, 127, 127), radius=27, fill=rgb[color])
            if color == "multicolor":
                for j, shade in enumerate(("#ed4c54", "#40b978", "#488be5")):
                    draw.ellipse((16+j*26, 30, 58+j*26, 92), fill=shade)
            else:
                draw.ellipse((44, 44, 84, 84), fill="#555555" if color == "white" else "#ffffff")
            image.save(icons / f"{bid}.png")
            records.append({"id": bid, "name": f"{color.title()} {i+1}", "kind": "app", "color": color})
    source = [[], *[ids[i:i+24] for i in range(0, len(ids), 24)]]
    write_json(output / "device.json", {"demo": True, "name": "Synthetic demo"})
    write_json(output / "snapshot.json", source)
    write_json(output / "manifest.json", records)
    target, summary = build_plan(source, classifications, PALETTE, LABELS)
    write_json(output / "planned-layout.json", target)
    write_json(output / "classifications.json", classifications)
    render_contact_sheets(records, icons, output / "contact-sheets")
    render_plan_preview(target, classifications, icons, output / "preview.png", names={r["id"]: r["name"] for r in records})
    print(f"Generated {len(summary)} pages using only synthetic icons at {output / 'preview.png'}; no device was accessed.")
    return 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--cfgutil", type=Path, help="Path to Apple's installed cfgutil executable")
    commands = p.add_subparsers(dest="command", required=True)
    devices = commands.add_parser("devices", help="List USB devices (read only)")
    devices.set_defaults(func=cmd_devices)
    scan = commands.add_parser("scan", help="Read icon-layout snapshot and export icons locally")
    scan.add_argument("--ecid", required=True)
    scan.add_argument("--session", type=Path, required=True)
    scan.set_defaults(func=cmd_scan)
    snap = commands.add_parser("snapshot", help="Read current layout and refresh exported icons")
    snap.add_argument("--session", type=Path, required=True)
    snap.add_argument("--output", type=Path, required=True)
    snap.set_defaults(func=cmd_snapshot)
    plan = commands.add_parser("plan", help="Build and preview a local plan without accessing the phone")
    plan.add_argument("--session", type=Path, required=True)
    plan.add_argument("--source", type=Path)
    plan.add_argument("--overrides", type=Path)
    plan.add_argument("--page-capacity", type=int, default=24, help="Visible slots per page; default 24 (four columns by six rows)")
    plan.set_defaults(func=cmd_plan)
    apply = commands.add_parser("apply", help="Write a reviewed plan once, then read back and verify")
    apply.add_argument("--session", type=Path, required=True)
    apply.add_argument("--accept-widget-changes", action="store_true")
    apply.add_argument("--yes", action="store_true", help="Skip the typed device confirmation; widget acceptance is still required")
    apply.set_defaults(func=cmd_apply)
    verify = commands.add_parser("verify", help="Read and compare against the current plan")
    verify.add_argument("--session", type=Path, required=True)
    verify.set_defaults(func=cmd_verify)
    demo = commands.add_parser("demo", help="Generate a synthetic preview without a phone")
    demo.add_argument("--output", type=Path, required=True)
    demo.set_defaults(func=cmd_demo)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (DeviceError, LayoutError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("Interrupted. If a write was in progress, inspect the phone and run verify before retrying.", file=sys.stderr)
        return 130
