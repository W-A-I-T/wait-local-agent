# Frozen capability-pack discovery

The desktop sidecar is a PyInstaller-frozen executable. Hidden imports make first-party capability-pack modules importable, but PyInstaller's frozen import archive is not guaranteed to expose those modules through `pkgutil.iter_modules()`.

WAIT therefore keeps a minimal explicit list of built-in public pack modules for frozen runtime discovery while preserving normal dynamic discovery for source/wheel installs and separately installed packs.

The desktop CI gate remains authoritative: the built sidecar must start and `/packs/status` must report at least one mounted router whenever `src/packs/**` exists.
