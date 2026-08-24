# Telemetry and License Metering

WAIT Local Agent keeps three separate systems separate. One does not silently
turn into another.

## 1. Local audit

Audit records stay in the customer's local database and local files. The
public runtime does not transmit those records to WAIT and has no phone-home
service for customer activity.

## 2. Support diagnostics

Support diagnostics are specified as an explicit, customer-initiated,
redacted flow. The forthcoming design, including preview and download before
any optional upload, is defined in [Diagnostics &
Support](../operations/diagnostics-and-support.md). It is not an automatic
telemetry path.

## 3. Commercial entitlement metering

Commercial entitlement metering belongs to a separately licensed commercial
pack, not the public runtime. If enabled under that separate agreement, it
would carry only entitlement fields: license ID, installation ID, enabled
packs, managed-client count, version, expiry, and over-limit status.

This commercial system does not turn the Community runtime's local audit into
a usage meter.

## Automatic outbound non-goals

The public runtime does not automatically send any of the following off the
machine:

- ticket bodies or incident content;
- email content;
- documents;
- prompts;
- customer names;
- hostnames;
- tenant IDs;
- credentials; or
- other customer work content.

Customer content is not used for model training by default.

