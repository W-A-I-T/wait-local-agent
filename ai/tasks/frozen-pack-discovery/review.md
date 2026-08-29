# Review criteria

Review the branch specifically for:

1. whether frozen discovery mounts only known built-in first-party modules;
2. whether normal source/wheel dynamic discovery remains unchanged;
3. whether explicit candidate lists used by tests/callers remain authoritative;
4. whether the fix can weaken pack locking, RBAC, approval, or route dependencies;
5. whether the desktop CI sidecar assertion remains the authoritative end-to-end proof.

The branch should not be merged if the built sidecar still returns no `mounted_router` entries from `/packs/status`.
