# Host collection mode

The normal `docker compose up` topology is unchanged: Linux collectors inspect
the API container. Those results are intentionally reported as
`collection_scope=container`; they describe the appliance container, not the
host that runs Docker.

Host collection is an explicit opt-in:

```bash
docker compose --profile host-collect up api-host-collect
```

Start `api-host-collect` by name as shown. Do not start the whole profile with
`docker compose --profile host-collect up`: the normal `api` service publishes
port 8788, while the host-collection service uses the host network namespace.

The Compose file keeps the host-collection service standalone so the default
`docker compose up` configuration does not depend on newer Compose YAML tags.

The profile runs a separate API service with the host PID and network
namespaces, and read-only host mounts at `/host/proc`, `/host/sys`, and
`/host/etc`. `WAIT_HOST_ROOT=/host` makes the Linux collectors read those
mounted paths, while `WAIT_COLLECTION_SCOPE=host` records the operator's
explicit scope assertion. The profile does not enable privileged mode, writable
host mounts, or additional Linux capabilities.

Collection scope is conservative: automatic detection reports `container` only
when container evidence is present, and reports `unknown` when the available
signals do not prove either scope. `unknown` is surfaced in collector results,
API responses, and CLI output; it must not be read as host scope. The host
profile supplies an explicit `host` assertion and an absolute `WAIT_HOST_ROOT`.

`WAIT_HOST_ROOT` rebases absolute collector paths only. Relative collector paths
remain process-local when no host root is configured; when `WAIT_HOST_ROOT` is
configured, a relative collector path is rejected. A relative
`WAIT_HOST_ROOT` is also rejected. These fail-closed rules prevent a malformed
host-collection configuration from reading the container filesystem while
claiming host scope. Rooted paths containing `..` segments or escaping the
resolved root are rejected as well.

## Security implications

This mode is intended for an administrator who has decided that the appliance
container may inspect the host. A read-only mount is still an information
exposure: `/host/etc` can contain host secrets such as shadow files, private
keys, service credentials, and other configuration secrets. Host PID and
network namespaces also widen what processes and network state the container
can observe. A read-only bind prevents writes through that mount, but it does
not make the data non-sensitive or prevent application-level disclosure.

The `host` scope value is operator-asserted by the profile. Do not set it in a
different deployment unless the mounted paths really describe the intended
host; otherwise results can be labeled inaccurately.

## Pre-enable checklist

- Confirm the API image, source, and dependencies are trusted and up to date.
- Review who can access the API, its logs, exports, backups, and the Docker
  host.
- Enable authentication and use a production secrets backend before exposing
  the API beyond the local host.
- Confirm that `/proc`, `/sys`, and `/etc` are the intended host paths and that
  the host's secret-handling policy permits this inspection.
- Prefer a dedicated collection window and stop the profile when collection is
  complete.
- Treat collected evidence and exported reports as containing host-sensitive
  information.
