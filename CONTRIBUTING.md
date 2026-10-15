# Contributing

Small fixes, reproducible bug reports, and improvements to local color classification are welcome. This project uses Python 3.10 or later and Pillow.

## Local setup

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests
python -m iphone_color_pages demo --output .local/demo
```

Keep device work separate from local tests. Tests and synthetic demos should not need an attached iPhone. Do not run `apply` as part of a test suite or unattended retry workflow.

## Report a problem

Include the Python version, macOS version, Configurator / `cfgutil` version, command used, and a redacted error. For layout bugs, provide the smallest synthetic layout that reproduces the problem. Say whether a write was attempted and whether the error happened before or after it.

Do not attach real ECIDs, app inventories, exported icons, unredacted logs, Home Screen screenshots, or session directories. Store local data under `.local/`; confirm staged changes contain no personal device data before committing. Public examples must use synthetic identifiers, names, icons, and layouts.

## Change expectations

- Preserve the rule that `apply` is the only layout-writing command.
- Keep fresh-baseline checks, explicit write confirmation, widget acknowledgment, and post-write validation in place.
- Preserve entry multiplicities and the source Dock; a set of app identifiers is not enough for validation.
- Never automatically retry a write or restore a layout after failure.
- Do not add cloud classification, uploads, API-key requirements, or telemetry without an explicit design discussion.
- Add focused tests for changed parsing, planning, or verification behavior, using synthetic data.
- Update both READMEs and the usage guide when command behavior changes.

Run `python -m unittest discover -s tests` before submitting a change, and describe the checks actually performed. Do not claim device compatibility based only on local tests.

Contributions are accepted under the repository's [MIT License](LICENSE). Third-party app artwork is not covered by that license.
