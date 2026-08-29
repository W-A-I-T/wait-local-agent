# Security boundary

The explicit frozen list contains only first-party module import names already shipped in the application bundle. It does not accept caller input, paths, package names, or executable content. Loading still passes through the existing manifest validation, license locking, RBAC/route dependencies, and normal pack router mounting path.
