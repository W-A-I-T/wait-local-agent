# Frozen pack discovery repair

## Problem

The new desktop CI gate on `main` proves the PyInstaller sidecar builds but does not mount any capability-pack router. Source discovery relies on `pkgutil.iter_modules()`, which is not a reliable inventory mechanism for modules stored in a frozen import archive.

## Change

- Keep the existing dynamic discovery path for ordinary installs.
- Add an explicit first-party built-in pack module list only when `sys.frozen` is true.
- Cover the failure mode with a regression test that makes `pkgutil.iter_modules()` return no modules.
- Keep the built-sidecar `/packs/status` CI assertion as the end-to-end proof.

## Non-goals

- No change to pack licensing.
- No change to router authorization.
- No arbitrary import of unknown frozen modules.
- No weakening or bypass of the sidecar verification gate.
