# Verification contract

Required before merge:

- backend test suite and 95.00% exact coverage gate pass;
- Windows backend job passes;
- UI job passes;
- gitleaks passes;
- compose-browser passes;
- desktop sidecar builds;
- frozen sidecar `/packs/status` reports `microsoft-admin` with `mounted_router=true`;
- no pack licensing, RBAC, approval, or route-dependency regression.
