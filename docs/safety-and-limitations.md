# Safety and limitations

## What the tool changes

`apply` writes a Home Screen icon layout through Apple's `cfgutil`. All other commands either read the device or work on local files. The tool does not use OpenAI, an AI API, cloud classification, or telemetry. It needs no API key. Python package installation may use the network to download dependencies.

The plan preserves the Dock represented in its source and groups the other represented app entries into color pages. Overflow is held in same-color folders, with nine icons per folder page. The default visible page capacity is 24 slots; `plan --page-capacity` can change it, and the regenerated preview needs review.

## A snapshot is not a full Home Screen backup

The icon layout returned by `cfgutil` does not fully capture widgets or duplicate Home Screen entries for the same app. The tool cannot infer omitted information from an app inventory. An app-entry count check only checks the entries present in the captured representation.

Applying a new layout can remove or change widget placement, and you may have to add widgets again. Keep a personal visual record before writing if those placements matter. Saving a before snapshot is useful for inspection, but it does **not** establish that a lossless rollback is possible. The tool does not automatically restore a previous layout after a failure.

## Checks around a write

Before writing, the tool reads the actual device again and requires an exact match with the selected plan baseline. If the device already matches the target, it verifies without writing. It also asks the user to confirm the device and entry counts in a terminal. A noninteractive run must explicitly supply `--yes`. Both modes require `--accept-widget-changes` and use the same validation.

Before and after snapshots are recorded locally. Post-write verification compares app-entry multiplicities, rather than just unique app identifiers, and checks the Dock, folder contents, and page structure. Unexpected, missing, or repeated entries are not considered a successful application. Read the verification report before deciding whether another write is appropriate.

No check can stop iOS from making its own later changes. The tool does not automatically retry a write or automatically restore after an error.

## App Library insertion

In one real-device trial, iOS inserted additional apps from the App Library after applying a layout. The initial plan's app set therefore differed from the readback. This is an observation from that trial, not a claim that every device behaves this way.

Unexpected entries cause verification to fail. To include them intentionally, take a new snapshot, generate a plan using `--source` with that snapshot, review it, and apply against the newly checked baseline. The [usage guide](usage.md#when-verification-fails) shows the commands. Do not repeatedly apply the old plan in response to a mismatch.

## Compatibility and color accuracy

The underlying method used Apple Configurator / `cfgutil` 2.21. The current Configurator [App Store listing](https://apps.apple.com/us/app/apple-configurator/id1037126344?mt=12) requires macOS 15.7 or later. That method has one real-device trial on iOS 27.0.1. The reusable CLI in this repository has only synthetic and mocked-device tests and has not itself been validated on a real phone. There is no promise of universal compatibility.

The original one-device arrangement used AI-assisted visual classification and manual correction. This open-source CLI instead uses a local HSV heuristic and manual overrides; it does not automatically reproduce that earlier visual classification. White backgrounds, dark blue icons, gradients, and multicolor artwork can be misclassified. Check contact sheets and use manual overrides before writing. Custom, tinted, or changed icons may differ from the artwork exported through Configurator.

Missing or unreadable PNG files and icon-export warnings are recorded in `scan-report.json`. Missing images and web clips without artwork default to `multicolor`, with unoverridden items listed in `plan.json` under `needs_color_review`. These placeholders do not automatically prevent `apply`. Review them explicitly rather than treating a valid plan as proof that every color is correct.

## Privacy and icon rights

An ECID, app inventory, icon set, contact sheet, and layout snapshot may reveal information about a device or its owner. Store these files under `.local/` and keep them out of Git. Removing a file in a later commit does not remove it from repository history.

The public examples use synthetic data. MIT covers this project's code; it does not grant a license to redistribute third-party App Store icons. App names and icons belong to their respective rights holders. This project is not affiliated with or endorsed by Apple.
