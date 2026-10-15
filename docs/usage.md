# Usage

Commands are shown with `python -m iphone_color_pages`. After installation, `iphone-color-pages` accepts the same arguments. Run a command with `--help` for its available options.

## Set up Configurator

Install [Apple Configurator](https://apps.apple.com/us/app/apple-configurator/id1037126344?mt=12) on a supported Mac. The CLI can find the executable bundled inside the app without installing automation tools into `PATH`. Check the bundled version with:

```sh
"/Applications/Apple Configurator.app/Contents/MacOS/cfgutil" version
```

Connect the iPhone with a data-capable USB cable. Unlock it, accept **Trust This Computer** if requested, and complete any device-side trust confirmation. Apple Configurator must be able to access the device. If `devices` cannot see it, solve the connection or trust issue before continuing.

**Apple Configurator → Install Automation Tools** is an optional way to make `cfgutil` available in `PATH`. If automatic discovery does not suit your installation, use the global `--cfgutil` option **before** the subcommand:

```sh
python -m iphone_color_pages --cfgutil "/Applications/Apple Configurator.app/Contents/MacOS/cfgutil" devices
```

The underlying method was developed with Apple Configurator / `cfgutil` 2.21 and has one real-device trial on iOS 27.0.1. The reusable CLI itself has only synthetic and mocked-device tests, not real-device validation. This is not a supported-device matrix. Apple's current Mac App Store listing requires macOS 15.7 or later.

## Preview without a device

```sh
python -m iphone_color_pages demo --output .local/demo
```

This creates synthetic example data and a local preview. It does not read or write a phone, and it does not contain a real user's icons or app inventory.

## Scan and plan

```sh
python -m iphone_color_pages devices
python -m iphone_color_pages scan --ecid <ECID> --session .local/my-phone
python -m iphone_color_pages plan --session .local/my-phone
```

Use the exact ECID printed for the intended phone. `scan` requires a new, empty session directory and refuses a nonempty one. A session associates that device with its exported icons and layout snapshot. `plan` uses the scan's `snapshot.json` as its source unless `--source` is supplied. It works on local files and does not change the phone.

Review `preview.png`, `plan.json`, and `contact-sheets/icons-001.png` and subsequent sheets before applying. Automatic classification uses HSV image statistics, so it cannot reliably make all the visual decisions a person would. An icon with a large white background may look white despite a colorful logo; a dark blue icon may belong on the blue page; some gradients fit best under `multicolor`.

The original single-device arrangement used AI-assisted visual classification and manual correction. This CLI uses local HSV suggestions plus overrides, without an AI API; it does not automatically reproduce that earlier classification.

Check `scan-report.json` for missing or unreadable PNG images and export warnings. Missing images and web clips without exported artwork receive `multicolor` placeholders and appear under `needs_color_review` in `plan.json` unless overridden. This review list does not block `apply`; inspect and correct it yourself before confirming a write.

The valid colors, in page order, are:

```text
red orange yellow green teal blue purple pink black gray white multicolor
```

The Dock stays as it appears in the source layout. Other entries are grouped by color. Each used color gets one page. When one color exceeds the available space on its page, same-color folders hold the overflow, with nine icons per folder page. `--page-capacity` defaults to 24 visible slots (four columns by six rows). Choose a capacity that matches the space available in your layout, for example:

```sh
python -m iphone_color_pages plan --session .local/my-phone --page-capacity 20
```

Review the regenerated preview whenever you change capacity. A smaller capacity controls how many visible entries are planned; it does not preserve widgets omitted by `cfgutil`.

## Correct colors

Create `.local/overrides.json` as a JSON object from bundle identifiers to palette values:

```json
{
  "com.example.reader": "blue",
  "com.example.camera": "black",
  "com.example.notes": "white",
  "com.example.studio": "multicolor"
}
```

Use identifiers from your local scan rather than guessing from app names. Then regenerate the plan and inspect its contact sheets:

```sh
python -m iphone_color_pages plan --session .local/my-phone --overrides .local/overrides.json
```

Overrides describe colors; they do not independently add an app to the source layout. The plan follows the entries represented in the selected source. Every override identifier must exist in that source; a stale override referring to an app that is no longer present causes planning to fail.

## Apply and verify

Read [the limitations](safety-and-limitations.md), especially the widget and duplicate-entry restrictions. If you need a record of widgets or their placement, take your own screenshots on the device before applying.

```sh
python -m iphone_color_pages apply --session .local/my-phone --accept-widget-changes
python -m iphone_color_pages verify --session .local/my-phone
```

The first command displays the actual device and entry counts and requires an interactive confirmation. `--accept-widget-changes` acknowledges the known layout-representation limit; it is required even when using `--yes`.

For an explicitly intended noninteractive run:

```sh
python -m iphone_color_pages apply --session .local/my-phone --accept-widget-changes --yes
```

This still performs baseline and structural checks. If the phone already matches the target plan, it verifies without writing. Do not put a write command in a retry loop. When a write or verification fails, inspect the recorded snapshots before deciding what to do next.

## When verification fails

If the current device layout matches neither the plan's source nor its target, `apply` refuses to write. Plan from a fresh snapshot after checking why it changed. A current layout that already matches the target needs no write.

If iOS inserts extra App Library entries after a write, verification reports failure rather than silently dropping or accepting them. This was observed during the real-device trial. To intentionally incorporate the current layout:

```sh
python -m iphone_color_pages snapshot --session .local/my-phone --output .local/current-layout.json
python -m iphone_color_pages plan --session .local/my-phone --source .local/current-layout.json
```

`snapshot` reads the phone and refreshes locally exported icons for newly visible apps; it does not write a layout to the phone. It refuses to overwrite an existing output file, so choose a new output name for each later snapshot.

To reuse color corrections, add `--overrides .local/overrides.json` after removing keys absent from the new source. Otherwise stale overrides are rejected. Reapply any chosen `--page-capacity` value too; it defaults to 24 on each `plan` invocation. Inspect the new app set, color choices, counts, and preview, then apply the revised plan:

```sh
python -m iphone_color_pages apply --session .local/my-phone --accept-widget-changes
python -m iphone_color_pages verify --session .local/my-phone
```

`--source` establishes the explicitly reviewed readback as the new baseline. It is not an instruction to skip baseline matching. If the device changes again, another read and review is needed. There is no automatic restore operation, and a saved icon layout cannot guarantee restoration of widgets or duplicate entries.

## Session files

All paths below are relative to the session directory. `plan` regenerates its outputs when you revise overrides or choose a different source. `snapshot` saves to the path you explicitly pass with `--output` and refreshes the local asset inventory.

| File or directory | Purpose |
| --- | --- |
| `device.json` | Selected device identity, including ECID |
| `snapshot.json` | Original icon-layout snapshot from `scan`; default plan source |
| `manifest.json` | Local icon identifiers, display names, and entry kinds |
| `scan-report.json` | Missing/unreadable icons and export warnings |
| `icons/` | Exported PNG app artwork |
| `plan.json` | Source and target layouts, fingerprints, classifications, capacity, and review list |
| `planned-layout.json` | Generated target layout for inspection |
| `classifications.json` | Icon identifier to color mapping |
| `contact-sheets/icons-001.png` | First numbered icon review sheet; additional sheets follow |
| `preview.png` | Generated page preview |
| `before-TIMESTAMP.json` | Device layout read immediately before an apply attempt |
| `apply-payload-TIMESTAMP.json` | Validated layout payload for a write attempt |
| `readback-TIMESTAMP.json` | Device layout read after an apply attempt or during `verify`, when readable |
| `verification.json` | Latest comparison against the current plan |

## Keep personal data local

Use `.local/` for session directories, overrides, snapshots, exported icons, and previews. These files can reveal installed apps, device identifiers, and Home Screen organization. Do not post them in an issue or pull request without replacing personal data with a synthetic reproduction.
