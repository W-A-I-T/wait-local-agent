# Expected result

A source/wheel install continues to discover packs dynamically. A PyInstaller-frozen desktop sidecar additionally seeds discovery with the known built-in public pack module `packs.microsoft_admin`, so the packaged product exposes the same Microsoft Admin router that is present in source.
