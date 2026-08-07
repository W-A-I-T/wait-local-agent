# Host collection mode

The normal `docker compose up` topology is unchanged: Linux collectors inspect
the API container. Those results are intentionally reported as
`collection_scope=container`; they describe the appliance container, not the
host that runs Docker.

Host collection is an explicit opt-in:

```bash
docker compose --profile host-collect up api-host-collect
```

The profile runs a separate API service with the host PID and network
namespaces, and read-only host mounts at `/host/proc`, `/host/sys`, and
`/host/etc`. `WAIT_HOST_ROOT=/host` makes the Linux collectors read those
mounted paths, while `WAIT_COLLECTION_SCOPE=host` records the operator's
explicit scope assertion. The profile does not enable privileged mode, writable
host mounts, or additional Linux capabilities.

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
