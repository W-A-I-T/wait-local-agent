# Implementation summary

`loader.py` now seeds `packs.microsoft_admin` only when running under a frozen interpreter (`sys.frozen`). It then continues through the existing package enumeration and deduplication path. The regression test simulates a frozen runtime whose `pkgutil.iter_modules()` returns no candidates and verifies the actual Microsoft Admin manifest still loads.
