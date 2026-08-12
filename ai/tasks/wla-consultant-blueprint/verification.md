# Verification

- Timestamp: 2026-08-12T00:36:14Z

## Command

`PYTHONPATH=src python -m pytest --cov=wait_local_agent --cov-report=term -q -k "not test_docling_parser_missing_dependency_errors_cleanly and not test_qdrant_local_backend_missing_dependency_errors"`

- Status: passed

### Output

    ........................................................................ [  7%]
    ........................................................................ [ 15%]
    ........................................................................ [ 23%]
    ........................................................................ [ 31%]
    ........................................................................ [ 39%]
    ........................................................................ [ 47%]
    ........................................................................ [ 55%]
    ........................................................................ [ 63%]
    ........................................................................ [ 71%]
    ........................................................................ [ 79%]
    ........................................................................ [ 87%]
    ........................................................................ [ 95%]
    .............................................                            [100%]
    =============================== warnings summary ===============================
    ../wait-local-agent/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
      /home/josephp/wait-local-agent/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
        from starlette.testclient import TestClient as TestClient  # noqa
    
    tests/test_founder_surface.py::test_founder_error_handlers_map_remote_failures[error2-413]
      /home/josephp/wait-local-agent-consultant/tests/test_founder_surface.py:753: StarletteDeprecationWarning: 'HTTP_413_REQUEST_ENTITY_TOO_LARGE' is deprecated. Use 'HTTP_413_CONTENT_TOO_LARGE' instead.
        response = founder_module.launch_passport_error_handler(request, error)
    
    -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
    
    ---------- coverage: platform linux, python 3.12.3-final-0 -----------
    Name                                                Stmts   Miss Branch BrPart  Cover   Missing
    -----------------------------------------------------------------------------------------------
    src/wait_local_agent/__init__.py                        2      0      0      0   100%
    src/wait_local_agent/api/__init__.py                    0      0      0      0   100%
    src/wait_local_agent/api/app.py                       831     36    114     10    95%   368-369, 386, 394, 406, 414-417, 428, 436-437, 513-520, 537-540, 566, 586, 589-590, 760-761, 775-776, 1049, 1234, 1447-1448, 1529-1530, 1557, 1567, 1588, 1589->1591, 1604
    src/wait_local_agent/api/founder.py                   378      1    128      3    99%   356, 504->508, 599->595
    src/wait_local_agent/api/packs/__init__.py              2      0      0      0   100%
    src/wait_local_agent/api/packs/loader.py              263      5     84      6    97%   87, 230->237, 260, 265, 280, 310->313, 373
    src/wait_local_agent/api/server_entry.py               19      0      2      0   100%
    src/wait_local_agent/backup.py                        119      0     24      0   100%
    src/wait_local_agent/cli.py                           908     42    168     17    95%   208-209, 237->exit, 279-280, 283-285, 302, 330-331, 341-342, 404->417, 430->434, 528, 531, 534, 553, 566-567, 578-579, 614-615, 777, 786, 788, 804, 818, 824, 907, 918, 1027-1028, 1031-1032, 1084, 1108, 1127, 1209-1210, 1374, 1393, 1473
    src/wait_local_agent/cloud_connectors/__init__.py       6      0      0      0   100%
    src/wait_local_agent/cloud_connectors/_safe.py         46      8     26      6    78%   20, 70, 76, 80, 82, 85-93
    src/wait_local_agent/cloud_connectors/adapters.py     302     11    102      8    95%   249-259, 282, 285, 297->299, 304, 317, 406, 416, 430
    src/wait_local_agent/cloud_connectors/aws.py          229      9     76      4    95%   87->104, 161, 228-234, 269
    src/wait_local_agent/cloud_connectors/azure.py        233      0     80      3    99%   99->exit, 105->exit, 114->133
    src/wait_local_agent/cloud_connectors/gcp.py          290      4    114      4    98%   131, 145->167, 214, 351-352, 408->406
    src/wait_local_agent/cloud_connectors/m365.py         282      7    100      3    96%   369, 373, 434-438
    src/wait_local_agent/collectors.py                   1840     80    550     45    95%   202, 222, 306-307, 327, 330, 332, 346-347, 468, 472-473, 475, 477, 483->489, 487-488, 491, 495-500, 507, 510-511, 513->512, 699, 710, 937, 1228, 1236, 1242, 1246, 1296, 1306, 1413, 1422, 1430, 1433, 1467, 1490-1491, 2221, 2251, 2275->2261, 2286, 2493-2494, 2499-2502, 2512, 2534-2537, 2542->2540, 2572, 2577->2576, 2922, 2940-2943, 3283, 3286, 3486-3487, 3496, 3505, 3515, 3522, 3532, 3542-3543, 3557, 3567, 3570, 3636->3634, 3682->3684, 3694->3696, 3698, 3742, 3770, 3773
    src/wait_local_agent/config.py                         91      2      8      0    98%   34-35
    src/wait_local_agent/connectors.py                    124      9     66      9    91%   51, 148, 173, 226, 239, 275, 280, 325, 340
    src/wait_local_agent/consultant.py                    131     19     56     17    80%   44, 47, 50, 134, 146, 149, 151, 160, 162, 168, 177, 185-188, 196, 198, 219, 221, 241
    src/wait_local_agent/document_parsing.py               87      3     20      2    95%   79-80, 101->103, 113
    src/wait_local_agent/founder_bundle.py                306      2    132      7    98%   186->191, 189->187, 198->202, 200->202, 232, 391->399, 488
    src/wait_local_agent/halopsa.py                       339     13    128      8    95%   164-165, 215-216, 251->253, 273-274, 503, 507->513, 512, 525, 533, 536-537, 601
    src/wait_local_agent/hudu.py                          158      8     58      7    93%   37, 59, 78->80, 114, 117, 147-148, 285, 289
    src/wait_local_agent/knowledge.py                      85      3     28      2    96%   57, 90, 112
    src/wait_local_agent/lp_client.py                     219      1     44      1    99%   207
    src/wait_local_agent/lp_polling.py                     82      1     16      1    98%   79
    src/wait_local_agent/models.py                        435      0      0      0   100%
    src/wait_local_agent/observability.py                 235      0     56      0   100%
    src/wait_local_agent/providers.py                     141      0     36      0   100%
    src/wait_local_agent/rbac.py                           52      0     14      0   100%
    src/wait_local_agent/reports/__init__.py                4      0      0      0   100%
    src/wait_local_agent/reports/builders.py               54      1     10      0    98%   143
    src/wait_local_agent/reports/hardening_checks.py      167      0     14      0   100%
    src/wait_local_agent/reports/models.py                 57      0      2      0   100%
    src/wait_local_agent/reports/renderers.py              72      0     30      0   100%
    src/wait_local_agent/reports/schemas.py                27      1     18      1    96%   52
    src/wait_local_agent/reports/service.py                29      1      4      1    94%   78
    src/wait_local_agent/retrieval.py                      30      0     14      0   100%
    src/wait_local_agent/scheduler.py                     113      2     34      8    93%   67->71, 69->71, 75->79, 77->79, 83->87, 85->87, 119, 166
    src/wait_local_agent/security.py                        7      0      0      0   100%
    src/wait_local_agent/services.py                       28      0      8      0   100%
    src/wait_local_agent/smart_actions.py                 345      0    100      0   100%
    src/wait_local_agent/store.py                        1019     69    262     62    90%   631, 700, 720, 784, 829, 879, 1062, 1089, 1114, 1150, 1162, 1180, 1229, 1233, 1275, 1299, 1331, 1344, 1363, 1383, 1387, 1403, 1406, 1485, 1505, 1567, 1705, 1718, 1739->1737, 1742, 1889, 1900, 1975, 1996, 2043, 2082, 2224, 2228, 2300, 2304, 2318, 2351, 2361, 2375, 2423, 2433, 2513, 2524, 2559, 2649, 2707, 2711, 2756, 2834, 2840, 2862, 2894, 2898, 2993, 2996, 3097-3103, 3117, 3165, 3259, 3281-3282, 3353-3354
    src/wait_local_agent/update_channel.py                183      7     52      5    95%   45, 49, 51, 58, 62, 304-305
    src/wait_local_agent/vault.py                          70      5     14      1    93%   59-60, 71, 90-91
    src/wait_local_agent/vector_search.py                  83      4     26      4    93%   51-52, 60, 73->exit, 136->exit, 153
    src/wait_local_agent/workflows.py                      41      0     14      0   100%
    -----------------------------------------------------------------------------------------------
    TOTAL                                               10564    354   2832    245    95%
    
    Required test coverage of 95.0% reached. Total coverage: 95.39%

## Command

`ruff check src/wait_local_agent/consultant.py src/wait_local_agent/models.py src/wait_local_agent/store.py src/wait_local_agent/api/app.py src/wait_local_agent/cli.py tests/test_consultant.py tests/test_api.py tests/test_cli.py`

- Status: passed

### Output

    All checks passed!

## Command

`python -m mypy src/wait_local_agent/consultant.py src/wait_local_agent/models.py src/wait_local_agent/store.py`

- Status: passed

### Output

    Success: no issues found in 3 source files

## Command

`python3 -m compileall -q src/wait_local_agent`

- Status: passed

### Output

    

## Command

`git diff --check`

- Status: passed

### Output

    

## Command

`pytest`

- Status: failed

### Output

    [output byte limit applied]
    [output line limit applied]
    
    ==================================== ERRORS ====================================
    ______________________ ERROR collecting tests/test_api.py ______________________
    ImportError while importing test module '/home/josephp/wait-local-agent-consultant/tests/test_api.py'.
    Hint: make sure your test modules/packages have valid Python names.
    Traceback:
    /usr/lib/python3.12/importlib/__init__.py:90: in import_module
        return _bootstrap._gcd_import(name[level:], package, level)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    tests/test_api.py:9: in <module>
        import wait_local_agent.api.app as app_module
    src/wait_local_agent/api/app.py:18: in <module>
        from slowapi import Limiter
    E   ModuleNotFoundError: No module named 'slowapi'
    _________________ ERROR collecting tests/test_audit_export.py __________________
    ImportError while importing test module '/home/josephp/wait-local-agent-consultant/tests/test_audit_export.py'.
    Hint: make sure your test modules/packages have valid Python names.
    Traceback:
    /usr/lib/python3.12/importlib/__init__.py:90: in import_module
        return _bootstrap._gcd_import(name[level:], package, level)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    tests/test_audit_export.py:8: in <module>
        from wait_local_agent.api.app import create_app
    src/wait_local_agent/api/app.py:18: in <module>
        from slowapi import Limiter
    E   ModuleNotFoundError: No module named 'slowapi'
    ____________________ ERROR collecting tests/test_backup.py _____________________
    ImportError while importing test module '/home/josephp/wait-local-agent-consultant/tests/test_backup.py'.
    Hint: make sure your test modules/packages have valid Python names.
    Traceback:
    /usr/lib/python3.12/importlib/__init__.py:90: in import_module
        return _bootstrap._gcd_import(name[level:], package, level)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    tests/test_backup.py:18: in <module>
        from wait_local_agent.cli import app
    src/wait_local_agent/cli.py:15: in <module>
        from wait_local_agent.api.app import create_app
    src/wait_local_agent/api/app.py:18: in <module>
        from slowapi import Limiter
    E   ModuleNotFoundError: No module named 'slowapi'
    ... [output lines omitted] ...
        from wait_local_agent.api.app import create_app
    src/wait_local_agent/api/app.py:18: in <module>
        from slowapi import Limiter
    E   ModuleNotFoundError: No module named 'slowapi'
    ________________ ERROR collecting tests/test_update_channel.py _________________
    ImportError while importing test module '/home/josephp/wait-local-agent-consultant/tests/test_update_channel.py'.
    Hint: make sure your test modules/packages have valid Python names.
    Traceback:
    /usr/lib/python3.12/importlib/__init__.py:90: in import_module
        return _bootstrap._gcd_import(name[level:], package, level)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    tests/test_update_channel.py:13: in <module>
        import wait_local_agent.api.app as api_app_module
    src/wait_local_agent/api/app.py:18: in <module>
        from slowapi import Limiter
    E   ModuleNotFoundError: No module named 'slowapi'
    =========================== short test summary info ============================
    ERROR tests/test_api.py
    ERROR tests/test_audit_export.py
    ERROR tests/test_backup.py
    ERROR tests/test_cli.py
    ERROR tests/test_collectors.py
    ERROR tests/test_collectors_e2e.py
    ERROR tests/test_connectors_validate.py
    ERROR tests/test_founder_surface.py
    ERROR tests/test_launch_edge_coverage.py
    ERROR tests/test_lp_coverage_topup.py
    ERROR tests/test_ops_routes.py
    ERROR tests/test_pack_loader.py
    ERROR tests/test_packs_cli.py
    ERROR tests/test_rate_limit.py
    ERROR tests/test_rbac.py
    ERROR tests/test_reports.py
    ERROR tests/test_scheduler.py
    ERROR tests/test_security_vault.py
    ERROR tests/test_server_entry.py
    ERROR tests/test_update_channel.py
    !!!!!!!!!!!!!!!!!!! Interrupted: 20 errors during collection !!!!!!!!!!!!!!!!!!!
    2 deselected, 20 errors in 2.45s

## Summary

- Passed: 5
- Failed: 1
