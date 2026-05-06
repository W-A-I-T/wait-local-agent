from __future__ import annotations

import shutil
from pathlib import Path

from wait_local_agent.store import Store


def backup_state(store: Store, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if store.path.exists():
        shutil.copy2(store.path, destination)
    else:
        Store(store.path)
        shutil.copy2(store.path, destination)
    return destination


def restore_state(store: Store, source: Path) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, store.path)
    Store(store.path)
    return store.path
